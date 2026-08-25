"""Langfuse 观测适配层。

默认关闭且不影响业务流程。开启后统一提供：
- 请求级 Agent trace；
- LangChain/LangGraph callback；
- RAG retriever 和 MCP tool observation；
- session、mode、run_id 等业务上下文。

默认不记录完整问题、回答和文档正文，避免把敏感业务内容上传到第三方服务。
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from loguru import logger

from app.config import config

try:
    from langfuse import Langfuse, get_client, propagate_attributes
    from langfuse.langchain import CallbackHandler
except ImportError:  # pragma: no cover - 依赖由 pyproject 管理
    Langfuse = None  # type: ignore[assignment,misc]
    get_client = None  # type: ignore[assignment]
    propagate_attributes = None  # type: ignore[assignment]
    CallbackHandler = None  # type: ignore[assignment,misc]


_handler_context: ContextVar[Any | None] = ContextVar(
    "langfuse_callback_handler", default=None
)
_client: Any | None = None
_REDACT_KEYS = {
    "content",
    "text",
    "prompt",
    "messages",
    "question",
    "answer",
    "response",
    "context",
    "page_content",
}
_SAFE_STRING_KEYS = {
    "name",
    "tool",
    "server",
    "mode",
    "run_id",
    "source",
    "sources",
    "status",
    "type",
    "level",
}


def is_enabled() -> bool:
    """判断 Langfuse 是否已经具备完整配置。"""
    return bool(
        config.langfuse_enabled
        and config.langfuse_public_key.strip()
        and config.langfuse_secret_key.strip()
        and Langfuse is not None
    )


def configuration_status() -> str:
    """返回启动日志使用的配置状态。"""
    if not config.langfuse_enabled:
        return "disabled"
    if not config.langfuse_public_key or not config.langfuse_secret_key:
        return "incomplete"
    if Langfuse is None:
        return "dependency_missing"
    return "enabled"


def get_langfuse_client() -> Any | None:
    """延迟创建单例 Langfuse 客户端。"""
    global _client
    if not is_enabled():
        return None
    if _client is None:
        _client = Langfuse(
            public_key=config.langfuse_public_key,
            secret_key=config.langfuse_secret_key,
            base_url=config.langfuse_base_url,
            environment=config.langfuse_environment,
            release=config.langfuse_release or None,
            sample_rate=config.langfuse_sample_rate,
            mask=_mask_langfuse_data,
        )
    return _client


def _mask_langfuse_data(*, data: Any, **_: Any) -> Any:
    """脱敏 Langfuse SDK 和 LangChain callback 写入的输入输出。"""
    if config.langfuse_capture_content:
        return data

    def mask_value(value: Any, key: str | None = None) -> Any:
        if key in _REDACT_KEYS:
            return "<redacted>"
        if isinstance(value, dict):
            return {str(k): mask_value(v, str(k)) for k, v in value.items()}
        if isinstance(value, list):
            return [mask_value(item, key) for item in value]
        if isinstance(value, tuple):
            return [mask_value(item, key) for item in value]
        if isinstance(value, str):
            if key in _SAFE_STRING_KEYS:
                return value[:200]
            return "<redacted>"
        return value

    return mask_value(data)


def _safe_input(value: Any) -> Any:
    """根据配置决定是否记录完整输入。"""
    if config.langfuse_capture_content:
        if isinstance(value, str):
            return value[:4000]
        return value
    if isinstance(value, dict):
        return {
            key: ("<redacted>" if key in {"question", "content", "prompt"} else value)
            for key, value in value.items()
        }
    if isinstance(value, str):
        return "<redacted>"
    return {"captured": False}


def current_handler() -> Any | None:
    """获取当前请求绑定的 LangChain callback。"""
    return _handler_context.get()


def langchain_config(
    base: dict[str, Any] | None = None,
    *,
    session_id: str | None = None,
    mode: str | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    """为 Runnable/Graph 合并当前请求的 Langfuse callback 和业务元数据。"""
    result = dict(base or {})
    metadata = dict(result.get("metadata") or {})
    tags = list(result.get("tags") or [])

    if session_id:
        metadata["session_id"] = session_id
    if mode:
        metadata["mode"] = mode
        tags.append(f"mode:{mode}")
    if run_id:
        metadata["run_id"] = run_id

    handler = current_handler()
    if handler is not None:
        result["callbacks"] = [handler]
    if metadata:
        result["metadata"] = metadata
    if tags:
        result["tags"] = list(dict.fromkeys(tags))
    return result


@contextmanager
def request_trace(
    *,
    name: str,
    session_id: str,
    mode: str,
    question: str,
    run_id: str | None = None,
) -> Iterator[Any | None]:
    """创建一个请求级 Agent trace，并把 callback 传播到子链路。"""
    client = get_langfuse_client()
    if client is None:
        yield None
        return

    metadata = {"mode": mode}
    if run_id:
        metadata["run_id"] = run_id

    yielded = False
    try:
        with propagate_attributes(
            session_id=session_id,
            trace_name=name,
            metadata=metadata,
            tags=["oncall-agent", f"mode:{mode}"],
            environment=config.langfuse_environment,
        ):
            with client.start_as_current_observation(
                name=name,
                as_type="agent",
                input={"question": _safe_input(question)},
                metadata=metadata,
            ) as observation:
                trace_id = client.get_current_trace_id()
                observation_id = client.get_current_observation_id()
                trace_context = {"trace_id": trace_id} if trace_id else None
                if trace_context and observation_id:
                    trace_context["parent_span_id"] = observation_id

                handler = CallbackHandler(
                    public_key=config.langfuse_public_key,
                    trace_context=trace_context,
                )
                token = _handler_context.set(handler)
                try:
                    yielded = True
                    yield observation
                except Exception as exc:
                    observation.update(
                        level="ERROR",
                        status_message=str(exc)[:1000],
                    )
                    raise
                finally:
                    _handler_context.reset(token)
    except Exception as exc:
        if yielded:
            raise
        logger.warning(f"Langfuse 请求追踪失败，不影响主流程: {exc}")
        yield None


@contextmanager
def observation(
    *,
    name: str,
    as_type: str,
    input_data: Any = None,
) -> Iterator[Any | None]:
    """创建一个可选的嵌套 observation，失败时不影响业务。"""
    client = get_langfuse_client()
    if client is None:
        yield None
        return

    yielded = False
    try:
        with client.start_as_current_observation(
            name=name,
            as_type=as_type,
            input=_safe_input(input_data),
        ) as current:
            yielded = True
            yield current
    except Exception as exc:
        if yielded:
            raise
        logger.warning(f"Langfuse observation 失败，不影响主流程: {exc}")
        yield None


def flush() -> None:
    """在应用关闭或脚本退出前刷新缓冲区。"""
    client = get_langfuse_client()
    if client is not None:
        client.flush()


def summarize_tool_output(result: Any) -> dict[str, Any]:
    """生成低敏的工具结果摘要。"""
    if isinstance(result, dict):
        return {
            "keys": list(result.keys())[:30],
            "error": str(result.get("error", ""))[:300] if result.get("error") else None,
        }
    if isinstance(result, list):
        return {"type": "list", "count": len(result)}
    return {"type": type(result).__name__}
