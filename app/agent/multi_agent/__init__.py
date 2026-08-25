"""Multi-Agent 入口

复用 app/services/multi_agent_service.MultiAgentService 的增强实现
（含 time_context 统一时间范围、observability 观测、error 列表初始化等）。

本包 __init__.py 只做转发，保持旧调用点 from app.agent.multi_agent import multi_agent_service 兼容。
"""

from app.services.multi_agent_service import (
    MultiAgentService,
    multi_agent_service,
)

__all__ = ["MultiAgentService", "multi_agent_service"]
