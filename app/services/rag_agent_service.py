"""RAG Agent 服务 - 基于 LangGraph 的智能代理

使用 langchain_qwq 的 ChatQwen 原生集成，支持真正的流式输出。
使用 LangGraph 原生 checkpointer（AsyncSqliteSaver / AsyncPostgresSaver）
替代手搓 storage + MemorySaver 混用方案。

持久化机制：
- create_agent(..., checkpointer=...) 让 LangGraph 自动管理消息历史
- 每次调用只需传入新消息，checkpointer 自动追加到历史
- 重启后从 checkpoint 恢复，对话可无缝继续
- 上下文压缩仍通过 CompressionMiddleware 实现
"""

from collections.abc import AsyncGenerator, Sequence
from datetime import datetime
from typing import Any

from langchain.agents import create_agent
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from loguru import logger
from typing_extensions import TypedDict

from app.agent.mcp_client import get_mcp_tools
from app.config import config
from app.core.checkpointer import get_checkpointer, thread_id_with_prefix
from app.core.conversation_compressor import (
    CompressionMiddleware,
)
from app.core.knowledge_prefetcher import KnowledgePrefetcher
from app.core.llm_factory import llm_factory
from app.core.mem0_manager import asearch_memory, schedule_memory_save
from app.core.system_prompt_builder import SystemPromptBuilder
from app.tools import get_current_time

_NO_EVIDENCE_RESPONSE = (
    "当前知识库未覆盖这个问题，暂时无法根据现有资料给出可靠答案。"
    "请补充相关文档或提供更具体的服务信息。"
)
_RETRIEVAL_ERROR_RESPONSE = (
    "知识库检索暂时失败，无法确认相关资料。请稍后重试，或检查知识库服务。"
)


class AgentState(TypedDict):
    """Agent 状态"""
    messages: Sequence[BaseMessage]


# ============================================================================
# RagAgentService
# ============================================================================

class RagAgentService:
    """RAG Agent 服务 - 使用 LangGraph + ChatQwen 原生集成"""

    _NO_EVIDENCE_RESPONSE = _NO_EVIDENCE_RESPONSE
    _RETRIEVAL_ERROR_RESPONSE = _RETRIEVAL_ERROR_RESPONSE

    def __init__(self, streaming: bool = True):
        self.model_name = config.llm_model
        self.streaming = streaming
        self.system_prompt = ""

        self.model = llm_factory.create_chat_model(
            temperature=0.7,
            streaming=streaming,
        )

        self.tools = [get_current_time]
        self.mcp_tools: list = []

        self.knowledge_prefetcher = KnowledgePrefetcher()
        self.system_prompt_builder = SystemPromptBuilder()

        self.agent = None
        self.agent_without_knowledge = None
        self._agent_initialized = False

        logger.info(f"RAG Agent 服务初始化完成, model={self.model_name}, streaming={streaming}")

    async def _initialize_agent(self):
        """异步初始化 Agent（含 checkpointer）"""
        if self._agent_initialized:
            return

        try:
            mcp_tools = await get_mcp_tools()
            logger.info(f"成功加载 {len(mcp_tools)} 个 MCP 工具")
        except Exception as e:
            logger.warning(f"MCP 工具加载失败: {e}")
            mcp_tools = []

        self.mcp_tools = mcp_tools
        all_tools = self.tools + self.mcp_tools
        self.system_prompt = self.system_prompt_builder.build(all_tools)

        compression_middleware = CompressionMiddleware()

        # 使用统一 checkpointer（由 lifespan 初始化）
        checkpointer = get_checkpointer()

        self.agent = create_agent(
            self.model,
            tools=all_tools,
            checkpointer=checkpointer,
            system_prompt=self.system_prompt,
            middleware=[compression_middleware],
        )

        tools_without_knowledge = [
            tool
            for tool in all_tools
            if getattr(tool, "name", "") != "retrieve_knowledge"
        ]
        self.agent_without_knowledge = create_agent(
            self.model,
            tools=tools_without_knowledge,
            checkpointer=checkpointer,
            system_prompt=self.system_prompt_builder.build(tools_without_knowledge),
            middleware=[CompressionMiddleware()],
        )

        self._agent_initialized = True
        logger.info(f"RAG Agent 编译完成，工具数: {len(all_tools)}")

    # ------------------------------------------------------------------
    # 查询接口
    # ------------------------------------------------------------------

    async def query(self, question: str, session_id: str) -> str:
        """非流式查询

        使用 checkpointer 自动管理消息历史，无需手动恢复/保存。
        """
        logger.info(f"[会话 {session_id}] RAG 查询（非流式）: {question}")

        try:
            (
                augmented_question,
                _,  # sources (not used in non-streaming)
                knowledge_prefetched,
                retrieval_state,
            ) = await self.knowledge_prefetcher.prefetch(question)

            if retrieval_state == "empty":
                logger.info(f"[会话 {session_id}] 空召回，直接返回知识库拒答")
                return self._NO_EVIDENCE_RESPONSE
            if retrieval_state == "error":
                logger.warning(f"[会话 {session_id}] 知识库检索失败，停止回答生成")
                return self._RETRIEVAL_ERROR_RESPONSE

            await self._initialize_agent()

            # === Mem0 记忆注入 ===
            memory_context = await asearch_memory(query=question, limit=3)
            if memory_context:
                augmented_question = f"{augmented_question}\n\n{memory_context}"
                logger.info(f"[会话 {session_id}] RAG 注入 {len(memory_context)} 字记忆上下文")
            # === 结束 ===

            thread_id = thread_id_with_prefix(session_id, "rag")
            config_dict = {"configurable": {"thread_id": thread_id}}

            # 只需传入新问题，checkpointer 自动恢复历史消息
            agent = self.agent_without_knowledge if knowledge_prefetched else self.agent
            result = await agent.ainvoke(
                {"messages": [HumanMessage(content=augmented_question)]},
                config=config_dict,
            )

            messages = result.get("messages", [])
            if messages:
                last = messages[-1]
                answer = last.content if hasattr(last, "content") else str(last)
                logger.info(f"[会话 {session_id}] RAG 查询完成（非流式）")
                # === 保存本轮 RAG 对话到 Mem0 ===
                try:
                    if answer and answer.strip():
                        schedule_memory_save(
                            messages=[
                                {"role": "user", "content": question[:1000]},
                                {"role": "assistant", "content": answer.strip()[:2000]},
                            ],
                            metadata={"type": "rag_chat", "session_id": session_id},
                        )
                except Exception as e:
                    logger.warning(f"[会话 {session_id}] 保存 RAG 记忆失败（不影响主流程）: {e}")
                # === 结束 ===
                return answer

            return "抱歉，无法处理您的请求。"

        except Exception as e:
            logger.error(f"[会话 {session_id}] RAG 查询失败: {e}")
            return f"抱歉，处理请求时出现错误: {str(e)}"

    async def query_stream(
        self, question: str, session_id: str
    ) -> AsyncGenerator[dict[str, Any]]:
        """流式查询

        使用 checkpointer 自动管理消息历史，无需手动恢复/保存。
        """
        logger.info(f"[会话 {session_id}] RAG 查询（流式）: {question}")

        try:
            (
                augmented_question,
                knowledge_sources,
                knowledge_prefetched,
                retrieval_state,
            ) = await self.knowledge_prefetcher.prefetch(question)

            if retrieval_state == "empty":
                logger.info(f"[会话 {session_id}] 空召回，流式返回知识库拒答")
                yield {
                    "type": "search_results",
                    "data": {
                        "query": question,
                        "documents": [],
                        "message": "未找到足够相关的知识库证据",
                    },
                }
                yield {"type": "content", "data": self._NO_EVIDENCE_RESPONSE}
                yield {
                    "type": "complete",
                    "data": {
                        "answer": self._NO_EVIDENCE_RESPONSE,
                        "abstained": True,
                        "reason": "no_evidence",
                    },
                }
                return

            if retrieval_state == "error":
                logger.warning(f"[会话 {session_id}] 知识库检索失败，停止回答生成")
                yield {"type": "content", "data": self._RETRIEVAL_ERROR_RESPONSE}
                yield {
                    "type": "complete",
                    "data": {
                        "answer": self._RETRIEVAL_ERROR_RESPONSE,
                        "abstained": True,
                        "reason": "retrieval_error",
                    },
                }
                return

            await self._initialize_agent()

            if knowledge_prefetched:
                yield {
                    "type": "search_results",
                    "data": {
                        "query": question,
                        "documents": knowledge_sources,
                        "message": "已完成知识库检索",
                    },
                }

            # === Mem0 记忆注入 ===
            memory_context = await asearch_memory(query=question, limit=3)
            if memory_context:
                augmented_question = f"{augmented_question}\n\n{memory_context}"
                logger.info(f"[会话 {session_id}] RAG 注入 {len(memory_context)} 字记忆上下文")
            # === 结束 ===

            thread_id = thread_id_with_prefix(session_id, "rag")
            config_dict = {"configurable": {"thread_id": thread_id}}

            has_error = False
            error_messages: list[str] = []
            assistant_response_parts: list[str] = []

            agent = self.agent_without_knowledge if knowledge_prefetched else self.agent
            async for token, metadata in agent.astream(
                {"messages": [HumanMessage(content=augmented_question)]},
                config=config_dict,
                stream_mode="messages",
            ):
                node_name = (
                    metadata.get("langgraph_node", "unknown")
                    if isinstance(metadata, dict)
                    else "unknown"
                )
                message_type = type(token).__name__

                if message_type in ("AIMessage", "AIMessageChunk"):
                    content_blocks = getattr(token, "content_blocks", None)
                    if content_blocks and isinstance(content_blocks, list):
                        for block in content_blocks:
                            if isinstance(block, dict) and block.get("type") == "text":
                                text = block.get("text", "")
                                if text:
                                    assistant_response_parts.append(text)
                                    yield {"type": "content", "data": text, "node": node_name}

                    if hasattr(token, "tool_calls") and token.tool_calls:
                        for tc in token.tool_calls:
                            tool_name = tc.get("name", "unknown")
                            logger.info(f"[会话 {session_id}] 工具调用: {tool_name}")
                            yield {
                                "type": "tool_call",
                                "data": {
                                    "tool": tool_name,
                                    "status": "start",
                                    "input": tc.get("args", {}),
                                },
                                "node": node_name,
                            }

                elif message_type == "ToolMessage":
                    tool_name = getattr(token, "name", "unknown")
                    tool_content = getattr(token, "content", "")
                    is_error = (
                        getattr(token, "status", "") == "error"
                        if hasattr(token, "status")
                        else False
                    )
                    if is_error:
                        error_messages.append(
                            f"工具 `{tool_name}` 调用失败: {tool_content[:200]}"
                        )
                        has_error = True
                    yield {
                        "type": "tool_result",
                        "data": {
                            "tool": tool_name,
                            "status": "error" if is_error else "success",
                            "content_preview": str(tool_content)[:300]
                            if tool_content
                            else "",
                        },
                        "node": node_name,
                    }

            if has_error and error_messages:
                yield {
                    "type": "warning",
                    "data": {
                        "message": "部分工具调用出现问题",
                        "details": error_messages,
                    },
                }

            logger.info(f"[会话 {session_id}] RAG 查询完成（流式）")

            # === 保存本轮 RAG 对话到 Mem0 ===
            try:
                assistant_response = "".join(assistant_response_parts)
                if assistant_response.strip():
                    schedule_memory_save(
                        messages=[
                            {"role": "user", "content": question[:1000]},
                            {"role": "assistant", "content": assistant_response[:2000]},
                        ],
                        metadata={"type": "rag_chat", "session_id": session_id},
                    )
            except Exception as e:
                logger.warning(f"[会话 {session_id}] 保存 RAG 记忆失败（不影响主流程）: {e}")
            # === 结束 ===

            yield {
                "type": "complete",
                "data": {"answer": assistant_response},
            }

        except Exception as e:
            logger.error(f"[会话 {session_id}] RAG 流式查询失败: {e}")
            yield {"type": "error", "data": str(e)}

    # ------------------------------------------------------------------
    # 会话管理（适配 checkpointer）
    # ------------------------------------------------------------------

    async def get_session_history(self, session_id: str) -> list:
        """获取会话历史（从 checkpointer 中读取）

        从 checkpoint 中反序列化消息列表，转为前端友好的格式。
        """
        await self._initialize_agent()
        thread_id = thread_id_with_prefix(session_id, "rag")

        try:
            snapshot = await self.agent.aget_state({"configurable": {"thread_id": thread_id}})
            if not snapshot or not snapshot.values:
                return []

            messages = snapshot.values.get("messages", [])
            history = []
            for msg in messages:
                if isinstance(msg, SystemMessage):
                    continue

                content = msg.content if hasattr(msg, "content") else str(msg)
                if isinstance(content, list):
                    text_parts = [
                        block.get("text", "")
                        for block in content
                        if isinstance(block, dict) and block.get("type") == "text"
                    ]
                    content = " ".join(text_parts)

                msg_dict = {"content": content, "timestamp": datetime.now().isoformat()}
                if isinstance(msg, HumanMessage):
                    msg_dict["type"] = "human"
                elif isinstance(msg, AIMessage):
                    msg_dict["type"] = "ai"
                elif isinstance(msg, ToolMessage):
                    msg_dict["type"] = "tool"
                    msg_dict["name"] = getattr(msg, "name", "")
                else:
                    continue

                history.append(msg_dict)

            logger.info(f"获取会话历史: {session_id}, 消息数量: {len(history)}")
            return history

        except Exception as e:
            logger.error(f"获取会话历史失败: {session_id}, 错误: {e}")
            return []

    async def clear_session(self, session_id: str) -> bool:
        """清空会话历史（从 checkpointer 中删除 thread）"""
        await self._initialize_agent()
        thread_id = thread_id_with_prefix(session_id, "rag")
        cp = get_checkpointer()

        try:
            await cp.adelete_thread(thread_id)
            logger.info(f"已清除会话历史: {session_id} (thread_id={thread_id})")
            return True
        except Exception as e:
            logger.error(f"清空会话历史失败: {session_id}, 错误: {e}")
            return False

    async def cleanup(self):
        """清理资源"""
        logger.info("清理 RAG Agent 服务资源...")


# 全局单例
rag_agent_service = RagAgentService(streaming=True)
