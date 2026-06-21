"""文档重排服务 — 调用阿里云百炼 DashScope Rerank API

在向量检索之后、格式化之前，对召回的文档进行语义级精排。
流程：粗排（向量相似度召回 k=rag_retrieval_k）→ 精排（重排模型 top_n=rag_top_k）

DashScope Rerank API 文档:
https://help.aliyun.com/zh/model-studio/developer-reference/rerank-model-api

注意：重排 API 不走 OpenAI 兼容模式，需直接调用 REST 接口。
"""

from typing import List

import httpx
from langchain_core.documents import Document
from loguru import logger

from app.config import config


# 阿里云百炼 DashScope Rerank API 端点
DASHSCOPE_RERANK_URL = (
    "https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank"
)


class RerankService:
    """文档重排服务

    职责：
    1. 接收向量检索返回的候选文档列表
    2. 调用阿里云百炼重排模型进行语义级精排
    3. 返回按相关性从高到低排列的 top_k 文档

    失败策略：不降级，直接抛出异常。
    """

    def __init__(self) -> None:
        """初始化重排服务"""
        self.api_key: str = config.dashscope_api_key
        self.model: str = config.rerank_model  # 默认 "gte-rerank"
        self.retrieval_k: int = config.rag_retrieval_k  # 粗排召回数（默认 9）
        self.top_k: int = config.rag_top_k  # 精排保留数（默认 3）
        self._client: httpx.Client | None = None

        if not self.api_key:
            logger.warning("RerankService: DASHSCOPE_API_KEY 未配置，重排功能将不可用")

        logger.info(
            f"RerankService 初始化完成: model={self.model}, "
            f"retrieval_k={self.retrieval_k}, top_k={self.top_k}"
        )

    @property
    def client(self) -> httpx.Client:
        """延迟创建 httpx 客户端（带连接池复用）"""
        if self._client is None:
            self._client = httpx.Client(
                timeout=httpx.Timeout(30.0),
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
            )
        return self._client

    def rerank(self, query: str, documents: List[Document]) -> List[Document]:
        """对文档列表进行语义重排

        工作流程：
        1. 从 Document 对象中提取 page_content 作为待重排文本
        2. 构建请求并调用 DashScope Rerank API
        3. 解析响应中的 relevance_score
        4. 按分数降序排列，返回前 top_k 个文档

        Args:
            query: 用户原始查询文本
            documents: 向量检索返回的候选文档列表（LangChain Document 对象）

        Returns:
            List[Document]: 重排后的 top_k 文档列表（保持原始 Document 的元数据不变）

        Raises:
            ValueError: API Key 未配置或模型名称无效
            httpx.HTTPStatusError: API 返回非 200 状态码
            RuntimeError: 重排过程出现其他异常
        """
        if not documents:
            logger.warning("RerankService.rerank: 文档列表为空，跳过重排")
            return documents

        if not self.api_key:
            raise ValueError(
                "DASHSCOPE_API_KEY 未配置。请在 .env 文件中设置 DASHSCOPE_API_KEY。\n"
                "获取方式: https://bailian.console.aliyun.com/#/api-key"
            )

        if len(documents) <= self.top_k:
            logger.info(
                f"RerankService.rerank: 文档数量({len(documents)}) <= top_k({self.top_k})，"
                f"跳过重排直接返回"
            )
            return documents

        logger.info(
            f"RerankService.rerank: query='{query[:80]}...', "
            f"候选文档数={len(documents)}, top_k={self.top_k}"
        )

        try:
            # 1. 提取文档文本内容
            doc_texts: List[str] = [doc.page_content for doc in documents]

            # 2. 构建 API 请求体
            request_body = {
                "model": self.model,
                "input": {
                    "query": query,
                    "documents": doc_texts,
                },
                "parameters": {
                    "top_n": min(self.top_k, len(documents)),
                    "return_documents": False,  # 不需要返回文档文本，只需 index + score
                },
            }

            # 3. 调用 DashScope Rerank API
            logger.debug(f"RerankService: 请求 DashScope Rerank API, model={self.model}")
            response = self.client.post(DASHSCOPE_RERANK_URL, json=request_body)
            response.raise_for_status()
            result = response.json()

            # 4. 解析响应
            output = result.get("output", {})
            results = output.get("results", [])

            if not results:
                logger.warning("RerankService: API 返回空结果，返回原始文档列表的前 top_k 个")
                return documents[: self.top_k]

            # 5. 按 relevance_score 降序排列（API 已经排好序，但为确保兼容性再排一次）
            sorted_results = sorted(
                results,
                key=lambda r: r.get("relevance_score", 0.0),
                reverse=True,
            )

            # 6. 构建重排后的文档列表
            reranked_docs: List[Document] = []
            for item in sorted_results[: self.top_k]:
                original_index: int = item.get("index", 0)
                relevance_score: float = item.get("relevance_score", 0.0)

                if 0 <= original_index < len(documents):
                    doc = documents[original_index]
                    # 在元数据中添加重排分数，便于调试和追踪
                    doc.metadata["rerank_score"] = relevance_score
                    doc.metadata["rerank_model"] = self.model
                    reranked_docs.append(doc)

            # 记录日志
            scores = [d.metadata.get("rerank_score", 0) for d in reranked_docs]
            logger.info(
                f"RerankService: 重排完成, "
                f"输入 {len(documents)} 篇 → 输出 {len(reranked_docs)} 篇, "
                f"分数范围: [{min(scores):.4f}, {max(scores):.4f}]"
            )

            # 记录使用的 token 数（如有）
            usage = result.get("usage", {})
            if usage:
                total_tokens = usage.get("total_tokens", 0)
                logger.debug(f"RerankService: API 消耗 {total_tokens} tokens")

            return reranked_docs

        except httpx.HTTPStatusError as e:
            logger.error(
                f"RerankService: DashScope API 返回错误状态码 {e.response.status_code}: "
                f"{e.response.text[:500]}"
            )
            raise RuntimeError(
                f"重排 API 调用失败 (HTTP {e.response.status_code}): {e.response.text[:300]}"
            ) from e

        except httpx.RequestError as e:
            logger.error(f"RerankService: 网络请求失败: {e}")
            raise RuntimeError(f"重排 API 网络请求失败: {e}") from e

        except Exception as e:
            logger.error(f"RerankService: 重排过程异常: {e}", exc_info=True)
            raise RuntimeError(f"文档重排失败: {e}") from e

    def close(self) -> None:
        """关闭 HTTP 客户端连接池"""
        if self._client is not None:
            self._client.close()
            self._client = None
            logger.debug("RerankService: HTTP 客户端已关闭")


# 全局单例
rerank_service = RerankService()
