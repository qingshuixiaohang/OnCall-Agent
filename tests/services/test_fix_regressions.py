"""RAGPipeline / file API 修复回归测试

覆盖两个已修复的"必炸"bug：
1. rag_pipeline._vector_search 用 r.content → 应 r.page_content
2. file.index_directory 用 result.success/result.to_dict() → 应 result["success"] / result
"""

import tempfile
from pathlib import Path
from unittest.mock import patch

from app.services.rag_pipeline import RAGPipeline


class TestVectorSearchRegression:
    """Bug 1 回归：_vector_search 读取真实 Document 不抛 AttributeError"""

    def test_page_content_used_not_content(self):
        """相似性搜索返回的 Document 用 .page_content 读取"""
        # 显式验证 pipeline 源码用的是 page_content（防止未来回退）
        import inspect
        src = inspect.getsource(RAGPipeline._vector_search)
        assert "page_content=" in src
        assert "r.content" not in src

    def test_real_document_does_not_crash(self):
        """用真实 langchain Document 驱动 _vector_search，验证不抛错"""
        from langchain_core.documents import Document as LCDocument
        pipeline = RAGPipeline()
        real_doc = LCDocument(page_content="真实内容", metadata={"_file_name": "a.md"})
        with patch(
            "app.services.rag_pipeline.vector_store_manager.similarity_search",
            return_value=[real_doc],
        ):
            docs = pipeline._vector_search("q")
        assert docs[0].page_content == "真实内容"


class TestIndexDirectoryRegression:
    """Bug 2 回归：/api/index_directory 对 dict 正确索引，不抛 AttributeError"""

    def test_index_directory_returns_proper_json(self):
        """索引成功返回结构正确的 JSON（真正 await 端点并断言内容）"""
        import asyncio
        import json

        from app.api.file import index_directory

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            (target / "a.md").write_text("# a", encoding="utf-8")

            # mock ingest，避免真实 Milvus/递归依赖
            with patch(
                "app.api.file.RAGPipeline"
            ) as MockPipeline:
                instance = MockPipeline.return_value
                instance.ingest.return_value = {
                    "file_path": str(target / "a.md"),
                    "chunk_count": 1,
                    "document_ids": ["id1"],
                    "deleted_count": 0,
                }
                # async 端点必须显式执行，否则协程不会运行、断言形同虚设
                resp = asyncio.run(index_directory(directory_path=str(target)))
                payload = json.loads(resp.body.decode("utf-8"))
                assert payload["code"] == 200
                assert payload["message"] == "success"
                assert payload["data"]["success_count"] == 1

    def test_dict_access_pattern(self):
        """回归保护：验证 file.py 使用 result['success'] 而非 result.success"""
        import inspect

        from app.api import file as file_module
        src = inspect.getsource(file_module)
        assert "result[\"success\"]" in src
        assert "result.success" not in src
        assert "result.to_dict()" not in src
