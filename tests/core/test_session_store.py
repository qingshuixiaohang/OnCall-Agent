"""SessionStore 测试

使用内存字典模拟 checkpointer，实现 seam 测试。
"""

from typing import Any

import pytest

from app.core.session_store import SessionStore

# ============================================================================
# Mock Checkpointer
# ============================================================================

class MockCheckpoint(dict):
    """模拟 LangGraph Checkpoint 的 ts 字段"""

    def __init__(self, ts: str = ""):
        super().__init__()
        self.ts = ts

    def __bool__(self) -> bool:
        return True

    def get(self, key: str, default: str = "") -> str:
        if key == "ts":
            return self.ts
        return default


class MockConfig(dict):
    """模拟 config 字典"""

    def __init__(self, configurable: dict[str, Any]):
        super().__init__(configurable)
        self.configurable = configurable


class MockCheckpointTuple:
    """模拟 cp.alist() 返回的 CheckpointTuple"""

    def __init__(self, thread_id: str, ts: str = ""):
        self.config = MockConfig({"configurable": {"thread_id": thread_id}})
        self.checkpoint = MockCheckpoint(ts=ts)


class MockCheckpointer:
    """内存字典实现的 checkpointer，替代 BaseCheckpointSaver

    用于测试 SessionStore 的解析逻辑：
    - _threads: dict[thread_id, CheckpointTuple]
    - alist(): 异步迭代所有线程
    - adelete_thread(thread_id): 删除指定线程
    """

    def __init__(self):
        self._threads: dict[str, MockCheckpointTuple] = {}

    def add(self, thread_id: str, ts: str = ""):
        self._threads[thread_id] = MockCheckpointTuple(thread_id=thread_id, ts=ts)

    async def alist(self, after: Any = None, limit: int | None = None):
        """模拟异步迭代器"""
        items = list(self._threads.values())
        if limit:
            items = items[:limit]
        for item in items:
            yield item

    async def adelete_thread(self, thread_id: str):
        self._threads.pop(thread_id, None)


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def store():
    return SessionStore(MockCheckpointer())


def _populate(store: SessionStore, threads: dict[str, str]):
    """向底层 mock checkpointer 添加测试数据"""
    cp: MockCheckpointer = store._cp  # type: ignore
    for thread_id, ts in threads.items():
        cp.add(thread_id, ts)


# ============================================================================
# Tests
# ============================================================================

class TestParseThread:
    """验证 thread_id 解析逻辑"""

    async def test_rag_session(self, store: SessionStore):
        """rag-{session_id} 格式"""
        _populate(store, {"rag-test-123": "2026-01-01T00:00:00Z"})
        sessions = await store.list_sessions()
        assert len(sessions) == 1
        assert sessions[0]["session_id"] == "test-123"
        assert sessions[0]["mode"] == "rag"
        assert sessions[0]["run_id"] is None

    async def test_aiops_with_run_id(self, store: SessionStore):
        """aiops-{session_id}-{32hex_run_id} 格式"""
        run_id = "a" * 32
        _populate(store, {f"aiops-session-X-{run_id}": "2026-01-01T00:00:00Z"})
        sessions = await store.list_sessions()
        assert len(sessions) == 1
        assert sessions[0]["session_id"] == "session-X"
        assert sessions[0]["mode"] == "aiops"
        assert sessions[0]["run_id"] == run_id

    async def test_multi_with_run_id(self, store: SessionStore):
        """multi-{session_id}-{32hex_run_id} 格式"""
        run_id = "b" * 32
        _populate(store, {f"multi-incident-42-{run_id}": "2026-01-01T00:00:00Z"})
        sessions = await store.list_sessions()
        assert len(sessions) == 1
        assert sessions[0]["session_id"] == "incident-42"
        assert sessions[0]["mode"] == "multi"
        assert sessions[0]["run_id"] == run_id

    async def test_unknown_prefix_ignored(self, store: SessionStore):
        """未知前缀的 thread_id 应该被忽略"""
        _populate(store, {"unknown-foo": "2026-01-01T00:00:00Z"})
        sessions = await store.list_sessions()
        assert len(sessions) == 0

    async def test_empty_thread_id_ignored(self, store: SessionStore):
        """空 thread_id 应该被忽略"""
        cp: MockCheckpointer = store._cp  # type: ignore
        # 添加一个没有 configurable 的 thread
        class MissingConfig(dict):
            pass
        cp._threads["empty"] = MockCheckpointTuple("rag-x")  # type: ignore
        cp._threads["empty"].config = MissingConfig()  # type: ignore
        sessions = await store.list_sessions()
        assert len(sessions) == 0


class TestListSessions:
    """会话列表去重与排序"""

    async def test_dedup_by_session_id(self, store: SessionStore):
        """同一 session_id 只保留最新 thread"""
        _populate(store, {
            "rag-chat-1": "2026-01-01T00:00:00Z",
        })
        sessions = await store.list_sessions()
        assert len(sessions) == 1
        assert sessions[0]["session_id"] == "chat-1"

    async def test_multiple_sessions_sorted_by_time(self, store: SessionStore):
        """多个会话按更新时间倒序排列"""
        _populate(store, {
            "rag-old": "2026-01-01T00:00:00Z",
            "rag-new": "2026-01-02T00:00:00Z",
            "rag-mid": "2026-01-01T12:00:00Z",
        })
        sessions = await store.list_sessions()
        assert len(sessions) == 3
        # 应该按 updated_at 降序
        assert sessions[0]["session_id"] == "new"
        assert sessions[1]["session_id"] == "mid"
        assert sessions[2]["session_id"] == "old"

    async def test_mixed_modes(self, store: SessionStore):
        """不同模式的会话混合列出"""
        _populate(store, {
            "rag-default": "2026-01-01T00:00:00Z",
            f"aiops-incident-{'a'*32}": "2026-01-02T00:00:00Z",
            "multi-alert": "2026-01-03T00:00:00Z",  # without run_id (unusual but valid)
        })
        sessions = await store.list_sessions()
        assert len(sessions) == 3
        modes = {s["mode"] for s in sessions}
        assert modes == {"rag", "aiops", "multi"}


class TestGetSession:
    """按 session_id 查找"""

    async def test_found(self, store: SessionStore):
        _populate(store, {"rag-s1": "2026-01-01T00:00:00Z"})
        info = await store.get_session("s1")
        assert info is not None
        assert info["session_id"] == "s1"

    async def test_not_found(self, store: SessionStore):
        _populate(store, {"rag-s1": "2026-01-01T00:00:00Z"})
        info = await store.get_session("nonexistent")
        assert info is None

    async def test_get_latest(self, store: SessionStore):
        """同一 session_id 有多个 run 时，应该返回最新的"""
        _populate(store, {
            f"aiops-s1-{'a'*32}": "2026-01-01T00:00:00Z",
            f"aiops-s1-{'b'*32}": "2026-01-02T00:00:00Z",
        })
        info = await store.get_session("s1")
        assert info is not None
        assert info["run_id"] == "b" * 32


class TestDeleteSession:
    """按 session_id 删除"""

    async def test_delete_all_runs(self, store: SessionStore):
        """删除应该清除所有关联的 thread（包括不同 run_id）"""
        _populate(store, {
            f"aiops-incident-{'a'*32}": "2026-01-01T00:00:00Z",
            f"aiops-incident-{'b'*32}": "2026-01-02T00:00:00Z",
            "rag-other": "2026-01-03T00:00:00Z",
        })
        deleted = await store.delete_session("incident")
        assert deleted is True
        remaining = await store.list_sessions()
        assert len(remaining) == 1
        assert remaining[0]["session_id"] == "other"

    async def test_delete_nonexistent(self, store: SessionStore):
        _populate(store, {"rag-s1": "2026-01-01T00:00:00Z"})
        deleted = await store.delete_session("nonexistent")
        assert deleted is False


class TestGetThreadId:
    """按 session_id + mode 查找 thread_id"""

    async def test_found(self, store: SessionStore):
        _populate(store, {"rag-s1": "2026-01-01T00:00:00Z"})
        tid = await store.get_thread_id("s1", "rag")
        assert tid == "rag-s1"

    async def test_mode_mismatch(self, store: SessionStore):
        _populate(store, {"rag-s1": "2026-01-01T00:00:00Z"})
        tid = await store.get_thread_id("s1", "aiops")
        assert tid is None
