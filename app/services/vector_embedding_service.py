"""向量嵌入服务模块 - 基于 LangChain Embeddings 标准接口"""


from langchain_core.embeddings import Embeddings
from loguru import logger
from openai import OpenAI

from app.config import config


class SiliconFlowEmbeddings(Embeddings):
    """SiliconFlow Embedding 服务 (OpenAI 兼容模式)

    实现 LangChain 标准 Embeddings 接口:
    - embed_documents(texts: List[str]) → List[List[float]]: 批量嵌入文档
    - embed_query(text: str) → List[float]: 嵌入单个查询
    """

    def __init__(
        self,
        api_key: str,
        model: str = "BAAI/bge-m3",
        base_url: str = "https://api.siliconflow.cn/v1",
    ):
        """
        初始化 SiliconFlow Embeddings

        Args:
            api_key: SiliconFlow API Key
            model: 嵌入模型名称
            base_url: API 地址
        """
        if not api_key:
            raise ValueError("请设置环境变量 SILICONFLOW_API_KEY")

        self.client = OpenAI(
            api_key=api_key,
            base_url=base_url
        )
        self.model = model

        # 打印初始化信息
        masked_key = self._mask_api_key(api_key)
        logger.info(
            f"SiliconFlow Embeddings 初始化完成 - "
            f"模型: {model}, API地址: {base_url}, API Key: {masked_key}"
        )

    @staticmethod
    def _mask_api_key(api_key: str) -> str:
        """掩码 API Key 用于日志"""
        if len(api_key) > 8:
            return f"{api_key[:8]}...{api_key[-4:]}"
        return "***"

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """
        批量嵌入文档列表 (LangChain 标准接口)

        Args:
            texts: 文本列表

        Returns:
            List[List[float]]: 嵌入向量列表
        """
        if not texts:
            return []

        try:
            logger.info(f"批量嵌入 {len(texts)} 个文档")

            # 批量调用 API（BAAI/bge-m3 固定 1024 维，不传 dimensions 参数）
            response = self.client.embeddings.create(
                model=self.model,
                input=texts,
                encoding_format="float"
            )

            embeddings = [item.embedding for item in response.data]
            logger.debug(f"批量嵌入完成, 维度: {len(embeddings[0])}")

            return embeddings

        except Exception as e:
            logger.error(f"批量嵌入失败: {e}")
            raise RuntimeError(f"批量嵌入失败: {e}") from e

    def embed_query(self, text: str) -> list[float]:
        """
        嵌入单个查询文本 (LangChain 标准接口)

        Args:
            text: 查询文本

        Returns:
            List[float]: 嵌入向量
        """
        if not text or not text.strip():
            raise ValueError("查询文本不能为空")

        try:
            logger.debug(f"嵌入查询, 长度: {len(text)} 字符")

            response = self.client.embeddings.create(
                model=self.model,
                input=text,
                encoding_format="float"
            )

            embedding = response.data[0].embedding
            logger.debug(f"查询嵌入完成, 维度: {len(embedding)}")

            return embedding

        except Exception as e:
            logger.error(f"查询嵌入失败: {e}")
            raise RuntimeError(f"查询嵌入失败: {e}") from e


# 全局单例
vector_embedding_service = SiliconFlowEmbeddings(
    api_key=config.siliconflow_api_key,
    model=config.siliconflow_embedding_model,
    base_url=config.siliconflow_api_base,
)
