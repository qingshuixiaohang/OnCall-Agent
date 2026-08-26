"""RAGPipeline - RAG 检索与入库的深模块对外接口"""

from pathlib import Path

from langchain_core.documents import Document
from loguru import logger

from app.config import config
from app.services.document_splitter_service import document_splitter_service
from app.services.keyword_index_service import keyword_index_service
from app.services.rerank_service import rerank_service
from app.services.vector_store_manager import vector_store_manager

_FILTER_FIELDS = ("service_name", "environment", "document_type")


class RAGPipeline:
    """RAG 检索与入库深模块。

    对外只暴露三个接口：
    - query(question, session_id, filters) → str：检索并返回格式化上下文
    - retrieve(question, filters) → tuple[str, list[Document]]：检索并返回 (上下文, 文档列表)
    - ingest(file_path) → result：文档入库
    """

    def __init__(self):
        self.rerank_enabled: bool = config.rag_rerank_enabled

    # ------------------------------------------------------------------
    # 对外接口
    # ------------------------------------------------------------------

    def query(
        self,
        question: str,
        session_id: str,
        filters: dict[str, str] | None = None,
    ) -> str:
        """检索知识库并返回格式化后的上下文文本。"""
        context, _ = self.retrieve(question, filters=filters)
        return context

    def retrieve(
        self,
        question: str,
        filters: dict[str, str] | None = None,
    ) -> tuple[str, list[Document]]:
        """检索知识库，返回 (格式化上下文, 文档列表)。供 Agent tool 使用。"""
        docs: list[Document] = []

        # Hybrid search：向量 + 关键词并行召回，RRF 合并
        dense_docs: list[Document] = []
        try:
            dense_docs = self._vector_search(question, filters=filters)
        except Exception as e:
            logger.warning(f"向量检索失败，降级到关键词检索: {e}")

        keyword_docs: list[Document] = []
        if config.rag_hybrid_enabled:
            keyword_docs = self._keyword_search(question, filters=filters)

        if dense_docs or keyword_docs:
            docs = self._merge_ranked_documents(dense_docs, keyword_docs)
        else:
            docs = []

        if not docs:
            return "没有找到相关信息。", []

        # 重排
        top_k = config.rag_top_k
        if len(docs) > top_k and self.rerank_enabled:
            docs = self._rerank(question, docs)

        # 阈值过滤
        docs = self._apply_rerank_threshold(docs)
        if not docs:
            return "没有找到足够相关的知识信息。", []

        return self._format_docs(docs), docs

    def ingest(
        self,
        file_path: str,
        metadata: dict[str, str] | None = None,
    ) -> dict:
        """文档入库：提取 → 分片 → 向量化 → 索引（向量 + 关键词）。"""
        import time

        start = time.perf_counter()
        path = Path(file_path).resolve()
        if not path.exists() or not path.is_file():
            raise ValueError(f"文件不存在: {file_path}")

        normalized_path = path.as_posix()

        # 1. 删除该文件的旧索引数据
        deleted_vector = vector_store_manager.delete_by_source(normalized_path)
        deleted_keyword = keyword_index_service.delete_by_source(normalized_path)
        total_deleted = deleted_vector + deleted_keyword

        # 2. 提取文本并分片
        content = document_splitter_service.extract_text(file_path)
        documents = document_splitter_service.split_document(
            content, normalized_path, extra_metadata=metadata
        )

        if not documents:
            return {
                "file_path": file_path,
                "chunk_count": 0,
                "document_ids": [],
                "deleted_count": total_deleted,
                "duration_ms": round((time.perf_counter() - start) * 1000, 2),
            }

        # 3. 向量存储（自动调用 embedding） + 关键词索引
        document_ids = vector_store_manager.add_documents(documents)
        keyword_index_service.upsert_documents(document_ids, documents)

        return {
            "file_path": file_path,
            "chunk_count": len(documents),
            "document_ids": document_ids,
            "deleted_count": total_deleted,
            "duration_ms": round((time.perf_counter() - start) * 1000, 2),
        }

    # ------------------------------------------------------------------
    # 内部检索步骤
    # ------------------------------------------------------------------

    def _vector_search(
        self, question: str, filters: dict[str, str] | None = None
    ) -> list[Document]:
        """向量检索：返回候选文档列表。"""
        expr = self._build_filter_expr(filters)
        results = vector_store_manager.similarity_search(
            query=question,
            k=config.rag_retrieval_k,
            expr=expr,
        )
        return [
            Document(page_content=r.page_content, metadata=r.metadata or {})
            for r in results
        ]

    def _keyword_search(
        self, question: str, filters: dict[str, str] | None = None
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

    def _rerank(self, question: str, docs: list[Document]) -> list[Document]:
        """语义重排：返回精排后的文档列表。"""
        return rerank_service.rerank(question, docs)

    @staticmethod
    def _build_filter_expr(filters: dict[str, str] | None) -> str | None:
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

    @staticmethod
    def _document_key(document: Document) -> str:
        metadata = document.metadata
        chunk_id = metadata.get("_chunk_id")
        if chunk_id:
            return str(chunk_id)
        return f"{metadata.get('_source', '')}:{metadata.get('chunk_index', '')}:{document.page_content}"

    @staticmethod
    def _merge_ranked_documents(
        dense_docs: list[Document],
        keyword_docs: list[Document],
    ) -> list[Document]:
        """使用 RRF 合并两路排名。"""
        rrf_constant = 60
        scores: dict[str, float] = {}
        documents: dict[str, Document] = {}

        for rank, document in enumerate(dense_docs, start=1):
            key = RAGPipeline._document_key(document)
            scores[key] = scores.get(key, 0.0) + 1 / (rrf_constant + rank)
            documents[key] = document

        for rank, document in enumerate(keyword_docs, start=1):
            key = RAGPipeline._document_key(document)
            scores[key] = scores.get(key, 0.0) + 1 / (rrf_constant + rank)
            documents.setdefault(key, document)

        ranked_keys = sorted(scores, key=scores.get, reverse=True)
        return [documents[key] for key in ranked_keys]

    @staticmethod
    def _apply_rerank_threshold(docs: list[Document]) -> list[Document]:
        """只对已有重排分数的结果应用阈值。"""
        scored = [doc for doc in docs if doc.metadata.get("rerank_score") is not None]
        if not scored:
            return docs
        return [
            doc
            for doc in docs
            if float(doc.metadata.get("rerank_score", 0.0))
            >= config.rag_min_rerank_score
        ]
