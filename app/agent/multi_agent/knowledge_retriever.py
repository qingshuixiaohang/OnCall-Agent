"""知识库检索 Specialist

职责：
1. 基于用户问题从知识库检索相关运维经验和最佳实践
2. 整理检索结果，供后续报告生成使用

设计决策：
1. 直接复用现有 retrieve_knowledge 工具，不重新实现检索逻辑
2. 不需要 LLM（纯检索），因此不继承 BaseSpecialist 的 LLM 创建逻辑
   但为统一接口仍继承 BaseSpecialist，只是永远不会访问 self.llm
3. 检索失败时返回降级结果，而不是抛出异常
4. 移除旧版硬编码的假 confidence 值（0.9/0.3），改为基于实际文档数量的简单判断
"""

from typing import Any

from langchain_core.documents import Document
from loguru import logger

from app.agent.multi_agent.base_specialist import BaseSpecialist
from app.agent.multi_agent.state import MultiAgentState
from app.tools import retrieve_knowledge


class KnowledgeRetriever(BaseSpecialist):
    """知识库检索 Specialist（纯检索，不使用 LLM）"""

    def __init__(self) -> None:
        super().__init__(
            name="knowledge_retriever",
            description="从知识库检索相关运维经验和最佳实践",
        )

    async def _execute(self, state: MultiAgentState) -> dict[str, Any]:
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

            # confidence 基于实际检索到的文档数量，而非硬编码
            confidence = min(len(docs) / 5.0, 1.0) if docs else 0.0

            return {
                "knowledge_context": context,
                "knowledge_retrieval": {
                    "documents": doc_info,
                    "doc_count": len(docs),
                    "confidence": confidence,
                },
                "completed_tasks": [f"完成 {self.name} 检索"],
            }

        except Exception as e:
            logger.error(f"知识库检索失败: {e}")
            return {
                "knowledge_context": "",
                "knowledge_retrieval": {
                    "documents": [],
                    "doc_count": 0,
                    "confidence": 0.0,
                },
                "completed_tasks": [f"完成 {self.name} 检索（降级）"],
            }

    def _normalize_result(self, result: Any) -> tuple[str, list[Document]]:
        """兼容工具返回格式

        retrieve_knowledge 使用 response_format="content_and_artifact"，
        ainvoke() 可能只返回 content（字符串），也可能返回元组。
        这里集中做兼容处理。
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
