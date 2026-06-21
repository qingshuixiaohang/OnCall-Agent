"""记忆存储引擎抽象接口

定义统一的存储后端抽象，支持 SQLite（开发）和 PostgreSQL（生产）
"""

from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, List


class AbstractStorageEngine(ABC):
    """记忆存储引擎抽象基类"""

    @abstractmethod
    async def save_state(self, thread_id: str, state: Dict[str, Any]) -> None:
        """保存会话状态"""
        pass

    @abstractmethod
    async def get_state(self, thread_id: str) -> Optional[Dict[str, Any]]:
        """获取会话状态"""
        pass

    @abstractmethod
    async def list_sessions(self) -> List[str]:
        """列出所有会话ID"""
        pass

    @abstractmethod
    async def delete_state(self, thread_id: str) -> bool:
        """删除会话状态"""
        pass

    @abstractmethod
    async def check_health(self) -> bool:
        """健康检查"""
        pass
