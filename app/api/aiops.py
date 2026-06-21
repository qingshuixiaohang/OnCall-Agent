"""
AIOps 智能运维接口
"""

import json
from fastapi import APIRouter
from sse_starlette.sse import EventSourceResponse
from loguru import logger

from app.models.aiops import AIOpsRequest
from app.services.aiops_service import aiops_service

router = APIRouter()


@router.post("/aiops")
async def diagnose_stream(request: AIOpsRequest):
    """
    AIOps 故障诊断接口（流式 SSE）

    **功能说明：**
    - 支持用户自定义诊断问题（自然语言），也支持默认全系统告警诊断
    - 使用 Plan-Execute-Replan 模式进行智能诊断
    - 流式返回诊断过程和结果

    **SSE 事件类型：**

    1. `status` - 状态更新
    2. `plan` - 诊断计划制定完成
    3. `step_complete` - 步骤执行完成
    4. `report` - 最终诊断报告
    5. `complete` - 诊断完成
    6. `error` - 错误信息

    **使用示例：**

    默认诊断（全系统告警检查）：
    ```bash
    curl -X POST "http://localhost:9900/api/aiops" \
      -H "Content-Type: application/json" \
      -d '{"session_id": "session-123"}' \
      --no-buffer
    ```

    自定义诊断问题：
    ```bash
    curl -X POST "http://localhost:9900/api/aiops" \
      -H "Content-Type: application/json" \
      -d '{"session_id": "session-123", "question": "查询所有 ERROR 级别的日志"}' \
      --no-buffer
    ```

    **前端使用示例：**
    ```javascript
    const eventSource = new EventSource('/api/aiops');

    eventSource.onmessage = (event) => {
      const data = JSON.parse(event.data);

      if (data.type === 'plan') {
        console.log('诊断计划:', data.plan);
      } else if (data.type === 'step_complete') {
        console.log('步骤完成:', data.current_step);
      } else if (data.type === 'report') {
        console.log('最终报告:', data.report);
      } else if (data.type === 'complete') {
        console.log('诊断完成');
        eventSource.close();
      }
    };
    ```

    Args:
        request: AIOps 诊断请求（支持可选的 question 字段用于自定义诊断）

    Returns:
        SSE 事件流
    """
    session_id = request.session_id or "default"
    user_question = request.question

    if user_question:
        logger.info(f"[会话 {session_id}] 收到 AIOps 自定义诊断请求（流式）: {user_question}")
    else:
        logger.info(f"[会话 {session_id}] 收到 AIOps 诊断请求（流式，默认全系统诊断）")

    async def event_generator():
        try:
            async for event in aiops_service.diagnose(
                session_id=session_id,
                user_input=user_question
            ):
                # 发送事件
                yield {
                    "event": "message",
                    "data": json.dumps(event, ensure_ascii=False)
                }

                # 如果是完成或错误事件，结束流
                if event.get("type") in ["complete", "error"]:
                    break

            logger.info(f"[会话 {session_id}] AIOps 诊断流式响应完成")

        except Exception as e:
            logger.error(f"[会话 {session_id}] AIOps 诊断流式响应异常: {e}", exc_info=True)
            yield {
                "event": "message",
                "data": json.dumps({
                    "type": "error",
                    "stage": "exception",
                    "message": f"诊断异常: {str(e)}"
                }, ensure_ascii=False)
            }

    return EventSourceResponse(event_generator())
