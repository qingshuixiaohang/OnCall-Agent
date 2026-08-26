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

import re
from collections.abc import AsyncGenerator, Sequence
from datetime import datetime
from typing import Any

from langchain.agents import create_agent
from langchain_core.documents import Document
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
from app.core.llm_factory import llm_factory
from app.core.mem0_manager import asearch_memory, schedule_memory_save
from app.tools import get_current_time, retrieve_knowledge


class AgentState(TypedDict):
    """Agent 状态"""
    messages: Sequence[BaseMessage]


# ============================================================================
# RagAgentService
# ============================================================================

class RagAgentService:
    """RAG Agent 服务 - 使用 LangGraph + ChatQwen 原生集成"""

    _NO_EVIDENCE_RESPONSE = (
        "当前知识库未覆盖这个问题，暂时无法根据现有资料给出可靠答案。"
        "请补充相关文档或提供更具体的服务信息。"
    )
    _RETRIEVAL_ERROR_RESPONSE = (
        "知识库检索暂时失败，无法确认相关资料。请稍后重试，或检查知识库服务。"
    )

    def __init__(self, streaming: bool = True):
        self.model_name = config.llm_model
        self.streaming = streaming
        self.system_prompt = ""

        self.model = llm_factory.create_chat_model(
            temperature=0.7,
            streaming=streaming,
        )

        self.tools = [retrieve_knowledge, get_current_time]
        self.mcp_tools: list = []
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
        self.system_prompt = self._build_system_prompt(all_tools)

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
            system_prompt=self._build_system_prompt(tools_without_knowledge),
            middleware=[CompressionMiddleware()],
        )

        self._agent_initialized = True
        logger.info(f"RAG Agent 编译完成，工具数: {len(all_tools)}")

    def _build_system_prompt(self, all_tools: list | None = None) -> str:
        from textwrap import dedent

        tool_descriptions = self._extract_tool_descriptions(all_tools) if all_tools else ""

        base_prompt = dedent("""
            你是一个专业的智能运维（AIOps）助手，能够使用多种工具来帮助用户排查系统问题、查询日志和监控数据。

            ## 核心能力
            1. **日志查询与分析**: 查询腾讯云 CLS 中的日志，支持按级别、关键词、时间范围筛选
            2. **监控指标查询**: 查询服务的 CPU 使用率、内存使用率等监控数据
            3. **知识检索**: 从内部知识库中检索相关的运维经验和最佳实践
            4. **时间查询**: 获取当前时间戳，用于日志查询的时间范围计算

            {tool_section}

            ## 工具使用核心原则

            ### 原则 1：使用精确的工具名称
            你必须使用系统提供的工具列表中**精确的工具名称**。不要自作主张地创造或猜测工具名。

            ### 原则 2：查询日志前必须先找到 Topic
            日志查询的标准工作流（必须严格遵循）：
            ```
            步骤1: search_topic_by_service_name(service_name="服务名")
                   -> 获取真实的 topic_id
            步骤2: get_current_timestamp()
                   -> 获取当前毫秒时间戳
            步骤3: 计算 start_time = current_ts - (N分钟 * 60 * 1000)
            步骤4: search_log(topic_id=步骤1获取的ID, start_time=步骤3计算值, end_time=步骤2获取值, query="查询条件")
            ```
            禁止跳过步骤1直接调用 search_log！
            禁止编造 topic_id（如 "topic-1234567890"）！

            ### 原则 3：监控指标查询可直接进行
            查询 CPU 或内存使用率不需要预先查找任何 ID。

            ### 原则 4：优先使用已有知识库证据
            如果用户消息中包含 `[内部知识库证据]`，必须优先依据这些资料回答，
            不要重复调用 retrieve_knowledge；引用文档内容时注明来源文件名。

            ## 回答风格要求（极其重要！）

            ### 禁止事项
            1. **禁止暴露思考过程**: 不要在回答中出现"我需要先..."等内心独白
            2. **禁止展示步骤编号**: 不要出现"步骤1/2/3"等中间步骤罗列
            3. **禁止预告工具调用**: 不要说"我将使用XX工具查询"
            4. **禁止边想边说**: 所有工具调用在后台静默完成

            ### 正确做法
            1. **静默执行**: 所有工具调用在内部完成
            2. **只输出最终答案**: 等所有工具调用完成后，一次性给出结构清晰的最终回答
            3. **直接呈现结果**: 用表格、列表等形式直接展示数据
            4. **失败时简洁说明**: 工具失败时直接告知结果和建议

            ## 其他回答要求
            - 保持友好、专业的语气
            - 回答简洁明了，重点突出
            - 基于工具返回的真实数据，不编造信息
            - 如果工具调用失败，诚实地告知失败原因
            - 如有不确定的地方，明确说明
        """).strip()

        if tool_descriptions:
            return base_prompt.replace("{tool_section}", tool_descriptions)
        return base_prompt.replace("{tool_section}", "")

    def _extract_tool_descriptions(self, tools: list) -> str:
        from textwrap import dedent
        descriptions = []
        for tool in tools:
            name = getattr(tool, "name", str(tool))
            desc = getattr(tool, "description", "")
            if desc:
                short = desc[:120].replace("\n", " ").strip()
                descriptions.append(f"  - **`{name}`**: {short}")
            else:
                descriptions.append(f"  - **`{name}`**")
        if descriptions:
            joined = "\n".join(descriptions)
            return dedent(f"""
                ## 可用工具清单

                {joined}

                以上是你可以使用的所有工具。请严格遵守工具名称和参数要求。
            """).strip()
        return ""

    _KNOWLEDGE_TERMS = (
        "排查",
        "故障",
        "异常",
        "原因",
        "怎么处理",
        "如何处理",
        "解决方案",
        "最佳实践",
        "历史案例",
        "报错",
        "错误",
        "超时",
        "连接失败",
        "不可用",
        "告警",
        "cpu",
        "内存",
        "redis",
        "kafka",
        "数据库",
        "timeout",
        "error",
        "exception",
        "incident",
        "runbook",
    )
    _TRIVIAL_QUERY_PATTERN = re.compile(
        r"^(你好|嗨|hello|hi|你是谁|你有什么功能|谢谢|感谢|再见|现在几点|几点了)[？?！!。.]?$",
        re.IGNORECASE,
    )

    @classmethod
    def _should_prefetch_knowledge(cls, question: str) -> bool:
        normalized = question.strip().lower()
        if not normalized or cls._TRIVIAL_QUERY_PATTERN.fullmatch(normalized):
            return False
        return len(normalized) >= 6 and any(term in normalized for term in cls._KNOWLEDGE_TERMS)

    @staticmethod
    def _normalize_knowledge_result(result: Any) -> tuple[str, list[Document]]:
        if isinstance(result, tuple) and len(result) == 2:
            context, docs = result
            if isinstance(docs, list):
                return str(context or ""), docs
            return str(context or ""), [docs]
        if isinstance(result, str):
            return result, []
        if isinstance(result, list):
            return "", result
        return "", []

    @staticmethod
    def _serialize_knowledge_documents(docs: list[Document]) -> list[dict[str, Any]]:
        sources = []
        for index, document in enumerate(docs, start=1):
            metadata = document.metadata or {}
            headers = [
                str(metadata[key])
                for key in ("h1", "h2", "h3")
                if metadata.get(key)
            ]
            sources.append(
                {
                    "index": index,
                    "page_content": document.page_content[:1600],
                    "metadata": {
                        "source": metadata.get("_file_name")
                        or metadata.get("_source")
                        or "未知来源",
                        "title": " > ".join(headers),
                        "service_name": metadata.get("service_name"),
                        "environment": metadata.get("environment"),
                    },
                    "score": metadata.get("rerank_score"),
                }
            )
        return sources

    async def _prepare_question(
        self, question: str
    ) -> tuple[str, list[dict[str, Any]], bool, str]:
        """对运维问题预先检索一次知识库，避免完全依赖 LLM 选工具。"""
        if not self._should_prefetch_knowledge(question):
            return question, [], False, "skipped"

        try:
            result = await retrieve_knowledge.ainvoke({"query": question})
            context, docs = self._normalize_knowledge_result(result)
            sources = self._serialize_knowledge_documents(docs)

            if context.startswith("检索知识时发生错误:"):
                logger.warning(f"预先检索知识库返回错误: {context[:300]}")
                return question, [], False, "error"

            if not docs:
                logger.info("预先检索知识库完成，但没有足够相关的证据")
                return question, [], False, "empty"

            evidence = context or "知识库未找到足够相关的资料。"
            prepared = (
                f"{question}\n\n"
                "[内部知识库证据]\n"
                f"{evidence}\n\n"
                "请优先依据上述证据回答；如果证据不足，请明确说明，不要补造事实。"
                "回答涉及文档内容时，请注明来源文件名。"
            )
            logger.info(f"预先检索知识库完成: 文档数={len(sources)}")
            return prepared, sources, True, "found"
        except Exception as error:
            logger.warning(f"预先检索知识库失败: {error}")
            return question, [], False, "error"

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
                _,
                knowledge_prefetched,
                retrieval_state,
            ) = await self._prepare_question(question)

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
    ) -> AsyncGenerator[dict[str, Any], None]:
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
            ) = await self._prepare_question(question)

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
