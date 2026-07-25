"""知识库检索 Specialist

职责：
1. 基于用户问题从知识库检索相关运维经验和最佳实践
2. 整理检索结果，供后续报告生成使用

设计决策：
1. 直接复用现有 retrieve_knowledge 工具，不重新实现检索逻辑
2. 返回知识库上下文原文，不做额外压缩，保留完整信息给下游
3. 检索失败时返回降级结果，而不是抛出异常
"""

from typing import Any, Dict, List, Optional
from langchain_core.documents import Document
from loguru import logger

from app.tools import retrieve_knowledge
from app.agent.multi_agent.state import MultiAgentState
from app.agent.multi_agent.base_specialist import BaseSpecialist


class KnowledgeRetriever(BaseSpecialist):
    """知识库检索 Specialist"""

    def __init__(self) -> None:
        super().__init__(
            name="knowledge_retriever",
            description="从知识库检索相关运维经验和最佳实践",
        )

    async def _execute(self, state: MultiAgentState) -> Dict[str, Any]:
        user_input = state.get("user_input", "")

        try:
            result = await retrieve_knowledge.ainvoke({"query": user_input})
            context, docs = self._normalize_result(result)

            doc_info = [
                {
                    "index": i,
                    "source": doc.metadata.get("_file_name", "未知来源"),
                    "content_preview": (
                        doc.page_content[:200] + "..."
                        if len(doc.page_content) > 200
                        else doc.page_content
                    ),
                }
                for i, doc in enumerate(docs, 1)
            ]

            return {
                "knowledge_context": context,
                "knowledge_retrieval": {
                    "documents": doc_info,
                    "doc_count": len(docs),
                    "confidence": 0.9 if docs else 0.3,
                },
                "completed_tasks": [f"完成 knowledge_retriever 分析"],
            }

        except Exception as e:
            logger.error(f"知识库检索失败: {e}")
            return {
                "knowledge_context": f"知识库检索失败: {str(e)}",
                "knowledge_retrieval": {
                    "documents": [],
                    "doc_count": 0,
                    "confidence": 0.0,
                },
                "completed_tasks": [f"完成 knowledge_retriever 分析"],
            }

    def _normalize_result(self, result: Any):
        """
        兼容工具返回格式
        
        预期返回值格式为 (context: str, docs: List[Document])。
        若返回格式发生变化，这里集中做兼容处理，避免分散在各个调用点。
        """
        if isinstance(result, tuple) and len(result) == 2:
            context, docs = result
            if isinstance(docs, list):
                return context or "", docs
            return context or "", [docs]

        if isinstance(result, str):
            return result, []

        if isinstance(result, list):
            return "", result

        return "", []