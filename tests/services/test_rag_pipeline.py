"""RAGPipeline 集成测试 - 只测 query() 和 ingest() 对外接口"""

from unittest.mock import MagicMock, patch

import pytest

from app.services.rag_pipeline import RAGPipeline


@pytest.fixture
def pipeline():
    """创建一个 RAGPipeline 实例（依赖由各测试按需 mock）"""
    return RAGPipeline()


class TestRAGPipelineQuery:
    """query() 接口的测试套件"""

    async def test_query_returns_formatted_context(self, pipeline):
        """正常检索：返回格式化后的上下文文本"""
        mock_doc = MagicMock()
        mock_doc.page_content = "CPU 使用率过高是常见故障"
        mock_doc.metadata = {"_file_name": "runbook.md", "rerank_score": 0.9}

        with patch.object(pipeline, "_vector_search", return_value=[mock_doc]), \
             patch.object(pipeline, "_keyword_search", return_value=[]), \
             patch.object(pipeline, "_rerank", side_effect=lambda q, docs: docs):
            result = await pipeline.query("CPU 告警怎么处理", "session-123")

        assert isinstance(result, str)
        assert "CPU 使用率过高" in result
        assert "runbook.md" in result

    async def test_query_fallback_to_keyword_when_milvus_down(self, pipeline):
        """Milvus 不可用时：降级到关键词检索"""
        mock_doc = MagicMock()
        mock_doc.page_content = "Redis 连接超时排查"
        mock_doc.metadata = {"_file_name": "redis.md", "rerank_score": 0.8}

        with patch.object(pipeline, "_vector_search", side_effect=RuntimeError("Milvus 连接失败")), \
             patch.object(pipeline, "_keyword_search", return_value=[mock_doc]), \
             patch.object(pipeline, "_rerank", side_effect=lambda q, docs: docs):
            result = await pipeline.query("Redis 连接超时", "session-456")

        assert isinstance(result, str)
        assert "Redis 连接超时排查" in result

    async def test_query_skips_rerank_when_disabled(self, pipeline):
        """rerank 关闭时：跳过重排步骤"""
        pipeline.rerank_enabled = False
        mock_doc = MagicMock()
        mock_doc.page_content = "Kafka 消费延迟"
        mock_doc.metadata = {"_file_name": "kafka.md"}

        with patch.object(pipeline, "_vector_search", return_value=[mock_doc]), \
             patch.object(pipeline, "_keyword_search", return_value=[]), \
             patch.object(pipeline, "_rerank") as mock_rerank:
            result = await pipeline.query("Kafka 延迟", "session-789")

        mock_rerank.assert_not_called()
        assert "Kafka 消费延迟" in result

    async def test_query_delegates_to_real_services(self, pipeline):
        """集成 seam：RAGPipeline.query() 通过真实服务模块检索"""
        # similarity_search 返回 List[SearchResult]，SearchResult 有 .content 和 .metadata
        mock_search_result = MagicMock()
        mock_search_result.content = "故障排查手册内容"
        mock_search_result.metadata = {"_file_name": "manual.md"}

        # search 和 rerank 返回 List[Document]
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
            mock_vsm.similarity_search.return_value = [mock_search_result]
            mock_kis.search.return_value = []
            mock_rs.rerank.return_value = [mock_doc]

            result = await pipeline.query("怎么排查故障", "session-001")

        assert isinstance(result, str)
        assert "故障排查手册内容" in result
        assert "manual.md" in result
