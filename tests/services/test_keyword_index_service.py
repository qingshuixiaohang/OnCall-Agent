"""KeywordIndexService 单元测试 - 纯本地 SQLite FTS5，无外部依赖"""

import pytest
from langchain_core.documents import Document

from app.services.keyword_index_service import KeywordIndexService


@pytest.fixture
def index(tmp_path):
    """创建基于临时 SQLite 的 KeywordIndexService 实例"""
    service = KeywordIndexService(str(tmp_path / "test.db"))
    return service


def _doc(content: str, source: str, **meta) -> Document:
    metadata = {"_source": source, **meta}
    return Document(page_content=content, metadata=metadata)


class TestTokenizer:
    """分词逻辑"""

    def test_keeps_english_identifiers(self):
        tokens = KeywordIndexService._tokenize("payment-service 下单失败")
        assert "payment-service" in tokens

    def test_splits_chinese_bigrams(self):
        tokens = KeywordIndexService._tokenize("下单失败")
        assert "下单" in tokens or "单失" in tokens or "失败" in tokens

    def test_lowercases(self):
        tokens = KeywordIndexService._tokenize("ERROR")
        assert "error" in tokens

    def test_empty_input(self):
        assert KeywordIndexService._tokenize("") == []

    def test_deduplicates(self):
        tokens = KeywordIndexService._tokenize("error ERROR Error")
        assert tokens.count("error") == 1


class TestUpsertAndSearch:
    """入库与检索"""

    def test_upsert_then_search_finds_match(self, index):
        index.upsert_documents(["1"], [_doc("payment服务CPU告警", "a.md")])
        results = index.search("payment", k=5)
        assert len(results) == 1

    def test_search_returns_document_content(self, index):
        index.upsert_documents(["1"], [_doc("Redis连接超时排查", "redis.md")])
        results = index.search("Redis", k=5)
        assert results[0].page_content == "Redis连接超时排查"

    def test_search_no_match_returns_empty(self, index):
        index.upsert_documents(["1"], [_doc("payment服务", "a.md")])
        results = index.search("完全无关的词", k=5)
        assert results == []

    def test_search_respects_top_k(self, index):
        docs = [_doc(f"service {i} error", f"{i}.md") for i in range(5)]
        index.upsert_documents([str(i) for i in range(5)], docs)
        results = index.search("error", k=3)
        assert len(results) <= 3

    def test_search_with_service_filter(self, index):
        index.upsert_documents(
            ["1", "2"],
            [_doc("payment error", "a.md", service_name="pay"),
             _doc("order error", "b.md", service_name="order")],
        )
        results = index.search("error", k=5, filters={"service_name": "pay"})
        assert len(results) == 1
        assert results[0].metadata.get("service_name") == "pay"


class TestDelete:
    """删除逻辑"""

    def test_delete_by_source_removes_docs(self, index):
        index.upsert_documents(["1", "2"], [_doc("a error", "a.md"), _doc("b error", "b.md")])
        deleted = index.delete_by_source("a.md")
        assert deleted >= 1
        results = index.search("error", k=5)
        assert all(r.metadata.get("_source") != "a.md" for r in results)

    def test_delete_nonexistent_source_returns_zero(self, index):
        deleted = index.delete_by_source("nonexistent.md")
        assert deleted == 0

    def test_reupsert_overwrites_old(self, index):
        index.upsert_documents(["1"], [_doc("old content", "a.md")])
        index.upsert_documents(["1"], [_doc("new content", "a.md")])
        results = index.search("new content", k=5)
        assert len(results) == 1
