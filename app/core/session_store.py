"""SessionStore - 深模块：隐藏 thread-id 惯例

Thread ID 格式：
  - RAG:       rag-{session_id}
  - AIOps:     aiops-{session_id}-{run_id}   (run_id 是 32 位 hex)
  - Multi:     multi-{session_id}-{run_id}   (run_id 是 32 位 hex)

职责：
  1. 从 checkpointer 列出所有会话（按 logical session_id 去重）
  2. 按 session_id 查找单个会话
  3. 按 session_id 删除所有关联的 thread
  4. 隐藏前缀匹配、run_id 解析、checkpoint 元数据提取等细节

设计决策：
  - 只负责 session 元数据管理，不关心历史消息内容
  - 历史消息由各自的 Agent 服务通过 get_session_history() 接口提供
  - 测试时可以用字典模拟 checkpointer（见 tests/）
"""

import re
from typing import Any, TypedDict

from langgraph.checkpoint.base import BaseCheckpointSaver
from loguru import logger


class SessionInfo(TypedDict):
    """会话信息"""
    session_id: str
    thread_id: str
    mode: str                        # "rag" | "aiops" | "multi"
    run_id: str | None
    updated_at: str


class SessionStore:
    """会话存储深模块

    隐藏 thread-id 前缀约定，提供统一的会话管理接口。
    """

    _PREFIXES = ("rag-", "aiops-", "multi-")

    def __init__(self, checkpointer: BaseCheckpointSaver):
        self._cp = checkpointer

    # ------------------------------------------------------------------
    # 对外接口
    # ------------------------------------------------------------------

    async def list_sessions(self) -> list[SessionInfo]:
        """列出所有会话（按 logical session_id 去重，按时间倒序）"""
        sessions: dict[str, SessionInfo] = {}
        async for checkpoint_tuple in self._cp.alist(None):
            info = self._parse_thread(checkpoint_tuple)
            if info:
                sid = info["session_id"]
                prev = sessions.get(sid)
                if not prev or info["updated_at"] >= prev["updated_at"]:
                    sessions[sid] = info

        return sorted(
            sessions.values(),
            key=lambda item: item.get("updated_at", ""),
            reverse=True,
        )

    async def get_session(self, session_id: str) -> SessionInfo | None:
        """查找指定 session_id 的最新 checkpoint。"""
        best = None
        async for checkpoint_tuple in self._cp.alist(None):
            info = self._parse_thread(checkpoint_tuple)
            if info and info["session_id"] == session_id:
                if not best or info["updated_at"] >= best["updated_at"]:
                    best = info
        return best

    async def delete_session(self, session_id: str) -> bool:
        """删除所有匹配 session_id 的 thread。"""
        deleted = False
        async for checkpoint_tuple in self._cp.alist(None):
            info = self._parse_thread(checkpoint_tuple)
            if info and info["session_id"] == session_id:
                await self._cp.adelete_thread(info["thread_id"])
                logger.info(f"SessionStore: 已删除 thread {info['thread_id']}")
                deleted = True
        return deleted

    async def get_thread_id(self, session_id: str, mode: str) -> str | None:
        """查找指定 session_id + mode 的 thread_id（无 run_id 的简版）。"""
        async for checkpoint_tuple in self._cp.alist(None):
            info = self._parse_thread(checkpoint_tuple)
            if info and info["session_id"] == session_id and info["mode"] == mode:
                return info["thread_id"]
        return None

    # ------------------------------------------------------------------
    # 内部解析
    # ------------------------------------------------------------------

    def _parse_thread(self, checkpoint_tuple: Any) -> SessionInfo | None:
        """将 CheckpointTuple 解析为 SessionInfo。

        Args:
            checkpoint_tuple: cp.alist() 产出的 checkpoint tuple

        Returns:
            SessionInfo | None: 如果 thread_id 格式不匹配则返回 None
        """
        config = checkpoint_tuple.config
        if not config or "configurable" not in config:
            return None
        thread_id = config["configurable"].get("thread_id", "")
        if not thread_id:
            return None

        for prefix in self._PREFIXES:
            if thread_id.startswith(prefix):
                value = thread_id[len(prefix):]
                return self._build_session_info(thread_id, prefix.rstrip("-"), value, checkpoint_tuple)

        return None

    @staticmethod
    def _build_session_info(
        thread_id: str,
        mode: str,
        value: str,
        checkpoint_tuple: Any,
    ) -> SessionInfo:
        """从 thread_id 后缀构建 SessionInfo。

        thread_id 可能有两种格式：
          - {session_id}                    （无 run_id，RAG 模式）
          - {session_id}-{32hex_run_id}     （有 run_id，AIOps/Multi 模式）
        """
        match = re.match(r"^(.*)-([0-9a-f]{32})$", value)
        session_id = match.group(1) if match else value
        run_id = match.group(2) if match else None

        checkpoint = getattr(checkpoint_tuple, "checkpoint", None) or {}
        updated_at = checkpoint.get("ts") or ""

        return SessionInfo(
            session_id=session_id,
            thread_id=thread_id,
            mode=mode,
            run_id=run_id,
            updated_at=updated_at,
        )
