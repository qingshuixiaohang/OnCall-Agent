"""KnowledgePrefetcher 预取判定测试

重点测 _should_prefetch 的关键词判定 + prefetch 的状态机，
不依赖真实知识库检索（mock retrieve_knowledge）。
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.core.knowledge_prefetcher import KnowledgePrefetcher


@pytest.fixture
def prefetcher():
    return KnowledgePrefetcher()


class TestShouldPrefetch:
    """预取判定逻辑"""

    def test_trivial_query_skipped(self, prefetcher: KnowledgePrefetcher):
        assert not prefetcher._should_prefetch("你好")
        assert not prefetcher._should_prefetch("hi")
        assert not prefetcher._should_prefetch("谢谢")
        assert not prefetcher._should_prefetch("")

    def test_too_short_skipped(self, prefetcher: KnowledgePrefetcher):
        # 少于 6 字符且无关键词
        assert not prefetcher._should_prefetch("abc")

    def test_keyword_triggers(self, prefetcher: KnowledgePrefetcher):
        assert prefetcher._should_prefetch("CPU 使用率过高怎么排查")
        assert prefetcher._should_prefetch("redis 连接超时故障")
        assert prefetcher._should_prefetch("数据库报错如何处理")

    def test_no_keyword_skipped(self, prefetcher: KnowledgePrefetcher):
        # 长但无运维关键词
        assert not prefetcher._should_prefetch("今天天气真不错啊哈哈哈")


class TestPrefetchStateMachine:
    """prefetch 状态机：skipped / found / empty / error"""

    async def test_skipped_for_trivial(self, prefetcher: KnowledgePrefetcher):
        _, _, prefetched, state = await prefetcher.prefetch("你好")
        assert state == "skipped"
        assert prefetched is False

    async def test_found(self, prefetcher: KnowledgePrefetcher):
        from unittest.mock import MagicMock

        from langchain_core.documents import Document

        docs = [Document(page_content="fault manual", metadata={"_file_name": "m.md"})]
        from app.core import knowledge_prefetcher as kp
        mock_tool = MagicMock()
        mock_tool.ainvoke = AsyncMock(return_value=("fault manual", docs))
        with patch.object(kp, "retrieve_knowledge", new=mock_tool):
            _, sources, prefetched, state = await prefetcher.prefetch("CPU fault troubleshoot")
        assert state == "found"
        assert prefetched is True
        assert len(sources) == 1

    async def test_empty_when_no_docs(self, prefetcher: KnowledgePrefetcher):
        from unittest.mock import MagicMock

        from app.core import knowledge_prefetcher as kp
        mock_tool = MagicMock()
        mock_tool.ainvoke = AsyncMock(return_value=("", []))
        with patch.object(kp, "retrieve_knowledge", new=mock_tool):
            _, _, prefetched, state = await prefetcher.prefetch("CPU fault troubleshoot")
        assert state == "empty"
        assert prefetched is False

    async def test_error_on_exception(self, prefetcher: KnowledgePrefetcher):
        from unittest.mock import MagicMock

        from app.core import knowledge_prefetcher as kp
        mock_tool = MagicMock()
        mock_tool.ainvoke = AsyncMock(side_effect=RuntimeError("boom"))
        with patch.object(kp, "retrieve_knowledge", new=mock_tool):
            _, _, prefetched, state = await prefetcher.prefetch("CPU fault troubleshoot")
        assert state == "error"
        assert prefetched is False
