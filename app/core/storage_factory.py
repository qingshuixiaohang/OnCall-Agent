"""存储引擎工厂

提供全局单例的存储引擎实例，支持开发/生产环境一键切换
"""

from typing import Optional

from app.config import config
from app.core.storage_engine import AbstractStorageEngine
from app.core.storage_sqlite import SQLiteStorageEngine
from app.core.storage_postgres import PostgreSQLStorageEngine
from loguru import logger


class StorageFactory:
    """存储引擎工厂"""

    @staticmethod
    def create_storage() -> AbstractStorageEngine:
        backend = config.storage_backend.lower()
        logger.info(f"初始化存储后端: {backend}")

        if backend == "sqlite":
            engine: AbstractStorageEngine = SQLiteStorageEngine(config.storage_sqlite_path)
            logger.info(f"SQLite 数据库路径: {config.storage_sqlite_path}")
            return engine

        elif backend == "postgresql":
            if not config.storage_postgres_url:
                raise ValueError("PostgreSQL backend requires STORAGE_POSTGRES_URL")
            engine = PostgreSQLStorageEngine(config.storage_postgres_url)
            logger.info(f"PostgreSQL 连接: {config.storage_postgres_url[:30]}...")
            return engine

        else:
            raise ValueError(f"不支持的存储后端: {backend}")


# 全局存储引擎实例
_storage_engine: Optional[AbstractStorageEngine] = None


def get_storage_engine() -> AbstractStorageEngine:
    """获取存储引擎实例（单例）"""
    global _storage_engine
    if _storage_engine is None:
        _storage_engine = StorageFactory.create_storage()
    return _storage_engine


def reset_storage_engine():
    """重置存储引擎实例（主要用于测试）"""
    global _storage_engine
    _storage_engine = None
