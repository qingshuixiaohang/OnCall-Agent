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
    3. 将下游事件流统一输出为 content/done/error 格式
    """

    async def route_stream(
        self,
        question: str,
        session_id: str
    ) -> AsyncGenerator[dict[str, Any], None]:
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

        # 2. 发送路由信息事件（前端可选择展示）
        yield {
            "type": "router_info",
            "target": target,
            "reason": reason,
        }

        # 3. 根据目标路由到下游 Agent
        if target == "rag":
            async for event in self._stream_rag(routed_question, session_id):
                yield event
        elif target == "aiops":
            async for event in self._stream_aiops(routed_question, session_id):
                yield event
        elif target == "multi_agent":
            async for event in self._stream_multi_agent(routed_question, session_id):
                yield event
        else:
            # 理论上不会到这里，兜底到 RAG
            logger.warning(f"[会话 {session_id}] 未知 target: {target}，降级到 RAG")
            async for event in self._stream_rag(routed_question, session_id):
                yield event

    async def _stream_rag(self, question: str, session_id: str) -> AsyncGenerator[dict[str, Any], None]:
        """流式转发 RAG Agent 输出"""
        async for event in rag_agent_service.query_stream(question, session_id=session_id):
            yield event

    async def _stream_aiops(self, question: str, session_id: str) -> AsyncGenerator[dict[str, Any], None]:
        """流式转发 AIOps 输出，并统一为 content/done/error"""
        async for event in aiops_service.diagnose(session_id=session_id, user_input=question):
            normalized = self._normalize_aiops_event(event)
            if normalized:
                yield normalized
                if normalized.get("type") == "done":
                    return

    async def _stream_multi_agent(self, question: str, session_id: str) -> AsyncGenerator[dict[str, Any], None]:
        """流式转发 Multi-Agent 输出，并统一为 content/done/error"""
        async for event in multi_agent_service.execute(user_input=question, session_id=session_id):
            normalized = self._normalize_multi_agent_event(event)
            if normalized:
                yield normalized
                if normalized.get("type") == "done":
                    return

    def _normalize_aiops_event(self, event: dict[str, Any]) -> dict[str, Any] | None:
        """将 AIOps 事件标准化为 content/done/error"""
        event_type = event.get("type")

        if event_type == "status":
            return {
                "type": "content",
                "data": f"⏳ {event.get('message', '')}\n"
            }
        elif event_type == "plan":
            plan = event.get("plan", [])
            if isinstance(plan, list):
                plan_text = "\n".join([f"- {p}" for p in plan])
            else:
                plan_text = str(plan)
            return {
                "type": "content",
                "data": f"## 执行计划\n{plan_text}\n\n"
            }
        elif event_type == "step_complete":
            return {
                "type": "content",
                "data": f"✅ {event.get('message', '')}\n"
            }
        elif event_type == "report":
            report = event.get("report", "")
            return {
                "type": "content",
                "data": f"## 诊断报告\n\n{report}\n"
            }
        elif event_type == "complete":
            # 优先取 diagnosis.report，再取 response
            diagnosis = event.get("diagnosis", {})
            report = diagnosis.get("report", "") or event.get("response", "")
            return {
                "type": "done",
                "data": report
            }
        elif event_type == "error":
            return {
                "type": "error",
                "data": event.get("message", "AIOps 诊断失败")
            }

        # 其他类型忽略
        return None

    def _normalize_multi_agent_event(self, event: dict[str, Any]) -> dict[str, Any] | None:
        """将 Multi-Agent 事件标准化为 content/done/error"""
        event_type = event.get("type")

        if event_type == "routing":
            specialists = ", ".join(event.get("specialists", []))
            reason = event.get("reason", "")
            return {
                "type": "content",
                "data": f"## 路由决策\n**专家**: {specialists}\n**原因**: {reason}\n\n"
            }
        elif event_type == "specialist_result":
            name = event.get("name", "")
            result = event.get("result", {})
            summary = result.get("summary", "") if isinstance(result, dict) else ""
            return {
                "type": "content",
                "data": f"### {name} 分析完成\n{summary or '已获取分析结果'}\n\n"
            }
        elif event_type == "complete":
            return {
                "type": "done",
                "data": event.get("report", "")
            }
        elif event_type == "error":
            return {
                "type": "error",
                "data": event.get("message", "Multi-Agent 诊断失败")
            }

        return None


# 全局单例
router_service = RouterService()
