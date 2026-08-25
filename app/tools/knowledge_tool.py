"""知识检索工具 - 从知识库检索相关信息（委托给 RAGPipeline）"""

from langchain_core.documents import Document
from langchain_core.tools import tool
from loguru import logger

from app.core.observability import observation

# 全局 RAGPipeline 单例
_pipeline = None


def _get_pipeline():
    global _pipeline
    if _pipeline is None:
        from app.services.rag_pipeline import RAGPipeline
        _pipeline = RAGPipeline()
    return _pipeline


@tool(response_format="content_and_artifact")
def retrieve_knowledge(
    query: str,
    service_name: str | None = None,
    environment: str | None = None,
    document_type: str | None = None,
) -> tuple[str, list[Document]]:
    """检索运维知识库，并返回上下文和结构化文档结果。"""
    with observation(
        name="rag-retrieval",
        as_type="retriever",
        input_data={
            "query": query,
            "filters": {
                key: value
                for key, value in {
                    "service_name": service_name,
                    "environment": environment,
                    "document_type": document_type,
                }.items()
                if value
            },
        },
    ) as trace:
        result = _retrieve_knowledge_impl(
            query=query,
            service_name=service_name,
            environment=environment,
            document_type=document_type,
        )
        if trace:
            context, docs = result
            trace.update(
                output={
                    "document_count": len(docs),
                    "sources": [
                        doc.metadata.get("_file_name", "unknown")
                        for doc in docs[:10]
                    ],
                    "rerank_scores": [
                        doc.metadata.get("rerank_score", "N/A")
                        for doc in docs[:10]
                    ],
                    "context_length": len(context),
                }
            )
        return result


def _retrieve_knowledge_impl(
    query: str,
    service_name: str | None = None,
    environment: str | None = None,
    document_type: str | None = None,
) -> tuple[str, list[Document]]:
    """从知识库中检索相关信息，委托给 RAGPipeline。

    Args:
        query: 用户的问题或查询
        service_name: 可选，按服务名称过滤
        environment: 可选，按环境过滤
        document_type: 可选，按文档类型过滤

    Returns:
        Tuple[str, List[Document]]: (格式化上下文, 文档列表)
    """
    try:
        logger.info(f"知识检索工具被调用: query='{query}'")

        filters = {
            key: value.strip()
            for key, value in {
                "service_name": service_name,
                "environment": environment,
                "document_type": document_type,
            }.items()
            if value and value.strip()
        }
        if filters:
            logger.info(f"知识检索应用元数据过滤: {filters}")

        pipeline = _get_pipeline()
        context, docs = pipeline.retrieve(query, filters=filters)

        logger.info(
            f"检索完成: 返回 {len(docs)} 篇文档, "
            f"上下文长度: {len(context)} 字符"
        )
        return context, docs

    except Exception as e:
        logger.error(f"知识检索工具调用失败: {e}")
        return f"检索知识时发生错误: {str(e)}", []
