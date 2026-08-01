"""会话管理 API

使用 LangGraph 统一 checkpointer 管理会话，替代手搓 storage。

设计决策：
1. list_sessions 通过 checkpointer.alist() 获取所有 thread_id
2. delete_session 通过 checkpointer.adelete_thread() 删除
3. get_session_state 返回 checkpoint 的基础元数据（thread_id、时间戳等）
   具体的对话内容由前端通过正常 SSE 流恢复，不再通过此 API 暴露完整状态
4. storage_health 改为 checkpointer 健康检查（通过数据库连接状态判断）
"""

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from loguru import logger

from app.core.checkpointer import get_checkpointer

router = APIRouter()


@router.get("/sessions")
async def list_sessions():
    """列出所有会话（从 checkpointer 读取 thread 列表）"""
    try:
        cp = get_checkpointer()
        sessions = []

        # alist 返回 AsyncIterator[CheckpointTuple]，提取 thread_id
        async for checkpoint_tuple in cp.alist(None):
            config = checkpoint_tuple.config
            if config and "configurable" in config:
                thread_id = config["configurable"].get("thread_id")
                if thread_id and thread_id not in sessions:
                    sessions.append(thread_id)

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
    """获取指定会话的基础信息

    返回 checkpoint 的元数据（thread_id、时间戳等）。
    具体的对话/诊断内容请通过正常 SSE 接口恢复。
    """
    try:
        cp = get_checkpointer()

        # 尝试查找任意前缀的 session
        # session_id 可能是前端传的纯 ID，也可能是带前缀的 thread_id
        found = False
        thread_id = session_id
        metadata = None

        async for checkpoint_tuple in cp.alist(None):
            config = checkpoint_tuple.config
            if config and "configurable" in config:
                tid = config["configurable"].get("thread_id", "")
                if tid == session_id or tid.endswith(f"-{session_id}"):
                    found = True
                    thread_id = tid
                    metadata = {
                        "thread_id": tid,
                        "checkpoint_ns": config["configurable"].get("checkpoint_ns"),
                    }
                    break

        if not found:
            raise HTTPException(status_code=404, detail="会话不存在")

        # 推断会话类型（基于 thread_id 前缀）
        session_type = "unknown"
        if thread_id.startswith("rag-"):
            session_type = "rag"
        elif thread_id.startswith("aiops-"):
            session_type = "aiops"
        elif thread_id.startswith("multi-"):
            session_type = "multi_agent"

        return JSONResponse(
            status_code=200,
            content={
                "code": 200,
                "data": {
                    "session_id": session_id,
                    "thread_id": thread_id,
                    "type": session_type,
                    "metadata": metadata,
                    "note": "具体会话内容请通过对应的 SSE 接口恢复"
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
    """删除指定会话（支持纯 session_id 或带前缀的 thread_id）"""
    try:
        cp = get_checkpointer()
        deleted = False

        # 如果是纯 session_id，尝试删除所有前缀版本
        prefixes = ["", "rag-", "aiops-", "multi-"]
        for prefix in prefixes:
            tid = f"{prefix}{session_id}" if prefix else session_id
            try:
                await cp.adelete_thread(tid)
                logger.info(f"已删除 thread: {tid}")
                deleted = True
            except Exception:
                # thread 可能不存在，忽略错误
                pass

        if not deleted:
            # 最后再遍历一次，尝试精确匹配
            async for checkpoint_tuple in cp.alist(None):
                config = checkpoint_tuple.config
                if config and "configurable" in config:
                    tid = config["configurable"].get("thread_id", "")
                    if tid == session_id or tid.endswith(f"-{session_id}"):
                        await cp.adelete_thread(tid)
                        deleted = True
                        break

        if not deleted:
            raise HTTPException(status_code=404, detail="会话不存在")

        logger.info(f"会话已删除: {session_id}")
        return JSONResponse(
            status_code=200,
            content={"code": 200, "message": "会话删除成功"}
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除会话失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/storage/health")
async def storage_health():
    """Checkpointer 健康检查"""
    try:
        cp = get_checkpointer()
        # 通过一次轻量操作验证连接是否存活
        healthy = True
        try:
            # 尝试读取至少一条记录（或空结果），验证数据库连接正常
            count = 0
            async for _ in cp.alist(limit=1):
                count += 1
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
                    "healthy": healthy
                }
            }
        )
    except Exception as e:
        logger.error(f"健康检查失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
