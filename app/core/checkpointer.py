"""统一 Checkpointer 管理

使用 LangGraph 官方的 AsyncSqliteSaver / AsyncPostgresSaver，
替代手搓的 storage + MemorySaver 混用方案。

设计决策：
1. 应用生命周期内（lifespan）统一创建和管理 checkpointer
2. 所有 Agent 共享同一个 checkpointer 实例（单例）
3. 启动时自动 setup() 建表
4. 关闭时关闭数据库连接
5. 不同 Agent 通过 thread_id 前缀隔离状态（rag- / aiops- / multi-）

为什么不用 MemorySaver？
- MemorySaver 是纯内存存储，进程重启后所有会话丢失
- 官方 AsyncSqliteSaver / AsyncPostgresSaver 是生产级持久化方案
- 与 LangGraph 的 checkpoint 机制深度集成，状态恢复更完整

升级前 vs 升级后：
- 升级前：MemorySaver（内存）+ 手搓 storage（SQLite/PG）= 两套机制，状态不一致
- 升级后：统一 checkpointer（SQLite/PG）= 一套机制，LangGraph 原生支持
"""

from typing import Any, Optional

from langgraph.checkpoint.base import BaseCheckpointSaver
from loguru import logger

from app.config import config

_CHECKPOINTER: Optional[BaseCheckpointSaver] = None
_CONN: Optional[Any] = None  # aiosqlite.Connection 或 asyncpg.Connection


async def setup_checkpointer() -> BaseCheckpointSaver:
    """创建并初始化全局 checkpointer

    根据 config.storage_backend 自动选择 SQLite 或 PostgreSQL。
    启动时调用 setup() 确保表结构已创建。
    """
    global _CHECKPOINTER, _CONN

    if _CHECKPOINTER is not None:
        return _CHECKPOINTER

    backend = config.storage_backend.lower()
    logger.info(f"初始化 LangGraph checkpointer: backend={backend}")

    if backend == "sqlite":
        import aiosqlite

        db_path = config.storage_sqlite_path
        # 确保目录存在
        import os
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)

        _CONN = await aiosqlite.connect(db_path)
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

        _CHECKPOINTER = AsyncSqliteSaver(_CONN)
        await _CHECKPOINTER.setup()
        logger.info(f"SQLite checkpointer 已初始化: {db_path}")

    elif backend == "postgresql":
        import asyncpg

        dsn = config.storage_postgres_url
        if not dsn:
            raise ValueError("PostgreSQL backend requires STORAGE_POSTGRES_URL")

        _CONN = await asyncpg.connect(dsn)
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

        _CHECKPOINTER = AsyncPostgresSaver(_CONN)
        await _CHECKPOINTER.setup()
        logger.info("PostgreSQL checkpointer 已初始化")

    else:
        raise ValueError(f"不支持的 checkpointer 后端: {backend}")

    return _CHECKPOINTER


def get_checkpointer() -> BaseCheckpointSaver:
    """获取全局 checkpointer 实例（单例）

    必须在 lifespan 中先调用 setup_checkpointer() 后才能使用。
    """
    if _CHECKPOINTER is None:
        raise RuntimeError(
            "checkpointer 尚未初始化，请在 lifespan 中先调用 setup_checkpointer()"
        )
    return _CHECKPOINTER


async def close_checkpointer() -> None:
    """关闭 checkpointer 和数据库连接"""
    global _CHECKPOINTER, _CONN

    if _CHECKPOINTER is not None:
        logger.info("关闭 LangGraph checkpointer...")
        _CHECKPOINTER = None

    if _CONN is not None:
        await _CONN.close()
        _CONN = None
        logger.info("checkpointer 数据库连接已关闭")


# ============================================================================
# thread_id 前缀工具（用于不同 Agent 的状态隔离）
# ============================================================================

def thread_id_with_prefix(session_id: str, prefix: str) -> str:
    """为不同 Agent 生成隔离的 thread_id

    防止 RAG / AIOps / Multi-Agent 使用相同 session_id 时状态冲突。

    Args:
        session_id: 前端传入的会话 ID
        prefix: Agent 类型前缀，如 "rag", "aiops", "multi"

    Returns:
        str: 带前缀的 thread_id，如 "rag-default"
    """
    # 如果 session_id 已经有前缀，不再重复添加
    if session_id.startswith(f"{prefix}-"):
        return session_id
    return f"{prefix}-{session_id}"
