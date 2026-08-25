"""会话管理 API

使用 LangGraph 统一 checkpointer 管理会话，替代手搓 storage。

设计决策：
1. list_sessions 通过 checkpointer.alist() 获取所有 thread_id
2. delete_session 通过 checkpointer.adelete_thread() 删除
3. get_session_state 返回 checkpoint 的基础元数据（thread_id、时间戳等）
   具体的对话内容由前端通过正常 SSE 流恢复，不再通过此 API 暴露完整状态
4. storage_health 改为 checkpointer 健康检查（通过数据库连接状态判断）
"""

import re

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse
from loguru import logger

from app.agent.multi_agent import multi_agent_service
from app.core.checkpointer import get_checkpointer
from app.services.aiops_service import aiops_service
from app.services.rag_agent_service import rag_agent_service

router = APIRouter()


@router.get("/sessions")
async def list_sessions():
    """列出所有会话（从 checkpointer 读取 thread 列表）"""
    try:
        cp = get_checkpointer()
        sessions = {}

        # alist 返回 AsyncIterator[CheckpointTuple]，提取 thread_id
        async for checkpoint_tuple in cp.alist(None):
            config = checkpoint_tuple.config
            if not config or "configurable" not in config:
                continue
            thread_id = config["configurable"].get("thread_id")
            if not thread_id:
                continue

            record = _session_record(thread_id, checkpoint_tuple)
            if record:
                previous = sessions.get(thread_id)
                if not previous or record["updated_at"] >= previous["updated_at"]:
                    sessions[thread_id] = record

        session_list = sorted(
            sessions.values(),
            key=lambda item: item.get("updated_at", ""),
            reverse=True,
        )

        return JSONResponse(
            status_code=200,
            content={
                "code": 200,
                "data": {
                    "sessions": session_list,
                    "total": len(session_list)
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
                if _matches_session(tid, session_id):
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
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str):
    """删除指定会话（支持纯 session_id 或带前缀的 thread_id）"""
    try:
        cp = get_checkpointer()
        deleted = False

        # 诊断每次运行有独立 run_id，因此先找出所有匹配的 thread。
        matching_threads = set()
        async for checkpoint_tuple in cp.alist(None):
            checkpoint_config = checkpoint_tuple.config
            if checkpoint_config and "configurable" in checkpoint_config:
                tid = checkpoint_config["configurable"].get("thread_id", "")
                if _matches_session(tid, session_id):
                    matching_threads.add(tid)

        for tid in matching_threads:
            try:
                await cp.adelete_thread(tid)
                logger.info(f"已删除 thread: {tid}")
                deleted = True
            except Exception as delete_err:
                logger.warning(f"删除 thread 失败 {tid}: {delete_err}")

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


def _matches_session(thread_id: str, session_id: str) -> bool:
    """匹配旧版 thread_id 和带 run_id 的诊断 thread_id。"""
    if thread_id == session_id or thread_id.endswith(f"-{session_id}"):
        return True

    return any(
        thread_id.startswith(f"{prefix}{session_id}-")
        for prefix in ("rag-", "aiops-", "multi-")
    )


def _public_session_id(thread_id: str) -> str:
    """把内部 thread_id 转成前端展示的逻辑会话 ID。"""
    record = _session_record(thread_id)
    return record["session_id"] if record else thread_id


def _session_record(thread_id: str, checkpoint_tuple=None) -> dict | None:
    """将内部 thread_id 转成前端可恢复的记录。"""
    prefixes = {
        "rag-": "rag",
        "aiops-": "aiops",
        "multi-": "multi",
    }
    prefix = next((value for value in prefixes if thread_id.startswith(value)), None)
    if prefix is None:
        return None

    value = thread_id[len(prefix):]
    match = re.match(r"^(.*)-([0-9a-f]{32})$", value)
    session_id = match.group(1) if match else value
    run_id = match.group(2) if match else None

    checkpoint = getattr(checkpoint_tuple, "checkpoint", None) or {}
    updated_at = checkpoint.get("ts") or ""
    return {
        "session_id": session_id,
        "thread_id": thread_id,
        "mode": prefixes[prefix],
        "run_id": run_id,
        "title": session_id,
        "updated_at": updated_at,
    }


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
