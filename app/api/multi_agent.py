"""Multi-Agent 智能运维接口

提供 Multi-Agent 协作的 AIOps 诊断接口
"""

import json

from fastapi import APIRouter
from loguru import logger
from sse_starlette.sse import EventSourceResponse

from app.agent.multi_agent import multi_agent_service
from app.models.aiops import AIOpsRequest

router = APIRouter()


@router.post("/aiops_multi")
async def diagnose_multi_stream(request: AIOpsRequest):
    """
    Multi-Agent AIOps 诊断接口（流式 SSE）

    **功能说明：**
    - 使用 Multi-Agent 协作模式进行智能诊断
    - Supervisor 自动路由到合适的 Specialist
    - 流式返回诊断过程和结果

    **SSE 事件类型：**
    1. `routing` - Supervisor 路由决策
    2. `specialist_result` - Specialist 分析结果
    3. `specialist_error` - Specialist 执行错误
    4. `complete` - 诊断完成
    5. `error` - 系统错误

    **使用示例：**

    复合诊断（推荐，验证 Multi-Agent 能力）：
    ```bash
    curl -X POST "http://localhost:9900/api/aiops_multi" \
      -H "Content-Type: application/json" \
      -d '{"session_id": "test-001", "question": "全面诊断 data-sync-service，它响应很慢，排查一下原因"}' \
      --no-buffer
    ```

    纯日志查询：
    ```bash
    curl -X POST "http://localhost:9900/api/aiops_multi" \
      -H "Content-Type: application/json" \
      -d '{"session_id": "test-002", "question": "data-sync-service 最近有什么错误日志？"}' \
      --no-buffer
    ```

    纯监控查询：
    ```bash
    curl -X POST "http://localhost:9900/api/aiops_multi" \
      -H "Content-Type: application/json" \
      -d '{"session_id": "test-003", "question": "data-sync-service 的 CPU 和内存使用率怎么样？"}' \
      --no-buffer
    ```

    知识库查询：
    ```bash
    curl -X POST "http://localhost:9900/api/aiops_multi" \
      -H "Content-Type: application/json" \
      -d '{"session_id": "test-004", "question": "CPU 使用率过高的处理方案是什么？"}' \
      --no-buffer
    ```
    """
    session_id = request.session_id or "default"
    user_question = request.question or "诊断当前系统是否存在告警"

    logger.info(f"[会话 {session_id}] 收到 Multi-Agent 诊断请求: {user_question[:100]}")

    async def event_generator():
        try:
            async for event in multi_agent_service.execute(
                user_input=user_question,
                session_id=session_id,
                run_id=request.run_id,
                resume=request.resume,
            ):
                yield {
                    "event": "message",
                    "data": json.dumps(event, ensure_ascii=False)
                }

                if event.get("type") in ["complete", "error"]:
                    break

            logger.info(f"[会话 {session_id}] Multi-Agent 诊断完成")

        except Exception as e:
            logger.error(f"[会话 {session_id}] Multi-Agent 诊断异常: {e}", exc_info=True)
            yield {
                "event": "message",
                "data": json.dumps({
                    "type": "error",
                    "message": f"诊断异常: {str(e)}"
                }, ensure_ascii=False)
            }

    return EventSourceResponse(event_generator())
