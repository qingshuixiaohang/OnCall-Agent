"""RAGPipeline - RAG 检索与入库的深模块对外接口"""

from typing import Dict, List, Optional

from langchain_core.documents import Document

from app.config import config
from app.services.keyword_index_service import keyword_index_service
from app.services.rerank_service import rerank_service
from app.services.vector_store_manager import vector_store_manager


_FILTER_FIELDS = ("service_name", "environment", "document_type")


class RAGPipeline:
    """RAG 检索与入库深模块。

    对外只暴露两个接口：
    - query(question, session_id, filters) → str：检索并返回格式化上下文
    - ingest(file_path) → result：文档入库
    """

    def __init__(self):
        self.rerank_enabled: bool = True

    # ------------------------------------------------------------------
    # 对外接口
    # ------------------------------------------------------------------

    async def query(
        self,
        question: str,
        session_id: str,
        filters: Optional[Dict[str, str]] = None,
    ) -> str:
        """检索知识库并返回格式化后的上下文文本。"""
        docs: list[Document] = []

        # 优先向量检索，失败则降级到关键词检索
        try:
            docs = await self._vector_search(question, filters=filters)
        except RuntimeError:
            docs = await self._keyword_search(question, filters=filters)

        # 重排
        if docs and self.rerank_enabled:
            docs = await self._rerank(question, docs)

        return self._format_docs(docs)

    async def ingest(self, file_path: str) -> dict:
        """文档入库：分片 → 向量化 → 索引。"""
        raise NotImplementedError("ingest 路径将在 02 任务中实现")

    # ------------------------------------------------------------------
    # 内部检索步骤（直接访问模块级服务，便于测试时 patch）
    # ------------------------------------------------------------------

    async def _vector_search(
        self, question: str, filters: Optional[Dict[str, str]] = None
    ) -> list[Document]:
        """向量检索：返回候选文档列表。"""
        expr = self._build_filter_expr(filters)
        results = vector_store_manager.similarity_search(
            query=question,
            k=config.rag_retrieval_k,
            expr=expr,
        )
        return [
            Document(page_content=r.content, metadata=r.metadata or {})
            for r in results
        ]

    async def _keyword_search(
        self, question: str, filters: Optional[Dict[str, str]] = None
    ) -> list[Document]:
        """关键词检索：返回候选文档列表。"""
        clean_filters = {
            key: value.strip()
            for key, value in (filters or {}).items()
            if value and value.strip()
        }
        return keyword_index_service.search(
            query=question,
            k=config.rag_keyword_k,
            filters=clean_filters,
        )

    async def _rerank(self, question: str, docs: list[Document]) -> list[Document]:
        """语义重排：返回精排后的文档列表。"""
        return rerank_service.rerank(question, docs)

    @staticmethod
    def _build_filter_expr(filters: Optional[Dict[str, str]]) -> Optional[str]:
        """构造 Milvus JSON 过滤表达式。"""
        if not filters:
            return None
        expressions = []
        for key, value in filters.items():
            if key not in _FILTER_FIELDS:
                continue
            escaped = value.replace("\\", "\\\\").replace('"', '\\"')
            expressions.append(f'metadata["{key}"] == "{escaped}"')
        return " and ".join(expressions) if expressions else None

    @staticmethod
    def _format_docs(docs: list[Document]) -> str:
        """将文档列表格式化为上下文文本。"""
        if not docs:
            return "没有找到相关信息。"

        parts = []
        for i, doc in enumerate(docs, 1):
            metadata = doc.metadata or {}
            source = metadata.get("_file_name", "未知来源")
            parts.append(
                f"【参考资料 {i}】\n来源: {source}\n内容:\n{doc.page_content}\n"
            )
        return "\n".join(parts)
