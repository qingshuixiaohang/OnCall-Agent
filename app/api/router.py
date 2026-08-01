"""Router Agent 接口

提供统一入口：自动路由到 RAG / AIOps / Multi-Agent。
"""

import json
from fastapi import APIRouter
from sse_starlette.sse import EventSourceResponse
from loguru import logger

from app.models.aiops import AIOpsRequest
from app.services.router_service import router_service

router = APIRouter()


@router.post("/router")
async def router_stream(request: AIOpsRequest):
    """智能路由接口（流式 SSE）

    根据用户输入自动路由到最合适的 Agent：
    - RAG：通用知识库问答
    - AIOps：单一维度运维诊断
    - Multi-Agent：复杂故障排查

    **SSE 事件类型：**
    1. `router_info` - 路由决策信息
    2. `content` - 流式内容
    3. `done` - 完成
    4. `error` - 错误

    **使用示例：**
    ```bash
    curl -X POST "http://localhost:9900/api/router" \
      -H "Content-Type: application/json" \
      -d '{"session_id": "test-001", "question": "CPU 使用率过高的处理方案是什么？"}' \
      --no-buffer
    ```
    """
    session_id = request.session_id or "default"
    user_question = request.question or ""

    logger.info(f"[会话 {session_id}] 收到 Router 请求: {user_question[:100]}")

    async def event_generator():
        try:
            async for event in router_service.route_stream(
                question=user_question,
                session_id=session_id
            ):
                yield {
                    "event": "message",
                    "data": json.dumps(event, ensure_ascii=False)
                }

                if event.get("type") in ["done", "error"]:
                    break

            logger.info(f"[会话 {session_id}] Router 请求完成")

        except Exception as e:
            logger.error(f"[会话 {session_id}] Router 异常: {e}", exc_info=True)
            yield {
                "event": "message",
                "data": json.dumps({
                    "type": "error",
                    "data": f"路由异常: {str(e)}"
                }, ensure_ascii=False)
            }

    return EventSourceResponse(event_generator())
