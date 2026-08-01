"""文档重排服务 — 支持 SiliconFlow / DashScope Rerank API

使用 httpx 直接发送 HTTP 请求，绕开 OpenAI SDK 封装的不确定性。
"""

from typing import List

from langchain_core.documents import Document
from loguru import logger

from app.config import config


class RerankService:
    """文档重排服务"""

    def __init__(self) -> None:
        self.backend: str = getattr(config, "rerank_backend", "siliconflow")
        self.model: str = config.rerank_model
        self.retrieval_k: int = config.rag_retrieval_k
        self.top_k: int = config.rag_top_k

        if self.backend == "siliconflow":
            self.api_key = config.siliconflow_api_key
            self.api_base = config.siliconflow_api_base.rstrip("/")
        else:
            self.api_key = config.dashscope_api_key
            self.api_base = "https://dashscope.aliyuncs.com"

        if not self.api_key:
            logger.warning(
                f"RerankService: 后端={self.backend}，API Key 未配置，重排功能将不可用"
            )

        logger.info(
            f"RerankService: backend={self.backend}, model={self.model}, "
            f"retrieval_k={self.retrieval_k}, top_k={self.top_k}"
        )

    def rerank(self, query: str, documents: List[Document]) -> List[Document]:
        if not documents:
            return documents

        if not self.api_key:
            raise ValueError("RerankService: API Key 未配置")

        if len(documents) <= self.top_k:
            return documents

        logger.info(
            f"RerankService: query=\'{query[:80]}...\', "
            f"候选={len(documents)}, top_k={self.top_k}, backend={self.backend}"
        )

        doc_texts = [doc.page_content for doc in documents]

        try:
            if self.backend == "siliconflow":
                results = self._call_siliconflow(query, doc_texts)
            else:
                results = self._call_dashscope(query, doc_texts)

            if not results:
                logger.warning("RerankService: API 返回空结果，返回原始 top_k")
                return documents[: self.top_k]

            sorted_results = sorted(
                results, key=lambda r: r.get("relevance_score", 0.0), reverse=True
            )

            reranked_docs: List[Document] = []
            for item in sorted_results[: self.top_k]:
                idx = item.get("index", 0)
                score = item.get("relevance_score", 0.0)
                if 0 <= idx < len(documents):
                    doc = documents[idx]
                    doc.metadata["rerank_score"] = score
                    doc.metadata["rerank_model"] = self.model
                    reranked_docs.append(doc)

            scores = [d.metadata.get("rerank_score", 0) for d in reranked_docs]
            logger.info(
                f"RerankService: 重排完成 {len(documents)} -> {len(reranked_docs)}, "
                f"分数范围 [{min(scores):.4f}, {max(scores):.4f}]"
            )
            return reranked_docs

        except Exception as e:
            logger.error(f"RerankService: 重排异常: {e}", exc_info=True)
            raise RuntimeError(f"文档重排失败: {e}") from e

    def _call_siliconflow(self, query: str, documents: List[str]) -> List[dict]:
        """SiliconFlow Rerank API（OpenAI 兼容 /rerank）"""
        import httpx

        url = f"{self.api_base}/rerank"
        logger.debug(f"RerankService: POST {url}, model={self.model}")

        with httpx.Client(timeout=30.0) as client:
            resp = client.post(
                url,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "query": query,
                    "documents": documents,
                    "top_n": min(self.top_k, len(documents)),
                },
            )
            resp.raise_for_status()
            data = resp.json()

        results = data.get("results", [])
        logger.debug(f"SiliconFlow rerank 返回 {len(results)} 条")
        return [
            {"index": r.get("index", i), "relevance_score": r.get("relevance_score", 0.0)}
            for i, r in enumerate(results)
        ]

    def _call_dashscope(self, query: str, documents: List[str]) -> List[dict]:
        """DashScope Rerank API（阿里云百炼专用格式）"""
        import httpx

        url = (
            "https://dashscope.aliyuncs.com/api/v1/services/rerank/"
            "text-rerank/text-rerank"
        )
        logger.debug(f"RerankService: POST {url}, model={self.model}")

        with httpx.Client(timeout=30.0) as client:
            resp = client.post(
                url,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "input": {"query": query, "documents": documents},
                    "parameters": {
                        "top_n": min(self.top_k, len(documents)),
                        "return_documents": False,
                    },
                },
            )
            resp.raise_for_status()
            data = resp.json()

        output = data.get("output", {})
        results = output.get("results", [])
        logger.debug(f"DashScope rerank 返回 {len(results)} 条")
        return [
            {"index": r.get("index", 0), "relevance_score": r.get("relevance_score", 0.0)}
            for r in results
        ]


# 全局单例
rerank_service = RerankService()
