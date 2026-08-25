"""向量检索服务模块 - 薄包装委托给 RAGPipeline"""

from typing import Any

from loguru import logger

from app.services.rag_pipeline import RAGPipeline


class SearchResult:
    """搜索结果类"""

    def __init__(
        self,
        id: str,
        content: str,
        score: float,
        metadata: dict[str, Any],
    ):
        self.id = id
        self.content = content
        self.score = score
        self.metadata = metadata

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "id": self.id,
            "content": self.content,
            "score": self.score,
            "metadata": self.metadata,
        }


class VectorSearchService:
    """向量检索服务 - 薄包装，委托给 RAGPipeline"""

    def __init__(self):
        """初始化向量检索服务"""
        logger.info("向量检索服务（薄包装）初始化完成")

    def search_similar_documents(self, query: str, top_k: int = 3) -> list[SearchResult]:
        """检索相似文档，委托给 RAGPipeline 的向量检索能力"""
        pipeline = RAGPipeline()
        _, docs = pipeline.retrieve(query)
        return [
            SearchResult(
                id=doc.metadata.get("_chunk_id", ""),
                content=doc.page_content,
                score=float(doc.metadata.get("rerank_score", 0.0)),
                metadata=doc.metadata or {},
            )
            for doc in docs[:top_k]
        ]
