"""配置管理模块

使用 Pydantic Settings 实现类型安全的配置管理
"""

from pathlib import Path
from typing import Any

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# 项目根目录（config.py 在 app/ 下，所以父目录就是项目根目录）
_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def resolve_project_path(value: str | Path) -> Path:
    """将相对路径固定解析到项目根目录，避免受启动目录影响。"""
    path = Path(value)
    return path if path.is_absolute() else _PROJECT_ROOT / path


class Settings(BaseSettings):
    """应用配置"""

    model_config = SettingsConfigDict(
        env_file=str(_PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        env_ignore_empty=True,
        extra="ignore",
    )

    # 应用配置
    app_name: str = "SuperBizAgent"
    app_version: str = "1.0.0"
    debug: bool = False
    host: str = "0.0.0.0"
    port: int = 9900
    cors_origins: str = "http://localhost:5173,http://localhost:9900"

    # DashScope 配置（API Key 和地址；模型统一由 rag_model 配置）
    dashscope_api_key: str = ""  # 默认空字符串，实际使用需从环境变量加载
    dashscope_api_base: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"

    # 生产 Agent 运行时模型配置。LLM_* 优先，兼容旧 DASHSCOPE_*/RAG_MODEL 配置。
    llm_provider: str = Field(
        default="openai_compatible",
        validation_alias=AliasChoices("LLM_PROVIDER"),
    )
    llm_model: str = Field(
        default="qwen3.7-plus",
        validation_alias=AliasChoices("LLM_MODEL", "RAG_MODEL", "DASHSCOPE_MODEL"),
    )
    llm_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("LLM_API_KEY", "DASHSCOPE_API_KEY"),
    )
    llm_api_base: str = Field(
        default="https://dashscope.aliyuncs.com/compatible-mode/v1",
        validation_alias=AliasChoices("LLM_API_BASE", "DASHSCOPE_API_BASE"),
    )
    llm_enable_thinking: bool | None = Field(
        default=None,
        validation_alias=AliasChoices("LLM_ENABLE_THINKING"),
    )
    llm_timeout: float = Field(default=60.0, validation_alias=AliasChoices("LLM_TIMEOUT"))
    llm_max_retries: int = Field(default=2, validation_alias=AliasChoices("LLM_MAX_RETRIES"))

    # Ragas 评审模型配置，与答案生成模型独立
    rag_eval_api_key: str = ""
    rag_eval_api_base: str = "https://api.stepfun.com/step_plan/v1"
    rag_eval_model: str = "step-3.7-flash"

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
    rag_model: str = Field(
        default="qwen3.7-plus",
        validation_alias=AliasChoices("RAG_MODEL", "DASHSCOPE_MODEL"),
        description="所有 DashScope 对话调用共用的模型名称",
    )

    # 重排模型配置
    rerank_backend: str = "siliconflow"  # 重排后端：siliconflow（免费）或 dashscope（阿里云百炼）
    rerank_model: str = "BAAI/bge-reranker-v2-m3"  # SiliconFlow 免费重排模型
    rag_retrieval_k: int = 9  # 粗排召回数量（重排前的候选文档数，建议为 rag_top_k 的 2-3 倍）
    rag_keyword_k: int = 9  # 关键词索引召回数量
    rag_hybrid_enabled: bool = True  # 是否合并向量召回和关键词召回
    rag_rerank_enabled: bool = True  # 是否启用语义重排（运行时可关闭）
    rag_min_rerank_score: float = 0.25  # 重排最低相关性分数
    rag_keyword_index_path: str = "./volumes/rag_keywords.db"

    # 文档分块配置
    chunk_max_size: int = 800
    chunk_overlap: int = 100

    # MCP 服务配置
    mcp_cls_transport: str = "sse"
    mcp_cls_url: str = "http://localhost:3000/sse"
    mcp_monitor_transport: str = "streamable-http"
    mcp_monitor_url: str = "http://localhost:8004/mcp"

    # 上下文压缩配置（对话历史自动总结）
    context_max_tokens: int = 32768  # 模型上下文窗口大小（qwen-max = 32K）
    context_compression_threshold: float = 0.7  # 压缩触发阈值（70% 时触发）
    context_keep_recent: int = 4  # 压缩后保留的最近消息条数

    @property
    def dashscope_model(self) -> str:
        """兼容旧调用方；模型实际只由 rag_model 配置。"""
        return self.rag_model

    # 记忆存储配置
    storage_backend: str = "sqlite"
    storage_postgres_url: str = ""
    storage_sqlite_path: str = "./volumes/langgraph.db"
    report_db_path: str = "./volumes/reports.db"  # 诊断报告独立 SQLite
    storage_max_history: int = 100
    storage_session_ttl: int = 86400  # 24小时
    # LangSmith 配置（可观测性）
    langsmith_tracing: bool = False
    langsmith_api_key: str = ""
    langsmith_project: str = "OnCall-Agent"
    langsmith_endpoint: str = "https://api.smith.langchain.com"

    # Langfuse 配置（可观测性，默认禁用）
    langfuse_enabled: bool = False
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_base_url: str = "https://cloud.langfuse.com"
    langfuse_environment: str = "production"
    langfuse_release: str = ""
    langfuse_sample_rate: float = 1.0
    langfuse_capture_content: bool = False

    @property
    def mcp_servers(self) -> dict[str, dict[str, Any]]:
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


class Mem0Config(BaseSettings):
    mem0_backend: str = "sqlite"  # sqlite | postgres | qdrant
    mem0_sqlite_path: str = "./volumes/mem0.db"
    mem0_user_id: str = ""
    mem0_save_timeout: float = 60.0

    model_config = {"env_prefix": ""}


mem0_config = Mem0Config()
# 全局配置实例
config = Settings()
