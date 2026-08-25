"""全局统一时间上下文。"""

from collections.abc import Iterable
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

TIMEZONE = "Asia/Shanghai"
TIME_TOOL_NAMES = frozenset({"get_current_time", "get_current_timestamp"})


def build_time_context(now: datetime | None = None) -> dict[str, Any]:
    """为一次请求生成稳定的时间范围。"""
    timezone = ZoneInfo(TIMEZONE)
    current = now.astimezone(timezone) if now else datetime.now(timezone)
    end_time_ms = int(current.timestamp() * 1000)
    log_start = current - timedelta(minutes=30)
    metric_start = current - timedelta(hours=1)

    return {
        "timezone": TIMEZONE,
        "now": current.strftime("%Y-%m-%d %H:%M:%S"),
        "end_time_ms": end_time_ms,
        "log_start_time_ms": int(log_start.timestamp() * 1000),
        "metric_start_time_ms": int(metric_start.timestamp() * 1000),
        "log_start": log_start.strftime("%Y-%m-%d %H:%M:%S"),
        "metric_start": metric_start.strftime("%Y-%m-%d %H:%M:%S"),
    }


def format_time_context(context: dict[str, Any]) -> str:
    """格式化给 LLM/工具调用使用的时间范围。"""
    return (
        f"时区={context.get('timezone', TIMEZONE)}, "
        f"当前时间={context.get('now', '')}, "
        f"日志范围={context.get('log_start', '')} 至 {context.get('now', '')} "
        f"({context.get('log_start_time_ms', 0)} 至 {context.get('end_time_ms', 0)} ms), "
        f"监控范围={context.get('metric_start', '')} 至 {context.get('now', '')} "
        f"({context.get('metric_start_time_ms', 0)} 至 {context.get('end_time_ms', 0)} ms)"
    )


def without_time_tools(tools: Iterable[Any]) -> list[Any]:
    """从工具列表移除时间工具。"""
    return [tool for tool in tools if getattr(tool, "name", "") not in TIME_TOOL_NAMES]
