"""SQLite 记忆存储引擎（开发/单机模式）

使用 aiosqlite 实现异步 SQLite 存储，适合开发和单机部署场景
"""

import json
from typing import Optional, Dict, Any, List

import aiosqlite

from app.core.storage_engine import AbstractStorageEngine
from loguru import logger


class SQLiteStorageEngine(AbstractStorageEngine):
    """SQLite 记忆存储引擎（开发/单机模式）"""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._initialized = False

    async def _ensure_initialized(self):
        if self._initialized:
            return

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    thread_id TEXT PRIMARY KEY,
                    state_json TEXT NOT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_updated_at
                ON sessions(updated_at DESC)
            """)
            await db.commit()

        self._initialized = True

    async def save_state(self, thread_id: str, state: Dict[str, Any]) -> None:
        await self._ensure_initialized()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO sessions (thread_id, state_json, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(thread_id) DO UPDATE SET
                    state_json = excluded.state_json,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (thread_id, json.dumps(state, ensure_ascii=False)),
            )
            await db.commit()
        logger.debug(f"[SQLite] 会话状态已保存: {thread_id}")

    async def get_state(self, thread_id: str) -> Optional[Dict[str, Any]]:
        await self._ensure_initialized()
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT state_json FROM sessions WHERE thread_id = ?",
                (thread_id,),
            )
            row = await cursor.fetchone()
            if row:
                return json.loads(row[0])
            return None

    async def list_sessions(self) -> List[str]:
        await self._ensure_initialized()
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT thread_id FROM sessions ORDER BY updated_at DESC"
            )
            rows = await cursor.fetchall()
            return [row[0] for row in rows]

    async def delete_state(self, thread_id: str) -> bool:
        await self._ensure_initialized()
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "DELETE FROM sessions WHERE thread_id = ?",
                (thread_id,),
            )
            await db.commit()
            return cursor.rowcount > 0

    async def check_health(self) -> bool:
        try:
            await self._ensure_initialized()
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute("SELECT 1")
                return True
        except Exception as e:
            logger.error(f"SQLite 健康检查失败: {e}")
            return False
