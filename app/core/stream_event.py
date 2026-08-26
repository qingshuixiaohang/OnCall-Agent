"""StreamEvent - 标准化事件协议

定义所有下游 Agent 产出的事件格式，RouterService 无需再做 if-elif 转换。
"""

from typing import Any, TypedDict


class StreamEvent(TypedDict):
    """标准化流式事件

    所有下游 Agent 的流式输出都应转换为 StreamEvent 后再 yield。

    type 字段取值：
    - "content": 文本内容（data 是字符串）
    - "done":    完成（data 是最终回答）
    - "error":   错误（data 是错误信息）
    - "router_info": 路由信息（target/reason 额外字段）
    """
    type: str
    data: Any
    target: str | None  # router_info 专用
    reason: str | None  # router_info 专用
