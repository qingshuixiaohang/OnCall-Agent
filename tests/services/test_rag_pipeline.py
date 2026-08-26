"""RAGPipeline 集成测试 - 只测 query() 和 ingest() 对外接口"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.services.rag_pipeline import RAGPipeline


@pytest.fixture
def pipeline():
    """创建一个 RAGPipeline 实例（依赖由各测试按需 mock）"""
    return RAGPipeline()


class TestRAGPipelineQuery:
    """query() 接口的测试套件"""

    def test_query_returns_formatted_context(self, pipeline):
        """正常检索：返回格式化后的上下文文本"""
        mock_doc = MagicMock()
        mock_doc.page_content = "CPU 使用率过高是常见故障"
        mock_doc.metadata = {"_file_name": "runbook.md", "rerank_score": 0.9}

        with patch.object(pipeline, "_vector_search", return_value=[mock_doc]), \
             patch.object(pipeline, "_keyword_search", return_value=[]), \
             patch.object(pipeline, "_rerank", side_effect=lambda q, docs: docs):
            result = pipeline.query("CPU 告警怎么处理", "session-123")

        assert isinstance(result, str)
        assert "CPU 使用率过高" in result
        assert "runbook.md" in result

    def test_query_fallback_to_keyword_when_milvus_down(self, pipeline):
        """Milvus 不可用时：降级到关键词检索"""
        mock_doc = MagicMock()
        mock_doc.page_content = "Redis 连接超时排查"
        mock_doc.metadata = {"_file_name": "redis.md", "rerank_score": 0.8}

        with patch.object(pipeline, "_vector_search", side_effect=RuntimeError("Milvus 连接失败")), \
             patch.object(pipeline, "_keyword_search", return_value=[mock_doc]), \
             patch.object(pipeline, "_rerank", side_effect=lambda q, docs: docs):
            result = pipeline.query("Redis 连接超时", "session-456")

        assert isinstance(result, str)
        assert "Redis 连接超时排查" in result

    def test_retrieve_fallback_when_vector_search_raises_any_exception(self, pipeline):
        """回归保护：_vector_search 抛任何异常时降级到关键词检索，不穿透"""
        mock_doc = MagicMock()
        mock_doc.page_content = "关键词结果"
        mock_doc.metadata = {"_file_name": "k.md", "rerank_score": 0.8}

        with patch.object(pipeline, "_vector_search", side_effect=AttributeError("模拟字段错误")),              patch.object(pipeline, "_keyword_search", return_value=[mock_doc]),              patch.object(pipeline, "_rerank", side_effect=lambda q, docs: docs):
            result = pipeline.query("fault", "s1")

        assert isinstance(result, str)
        assert "关键词结果" in result

    def test_query_skips_rerank_when_disabled(self, pipeline):
        """rerank 关闭时：跳过重排步骤"""
        pipeline.rerank_enabled = False
        mock_doc = MagicMock()
        mock_doc.page_content = "Kafka 消费延迟"
        mock_doc.metadata = {"_file_name": "kafka.md"}

        with patch.object(pipeline, "_vector_search", return_value=[mock_doc]), \
             patch.object(pipeline, "_keyword_search", return_value=[]), \
             patch.object(pipeline, "_rerank") as mock_rerank:
            result = pipeline.query("Kafka 延迟", "session-789")

        mock_rerank.assert_not_called()
        assert "Kafka 消费延迟" in result

    def test_query_delegates_to_real_services(self, pipeline):
        """回归保护：RAGPipeline.query() 通过 page_content 读取检索结果

        从前的实现用 result.content 读取，但 similarity_search 返回
        List[Document]（字段是 page_content），导致每次真实检索都抛
        AttributeError。此测试确保用正确的字段名。
        """
        # similarity_search 返回 List[Document]，正确字段是 page_content 而非 content
        mock_doc = MagicMock()
        mock_doc.page_content = "故障排查手册内容"
        mock_doc.metadata = {"_file_name": "manual.md", "rerank_score": 0.85}

        with patch(
            "app.services.rag_pipeline.vector_store_manager"
        ) as mock_vsm, patch(
            "app.services.rag_pipeline.keyword_index_service"
        ) as mock_kis, patch(
            "app.services.rag_pipeline.rerank_service"
        ) as mock_rs:
            mock_vsm.similarity_search.return_value = [mock_doc]
            mock_kis.search.return_value = []
            mock_rs.rerank.return_value = [mock_doc]

            result = pipeline.query("怎么排查故障", "session-001")

        assert isinstance(result, str)
        assert "故障排查手册内容" in result
        assert "manual.md" in result

    def test_vector_search_reads_document_page_content(self, pipeline):
        """回归保护：_vector_search 直接读 Document.page_content，不抛 AttributeError"""
        # 用真实 langchain Document 而非 MagicMock，确保走真实属性访问路径
        from langchain_core.documents import Document as LCDocument

        real_doc = LCDocument(page_content="真实文档", metadata={"_file_name": "x.md"})

        with patch(
            "app.services.rag_pipeline.vector_store_manager.similarity_search",
            return_value=[real_doc],
        ):
            docs = pipeline._vector_search("fault")

        assert len(docs) == 1
        assert docs[0].page_content == "真实文档"


class TestRAGPipelineIngest:
    """ingest() 接口的测试套件"""

    def test_ingest_returns_metadata(self, pipeline, tmp_path):
        """正常入库：返回包含文件路径、分片数、文档 ID 的结果"""
        target = tmp_path / "test.md"
        target.write_text("# title\ncontent", encoding="utf-8")

        mock_doc = MagicMock()
        mock_doc.metadata = {}

        with patch(
            "app.services.rag_pipeline.document_splitter_service"
        ) as mock_splitter, patch(
            "app.services.rag_pipeline.vector_store_manager"
        ) as mock_vsm, patch(
            "app.services.rag_pipeline.keyword_index_service"
        ) as mock_kis:
            mock_splitter.extract_text.return_value = "# 文档标题\n内容"
            mock_splitter.split_document.return_value = [mock_doc, mock_doc]
            mock_vsm.delete_by_source.return_value = 0
            mock_kis.delete_by_source.return_value = 0
            mock_vsm.add_documents.return_value = ["id-1", "id-2"]

            result = pipeline.ingest(str(target))

        assert result["file_path"] == str(target)
        assert result["chunk_count"] == 2
        assert len(result["document_ids"]) == 2

    def test_ingest_deletes_old_data_before_indexing(self, pipeline, tmp_path):
        """入库前先删除该文件的旧索引数据"""
        target = tmp_path / "old.md"
        target.write_text("content", encoding="utf-8")

        mock_doc = MagicMock()
        mock_doc.metadata = {}

        with patch(
            "app.services.rag_pipeline.document_splitter_service"
        ) as mock_splitter, patch(
            "app.services.rag_pipeline.vector_store_manager"
        ) as mock_vsm, patch(
            "app.services.rag_pipeline.keyword_index_service"
        ) as mock_kis:
            mock_splitter.extract_text.return_value = "内容"
            mock_splitter.split_document.return_value = [mock_doc]
            mock_vsm.delete_by_source.return_value = 3
            mock_kis.delete_by_source.return_value = 0
            mock_vsm.add_documents.return_value = ["id-1"]

            result = pipeline.ingest(str(target))

        expected = Path(str(target)).resolve().as_posix()
        mock_vsm.delete_by_source.assert_called_once_with(expected)
        mock_kis.delete_by_source.assert_called_once_with(expected)
        assert result["deleted_count"] == 3

    def test_ingest_updates_vector_and_keyword_index(self, pipeline, tmp_path):
        """同时更新向量索引和关键词索引"""
        target = tmp_path / "doc.md"
        target.write_text("content", encoding="utf-8")

        mock_doc = MagicMock()
        mock_doc.metadata = {}

        with patch(
            "app.services.rag_pipeline.document_splitter_service"
        ) as mock_splitter, patch(
            "app.services.rag_pipeline.vector_store_manager"
        ) as mock_vsm, patch(
            "app.services.rag_pipeline.keyword_index_service"
        ) as mock_kis:
            mock_splitter.extract_text.return_value = "内容"
            mock_splitter.split_document.return_value = [mock_doc]
            mock_vsm.delete_by_source.return_value = 0
            mock_kis.delete_by_source.return_value = 0
            mock_vsm.add_documents.return_value = ["id-1"]

            pipeline.ingest(str(target))

        mock_vsm.add_documents.assert_called_once()
        mock_kis.upsert_documents.assert_called_once_with(["id-1"], [mock_doc])

    def test_ingest_then_query_retrieves_ingested_content(self, pipeline, tmp_path):
        """ingest 后 query 能检索到刚入库的内容"""
        target = tmp_path / "new.md"
        target.write_text("ingested content", encoding="utf-8")

        ingested_doc = MagicMock()
        ingested_doc.page_content = "ingested content"
        ingested_doc.metadata = {"_file_name": "new.md", "rerank_score": 0.9}

        with patch(
            "app.services.rag_pipeline.document_splitter_service"
        ) as mock_splitter, patch(
            "app.services.rag_pipeline.vector_store_manager"
        ) as mock_vsm, patch(
            "app.services.rag_pipeline.keyword_index_service"
        ) as mock_kis, patch(
            "app.services.rag_pipeline.rerank_service"
        ) as mock_rs:
            # ingest 阶段
            mock_splitter.extract_text.return_value = "ingested content"
            mock_splitter.split_document.return_value = [ingested_doc]
            mock_vsm.delete_by_source.return_value = 0
            mock_kis.delete_by_source.return_value = 0
            mock_vsm.add_documents.return_value = ["id-1"]
            pipeline.ingest(str(target))

            # query 阶段：模拟检索到刚入库的文档（注意 similarity_search 返回 Document，用 page_content）
            mock_vsm.similarity_search.return_value = [
                MagicMock(page_content="ingested content", metadata={"_file_name": "new.md"})
            ]
            mock_kis.search.return_value = []
            mock_rs.rerank.return_value = [
                MagicMock(page_content="ingested content", metadata={"_file_name": "new.md", "rerank_score": 0.9})
            ]

            result = pipeline.query("ingested content", "session-ingest")

        assert "ingested content" in result
        assert "new.md" in result
