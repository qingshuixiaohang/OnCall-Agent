"""KnowledgePrefetcher - 知识预取深模块

从 RagAgentService 中提取的知识预取逻辑，职责单一：
1. 判断是否应该预取知识（_should_prefetch_knowledge）
2. 执行预取并规范化结果（_prepare_question）
3. 序列化知识文档为前端友好格式

提取后 RagAgentService 的 query/query_stream 只需委托给此模块。
"""

import re
from typing import Any

from langchain_core.documents import Document
from loguru import logger

from app.tools.knowledge_tool import retrieve_knowledge

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


class KnowledgePrefetcher:
    """知识预取器

    判断问题是否与故障排查相关，若是则预先检索知识库。
    将结果注入到问题文本中，让 LLM 优先使用知识库证据。
    """

    # ------------------------------------------------------------------
    # 接口
    # ------------------------------------------------------------------

    async def prefetch(
        self, question: str
    ) -> tuple[str, list[dict[str, Any]], bool, str]:
        """对运维问题预先检索一次知识库。

        Args:
            question: 用户原始问题

        Returns:
            (augmented_question, sources, prefetched, state):
            - augmented_question: 注入知识库证据后的问题（或原问题）
            - sources: 知识文档列表（前端用）
            - prefetched: 是否预取了知识
            - state: "skipped" | "empty" | "error" | "found"
        """
        if not self._should_prefetch(question):
            return question, [], False, "skipped"

        try:
            result = await retrieve_knowledge.ainvoke({"query": question})
            context, docs = self._normalize_result(result)
            sources = self._serialize_documents(docs)

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
    # 判断逻辑
    # ------------------------------------------------------------------

    @classmethod
    def _should_prefetch(cls, question: str) -> bool:
        """判断是否需要预取知识。"""
        normalized = question.strip().lower()
        if not normalized or _TRIVIAL_QUERY_PATTERN.fullmatch(normalized):
            return False
        return len(normalized) >= 6 and any(
            term in normalized for term in _KNOWLEDGE_TERMS
        )

    @staticmethod
    def _normalize_result(result: Any) -> tuple[str, list[Document]]:
        """规范化知识检索结果。"""
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
    def _serialize_documents(docs: list[Document]) -> list[dict[str, Any]]:
        """将知识文档序列化为前端友好的格式。"""
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
