"""Router Service

负责编排 Router Agent 和下游 Agent，将不同目标的事件流统一输出。
"""

from collections.abc import AsyncGenerator
from typing import Any

from loguru import logger

from app.agent.multi_agent import multi_agent_service
from app.agent.router import router_agent
from app.services.aiops_service import aiops_service
from app.services.rag_agent_service import rag_agent_service


class RouterService:
    """路由服务

    1. 调用 Router Agent 做决策
    2. 根据决策路由到 RAG / AIOps / Multi-Agent
    3. 下游 Agent 各自通过 to_stream_event() 产出标准事件
    """

    async def route_stream(
        self,
        question: str,
        session_id: str
    ) -> AsyncGenerator[dict[str, Any]]:
        """路由并流式输出

        Args:
            question: 用户问题
            session_id: 会话ID

        Yields:
            Dict[str, Any]: 标准化事件流
        """
        # 1. 路由决策
        decision = await router_agent.route(question)
        target = decision.get("target", "rag")
        reason = decision.get("reason", "")
        routed_question = decision.get("question", question)

        logger.info(f"[会话 {session_id}] Router 决策: target={target}, reason={reason}")

        # 2. 发送路由信息事件
        yield {
            "type": "router_info",
            "target": target,
            "reason": reason,
        }

        # 3. 根据目标路由到下游 Agent
        if target == "rag":
            async for event in rag_agent_service.query_stream(routed_question, session_id=session_id):
                yield event
        elif target == "aiops":
            async for event in self._stream_aiops(routed_question, session_id):
                yield event
        elif target == "multi_agent":
            async for event in self._stream_multi_agent(routed_question, session_id):
                yield event
        else:
            logger.warning(f"[会话 {session_id}] 未知 target: {target}，降级到 RAG")
            async for event in rag_agent_service.query_stream(routed_question, session_id=session_id):
                yield event

    async def _stream_aiops(self, question: str, session_id: str) -> AsyncGenerator[dict[str, Any]]:
        """流式转发 AIOps 输出，通过 to_stream_event() 标准化"""
        async for event in aiops_service.diagnose(session_id=session_id, user_input=question):
            normalized = aiops_service.to_stream_event(event)
            if normalized:
                yield normalized
                if normalized.get("type") == "done":
                    return

    async def _stream_multi_agent(self, question: str, session_id: str) -> AsyncGenerator[dict[str, Any]]:
        """流式转发 Multi-Agent 输出，通过 to_stream_event() 标准化"""
        async for event in multi_agent_service.execute(user_input=question, session_id=session_id):
            normalized = multi_agent_service.to_stream_event(event)
            if normalized:
                yield normalized
                if normalized.get("type") == "done":
                    return


# 全局单例
router_service = RouterService()
