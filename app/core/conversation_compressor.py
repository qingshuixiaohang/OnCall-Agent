"""对话上下文压缩中间件 - LangGraph Agent 基础设施

当对话消息 token 总数超阈值时，用 LLM 摘要替换旧消息，控制上下文长度。
抽出前位于 app/services/rag_agent_service.py，现为可复用的 core 组件。
"""

from collections.abc import Sequence
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import HumanMessage, RemoveMessage, SystemMessage
from langgraph.graph.message import REMOVE_ALL_MESSAGES
from loguru import logger
from typing_extensions import TypedDict

from app.config import config
from app.core.llm_factory import llm_factory


class AgentState(TypedDict):
    """Agent 状态"""
    messages: list[Any]


class ConversationCompressor:
    """对话上下文压缩器

    当对话消息的 token 总数超过配置的阈值（默认 70% 上下文窗口）时，
    自动使用 LLM 对历史对话进行总结，用简洁的摘要替换旧的详细消息。
    """

    SUMMARIZE_PROMPT = """请将以下对话历史总结为一到两段简洁的摘要。
摘要需要包含：
1. 用户问过的所有问题的要点
2. 助手执行过的关键操作（如调用了什么工具、查到了什么数据）
3. 重要的发现和结论

请直接用中文输出摘要，不要加"对话摘要："等前缀。"""

    def __init__(
        self,
        max_tokens: int = 32768,
        threshold: float = 0.7,
        keep_recent: int = 4,
    ):
        self.max_tokens = max_tokens
        self.threshold = threshold
        self.keep_recent = keep_recent
        self._tokenizer = None
        self._summarization_model = None

    @property
    def tokenizer(self):
        if self._tokenizer is None:
            try:
                import tiktoken
                self._tokenizer = tiktoken.get_encoding("cl100k_base")
                logger.info("tiktoken 编码器已加载: cl100k_base")
            except Exception as e:
                logger.warning(f"tiktoken 不可用: {e}")
        return self._tokenizer

    @property
    def summarization_model(self):
        if self._summarization_model is None:
            self._summarization_model = llm_factory.create_chat_model(
                temperature=0.3,
                streaming=False,
            )
        return self._summarization_model

    def count_tokens(self, messages: Sequence[Any]) -> int:
        total = 0
        for msg in messages:
            content = msg.content if hasattr(msg, "content") else str(msg)
            if isinstance(content, str):
                if self._tokenizer is not None:
                    total += len(self.tokenizer.encode(content))
                else:
                    chinese_chars = sum(1 for c in content if "\u4e00" <= c <= "\u9fff")
                    other_chars = len(content) - chinese_chars
                    total += int(chinese_chars * 1.5 + other_chars * 0.25)
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        text = block.get("text", "")
                        if self._tokenizer is not None:
                            total += len(self.tokenizer.encode(text))
                        else:
                            chinese_chars = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
                            other_chars = len(text) - chinese_chars
                            total += int(chinese_chars * 1.5 + other_chars * 0.25)
        return total

    def _should_compress(self, messages: Sequence[Any]) -> bool:
        token_count = self.count_tokens(messages)
        threshold_tokens = int(self.max_tokens * self.threshold)
        return token_count >= threshold_tokens

    async def _summarize_messages(self, messages: list[Any]) -> str:
        conversation_text_parts = []
        for msg in messages:
            if isinstance(msg, SystemMessage):
                continue
            role = "用户" if isinstance(msg, HumanMessage) else "助手"
            content = msg.content if hasattr(msg, "content") else str(msg)
            if isinstance(content, list):
                text_parts = [
                    block.get("text", "")
                    for block in content
                    if isinstance(block, dict) and block.get("type") == "text"
                ]
                content = " ".join(text_parts)
            if len(str(content)) > 2000:
                content = str(content)[:2000] + "...(已截断)"
            conversation_text_parts.append(f"[{role}]: {content}")

        conversation_text = "\n".join(conversation_text_parts)

        summary_response = await self.summarization_model.ainvoke([
            HumanMessage(content=f"{self.SUMMARIZE_PROMPT}\n\n对话内容：\n{conversation_text}")
        ])
        summary = (
            summary_response.content
            if hasattr(summary_response, "content")
            else str(summary_response)
        )
        logger.info(f"对话总结完成，摘要长度: {len(summary)} 字符")
        return summary

    async def compress(self, messages: Sequence[Any]) -> dict[str, Any] | None:
        if not messages:
            return None
        if not self._should_compress(messages):
            return None

        token_count = self.count_tokens(messages)
        threshold_tokens = int(self.max_tokens * self.threshold)
        logger.info(
            f"上下文压缩触发: token {token_count} >= 阈值 {threshold_tokens}"
        )

        try:
            system_messages = []
            non_system_messages = []
            for i, msg in enumerate(messages):
                if isinstance(msg, SystemMessage) and i < 2:
                    system_messages.append(msg)
                else:
                    non_system_messages.append(msg)

            if len(non_system_messages) <= self.keep_recent + 2:
                return None

            split_point = max(0, len(non_system_messages) - self.keep_recent)
            old_messages = non_system_messages[:split_point]
            recent_messages = non_system_messages[split_point:]

            if not old_messages:
                return None

            summary_text = await self._summarize_messages(old_messages)

            new_messages = list(system_messages)
            new_messages.append(HumanMessage(
                content=f"[历史对话摘要]\n以下是之前对话的要点总结：\n\n{summary_text}\n\n---\n以下是最近的对话："
            ))
            new_messages.extend(recent_messages)

            old_tokens = self.count_tokens(messages)
            new_tokens = self.count_tokens(new_messages)
            reduction = (1 - new_tokens / old_tokens) * 100 if old_tokens > 0 else 0
            logger.info(
                f"上下文压缩完成: {len(messages)} 条 -> {len(new_messages)} 条, "
                f"token: {old_tokens} -> {new_tokens} (减少 {reduction:.1f}%)"
            )

            return {
                "messages": [
                    RemoveMessage(id=REMOVE_ALL_MESSAGES),
                    *new_messages
                ]
            }

        except Exception as e:
            logger.error(f"上下文压缩失败，回退到简单截断: {e}")
            return self._fallback_trim(messages)

    def _fallback_trim(self, messages: Sequence[Any]) -> dict[str, Any]:
        first_msg = messages[0] if messages else None
        keep_count = min(self.keep_recent + 2, len(messages))
        if first_msg and isinstance(first_msg, SystemMessage):
            recent = messages[-(keep_count - 1):] if len(messages) > keep_count else messages[1:]
            new_messages = [first_msg] + list(recent)
        else:
            recent = messages[-keep_count:] if len(messages) > keep_count else messages
            new_messages = list(recent)
        logger.warning(f"降级截断: {len(messages)} 条 -> {len(new_messages)} 条")
        return {
            "messages": [
                RemoveMessage(id=REMOVE_ALL_MESSAGES),
                *new_messages
            ]
        }


class CompressionMiddleware(AgentMiddleware):
    """上下文压缩中间件（LangGraph AgentMiddleware 集成）"""

    def __init__(self):
        super().__init__()
        self.compressor = ConversationCompressor(
            max_tokens=config.context_max_tokens,
            threshold=config.context_compression_threshold,
            keep_recent=config.context_keep_recent,
        )

    async def abefore_model(
        self,
        state: dict,
        runtime: Any = None,
    ) -> dict[str, Any] | None:
        messages = state.get("messages", [])
        return await self.compressor.compress(messages)

    async def awrap_tool_call(self, request: Any, handler: Any) -> Any:
        return await handler(request)
