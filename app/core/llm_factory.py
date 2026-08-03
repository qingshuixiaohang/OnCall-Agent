"""生产 Agent 的统一 LLM 创建入口。"""

from langchain_openai import ChatOpenAI

from app.config import config


class LLMFactory:
    """通过 OpenAI 兼容协议创建生产 Agent 使用的聊天模型。"""

    SUPPORTED_PROVIDERS = {"openai_compatible", "openai", "dashscope", "stepfun"}

    @classmethod
    def create_chat_model(
        cls,
        model: str | None = None,
        temperature: float = 0.7,
        streaming: bool = True,
        base_url: str | None = None,
        api_key: str | None = None,
        structured: bool = False,
    ) -> ChatOpenAI:
        resolved_model = model or config.llm_model
        resolved_base_url = base_url or config.llm_api_base
        resolved_api_key = api_key or config.llm_api_key

        cls._validate_provider(config.llm_provider)
        extra_body = cls._extra_body_for_model(resolved_model)

        return ChatOpenAI(
            model=resolved_model,
            temperature=temperature,
            streaming=streaming,
            base_url=resolved_base_url,
            api_key=resolved_api_key,
            timeout=config.llm_timeout,
            max_retries=config.llm_max_retries,
            extra_body=extra_body if extra_body else None,
        )

    @classmethod
    def _extra_body_for_model(cls, model: str) -> dict[str, bool]:
        if config.llm_enable_thinking is not None:
            return {"enable_thinking": config.llm_enable_thinking}
        if model.lower().startswith("qwen3.7"):
            return {"enable_thinking": True}
        return {}

    @classmethod
    def _validate_provider(cls, provider: str) -> None:
        if provider.lower() not in cls.SUPPORTED_PROVIDERS:
            supported = ", ".join(sorted(cls.SUPPORTED_PROVIDERS))
            raise ValueError(f"不支持的 LLM_PROVIDER={provider}，可选值: {supported}")

    @classmethod
    def validate_runtime_config(cls) -> None:
        cls._validate_provider(config.llm_provider)
        missing = []
        if not config.llm_model.strip():
            missing.append("LLM_MODEL/RAG_MODEL")
        if not config.llm_api_key.strip():
            missing.append("LLM_API_KEY/DASHSCOPE_API_KEY")
        if not config.llm_api_base.strip():
            missing.append("LLM_API_BASE/DASHSCOPE_API_BASE")
        if missing:
            raise RuntimeError(f"生产 Agent LLM 配置缺失: {', '.join(missing)}")
        if config.llm_timeout <= 0:
            raise RuntimeError("LLM_TIMEOUT 必须大于 0")
        if config.llm_max_retries < 0:
            raise RuntimeError("LLM_MAX_RETRIES 不能小于 0")

# 全局 LLM 工厂实例
llm_factory = LLMFactory()
