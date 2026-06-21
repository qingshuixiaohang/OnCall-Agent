"""
会话管理 API

提供会话的列出、获取、删除以及存储后端的健康检查功能
"""

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from app.core.storage_factory import get_storage_engine
from loguru import logger

router = APIRouter()


@router.get("/sessions")
async def list_sessions():
    """列出所有会话"""
    try:
        storage = get_storage_engine()
        sessions = await storage.list_sessions()
        return JSONResponse(
            status_code=200,
            content={
                "code": 200,
                "data": {
                    "sessions": sessions,
                    "total": len(sessions)
                }
            }
        )
    except Exception as e:
        logger.error(f"列出会话失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sessions/{session_id}")
async def get_session_state(session_id: str):
    """获取指定会话的状态"""
    try:
        storage = get_storage_engine()
        state = await storage.get_state(session_id)

        if state is None:
            raise HTTPException(status_code=404, detail="会话不存在")

        # 过滤敏感信息
        filtered_state = {
            "input": state.get("input", ""),
            "plan": state.get("plan", []),
            "past_steps_count": len(state.get("past_steps", [])),
            "response": state.get("response", "")
        }

        return JSONResponse(
            status_code=200,
            content={
                "code": 200,
                "data": {
                    "session_id": session_id,
                    "state": filtered_state
                }
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取会话状态失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str):
    """删除指定会话"""
    try:
        storage = get_storage_engine()
        success = await storage.delete_state(session_id)

        if not success:
            raise HTTPException(status_code=404, detail="会话不存在")

        logger.info(f"会话已删除: {session_id}")
        return JSONResponse(
            status_code=200,
            content={
                "code": 200,
                "message": "会话删除成功"
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除会话失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/storage/health")
async def storage_health():
    """存储后端健康检查"""
    try:
        storage = get_storage_engine()
        is_healthy = await storage.check_health()

        return JSONResponse(
            status_code=200 if is_healthy else 503,
            content={
                "code": 200 if is_healthy else 503,
                "data": {
                    "backend": type(storage).__name__,
                    "healthy": is_healthy
                }
            }
        )
    except Exception as e:
        logger.error(f"健康检查失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
