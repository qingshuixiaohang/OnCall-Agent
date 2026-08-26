"""会话管理 API

使用 LangGraph 统一 checkpointer 管理会话，替代手搓 storage。

设计决策：
1. session 元数据操作通过 SessionStore 深模块隐藏 thread-id 惯例
2. 历史消息内容由各自的 Agent 服务提供
3. storage_health 通过轻量检查验证连接状态
"""

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse
from loguru import logger

from app.agent.multi_agent import multi_agent_service
from app.core.checkpointer import get_checkpointer
from app.core.session_store import SessionStore
from app.models.request import ClearRequest
from app.models.response import ApiResponse, SessionInfoResponse
from app.services.aiops_service import aiops_service
from app.services.rag_agent_service import rag_agent_service

router = APIRouter()

# 全局 SessionStore 实例（懒初始化）
_session_store: SessionStore | None = None


def _get_session_store() -> SessionStore:
    global _session_store
    if _session_store is None:
        _session_store = SessionStore(get_checkpointer())
    return _session_store


@router.get("/sessions")
async def list_sessions():
    """列出所有会话"""
    try:
        store = _get_session_store()
        session_list = await store.list_sessions()
        return JSONResponse(
            status_code=200,
            content={
                "code": 200,
                "data": {
                    "sessions": session_list,
                    "total": len(session_list),
                },
            },
        )
    except Exception as e:
        logger.error(f"列出会话失败: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/sessions/{session_id}")
async def get_session_state(session_id: str):
    """获取指定会话的基础信息

    返回 checkpoint 的元数据（thread_id、时间戳等）。
    具体的对话/诊断内容请通过正常 SSE 接口恢复。
    """
    try:
        store = _get_session_store()
        info = await store.get_session(session_id)

        if not info:
            raise HTTPException(status_code=404, detail="会话不存在")

        return JSONResponse(
            status_code=200,
            content={
                "code": 200,
                "data": {
                    "session_id": info["session_id"],
                    "thread_id": info["thread_id"],
                    "type": info["mode"],
                    "run_id": info["run_id"],
                    "updated_at": info["updated_at"],
                    "note": "具体会话内容请通过对应的 SSE 接口恢复",
                },
            },
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取会话状态失败: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/sessions/{session_id}/history")
async def get_session_history(
    session_id: str,
    mode: str = Query("rag", pattern="^(rag|aiops|multi)$"),
    run_id: str | None = Query(None),
):
    """读取指定模式的会话历史或诊断时间线。"""
    try:
        if mode == "rag":
            history = await rag_agent_service.get_session_history(session_id)
            return {
                "code": 200,
                "data": {
                    "mode": "rag",
                    "session_id": session_id,
                    "run_id": None,
                    "events": history,
                },
            }

        if not run_id:
            raise HTTPException(status_code=400, detail="诊断历史必须提供 run_id")

        if mode == "aiops":
            history = await aiops_service.get_history(session_id, run_id)
        else:
            history = await multi_agent_service.get_history(session_id, run_id)

        if history is None:
            raise HTTPException(status_code=404, detail="诊断运行不存在")

        return {"code": 200, "data": history}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"读取会话历史失败: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str):
    """删除指定会话（支持纯 session_id 或带前缀的 thread_id）"""
    try:
        store = _get_session_store()
        deleted = await store.delete_session(session_id)

        if not deleted:
            raise HTTPException(status_code=404, detail="会话不存在")

        logger.info(f"会话已删除: {session_id}")
        return JSONResponse(
            status_code=200,
            content={"code": 200, "message": "会话删除成功"},
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除会话失败: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/storage/health")
async def storage_health():
    """Checkpointer 健康检查"""
    try:
        cp = get_checkpointer()
        healthy = True
        try:
            async for _ in cp.alist(limit=1):
                break
        except Exception as conn_err:
            logger.warning(f"Checkpointer 连接异常: {conn_err}")
            healthy = False

        return JSONResponse(
            status_code=200 if healthy else 503,
            content={
                "code": 200 if healthy else 503,
                "data": {
                    "backend": type(cp).__name__,
                    "healthy": healthy,
                },
            },
        )
    except Exception as e:
        logger.error(f"健康检查失败: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/sessions/clear", response_model=ApiResponse)
async def clear_session(request: ClearRequest):
    """清空指定会话的历史（统一入口）"""
    try:
        success = await rag_agent_service.clear_session(request.session_id)
        logger.info(f"清空会话: {request.session_id}, 结果: {success}")
        return ApiResponse(
            status="success" if success else "error",
            message="会话已清空" if success else "清空会话失败",
            data=None,
        )
    except Exception as e:
        logger.error(f"清空会话错误: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/sessions/{session_id}/info", response_model=SessionInfoResponse)
async def get_session_info(session_id: str) -> SessionInfoResponse:
    """查询指定会话的历史消息（统一入口）"""
    try:
        history = await rag_agent_service.get_session_history(session_id)
        return SessionInfoResponse(
            session_id=session_id,
            message_count=len(history),
            history=history,
        )
    except Exception as e:
        logger.error(f"获取会话信息错误: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e
