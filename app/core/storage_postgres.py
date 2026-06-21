"""PostgreSQL 记忆存储引擎（生产模式）

使用 asyncpg 实现异步 PostgreSQL 存储，适合生产部署场景
"""

import json
from typing import Optional, Dict, Any, List

import asyncpg

from app.core.storage_engine import AbstractStorageEngine
from loguru import logger


class PostgreSQLStorageEngine(AbstractStorageEngine):
    """PostgreSQL 记忆存储引擎（生产模式）"""

    def __init__(self, url: str):
        self.url = url
        self._pool: Optional[asyncpg.Pool] = None

    async def _get_pool(self) -> asyncpg.Pool:
        if self._pool is None:
            self._pool = await asyncpg.create_pool(self.url)
            await self._init_schema()
        return self._pool

    async def _init_schema(self):
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    thread_id VARCHAR(255) PRIMARY KEY,
                    state_json JSONB NOT NULL,
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                )
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_sessions_updated_at
                ON sessions(updated_at DESC)
            """)

    async def save_state(self, thread_id: str, state: Dict[str, Any]) -> None:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO sessions (thread_id, state_json)
                VALUES ($1, $2::jsonb)
                ON CONFLICT (thread_id) DO UPDATE SET
                    state_json = $2::jsonb,
                    updated_at = CURRENT_TIMESTAMP
                """,
                thread_id,
                json.dumps(state),
            )
        logger.debug(f"[PostgreSQL] 会话状态已保存: {thread_id}")

    async def get_state(self, thread_id: str) -> Optional[Dict[str, Any]]:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT state_json FROM sessions WHERE thread_id = $1",
                thread_id,
            )
            if row:
                return dict(row["state_json"])
            return None

    async def list_sessions(self) -> List[str]:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT thread_id FROM sessions ORDER BY updated_at DESC"
            )
            return [row["thread_id"] for row in rows]

    async def delete_state(self, thread_id: str) -> bool:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM sessions WHERE thread_id = $1",
                thread_id,
            )
            return result == "DELETE 1"

    async def check_health(self) -> bool:
        try:
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
                return True
        except Exception as e:
            logger.error(f"PostgreSQL 健康检查失败: {e}")
            return False

    async def close(self):
        """关闭连接池"""
        if self._pool:
            await self._pool.close()
            self._pool = None
            logger.info("PostgreSQL 连接池已关闭")
