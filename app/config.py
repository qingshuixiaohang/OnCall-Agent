"""配置管理模块

使用 Pydantic Settings 实现类型安全的配置管理
"""

from pathlib import Path
from typing import Dict, Any
from pydantic_settings import BaseSettings, SettingsConfigDict


# 项目根目录（config.py 在 app/ 下，所以父目录就是项目根目录）
_PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """应用配置"""

    model_config = SettingsConfigDict(
        env_file=str(_PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # 应用配置
    app_name: str = "SuperBizAgent"
    app_version: str = "1.0.0"
    debug: bool = False
    host: str = "0.0.0.0"
    port: int = 9900

    # DashScope 配置（对话模型）
    dashscope_api_key: str = ""  # 默认空字符串，实际使用需从环境变量加载
    dashscope_model: str = "qwen3.7-max"

    # SiliconFlow 配置（嵌入向量模型）
    siliconflow_api_key: str = ""
    siliconflow_api_base: str = "https://api.siliconflow.cn/v1"
    siliconflow_embedding_model: str = "BAAI/bge-m3"

    # Milvus 配置
    milvus_host: str = "localhost"
    milvus_port: int = 19530
    milvus_timeout: int = 10000  # 毫秒

    # RAG 配置
    rag_top_k: int = 3
    rag_model: str = "qwen3.7-max"  # 使用快速响应模型，不带扩展思考

    # 重排模型配置（阿里云百炼 DashScope Rerank API）
    rerank_model: str = "gte-rerank"  # 重排模型名称
    rag_retrieval_k: int = 9  # 粗排召回数量（重排前的候选文档数，建议为 rag_top_k 的 2-3 倍）

    # 文档分块配置
    chunk_max_size: int = 800
    chunk_overlap: int = 100

    # MCP 服务配置
    mcp_cls_transport: str = "streamable-http"
    mcp_cls_url: str = "http://localhost:8003/mcp"
    mcp_monitor_transport: str = "streamable-http"
    mcp_monitor_url: str = "http://localhost:8004/mcp"

    # 上下文压缩配置（对话历史自动总结）
    context_max_tokens: int = 32768  # 模型上下文窗口大小（qwen-max = 32K）
    context_compression_threshold: float = 0.7  # 压缩触发阈值（70% 时触发）
    context_keep_recent: int = 4  # 压缩后保留的最近消息条数

    # 记忆存储配置
    storage_backend: str = "sqlite"
    storage_postgres_url: str = ""
    storage_sqlite_path: str = "./volumes/langgraph.db"
    storage_max_history: int = 100
    storage_session_ttl: int = 86400  # 24小时
    # LangSmith 配置（可观测性）
    langsmith_tracing: bool = False
    langsmith_api_key: str = ""
    langsmith_project: str = "OnCall-Agent"
    langsmith_endpoint: str = "https://api.smith.langchain.com"

    @property
    def mcp_servers(self) -> Dict[str, Dict[str, Any]]:
        """获取完整的 MCP 服务器配置"""
        return {
            "cls": {
                "transport": self.mcp_cls_transport,
                "url": self.mcp_cls_url,
            },
            "monitor": {
                "transport": self.mcp_monitor_transport,
                "url": self.mcp_monitor_url,
            }
        }


# 全局配置实例
config = Settings()
