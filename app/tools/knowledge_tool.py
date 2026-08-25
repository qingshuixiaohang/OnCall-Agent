"""知识检索工具 - 从知识库检索相关信息（委托给 RAGPipeline）"""


from langchain_core.documents import Document
from langchain_core.tools import tool
from loguru import logger

from app.config import config
from app.core.observability import observation
from app.services.rag_pipeline import rag_pipeline  # noqa: F401 – 保留导入以确保单例初始化

_FILTER_FIELDS = ("service_name", "environment", "document_type")

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
    """从知识库中检索相关信息来回答问题

    当用户的问题涉及专业知识、文档内容或需要参考资料时，使用此工具。

    检索过程委托给 RAGPipeline：
    1. 向量检索和关键词检索分别召回候选文档
    2. 使用 RRF 合并两路结果
    3. 使用重排模型精排，并过滤低于最低相关性分数的文档

    Args:
        query: 用户的问题或查询
        service_name: 可选，按服务名称过滤，例如 payment-service
        environment: 可选，按环境过滤，例如 prod
        document_type: 可选，按文档类型过滤，例如 runbook

    Returns:
        Tuple[str, List[Document]]: (格式化的上下文文本, 重排后的文档列表)
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


def format_docs(docs: list[Document]) -> str:
    """格式化文档列表为上下文文本（保留供外部使用）。"""
    formatted_parts = []
    for i, doc in enumerate(docs, 1):
        metadata = doc.metadata
        source = metadata.get("_file_name", "未知来源")
        headers = [
            str(metadata[key])
            for key in ("h1", "h2", "h3")
            if metadata.get(key)
        ]
        header_str = " > ".join(headers) if headers else ""
        formatted = f"【参考资料 {i}】"
        if header_str:
            formatted += f"\n标题: {header_str}"
        formatted += f"\n来源: {source}"
        rerank_score = metadata.get("rerank_score")
        if rerank_score is not None:
            relevance = _score_to_label(rerank_score)
            formatted += f"\n相关性: {relevance} ({rerank_score:.4f})"
        formatted += f"\n内容:\n{doc.page_content}\n"
        formatted_parts.append(formatted)
    return "\n".join(formatted_parts)


def _score_to_label(score: float) -> str:
    """将重排分数转换为可读的相关性标签。"""
    if score >= 0.8:
        return "高度相关"
    elif score >= 0.6:
        return "相关"
    elif score >= 0.4:
        return "部分相关"
    else:
        return "低相关"


def _build_milvus_filter(filters: dict[str, str]) -> str | None:
    """构造只允许使用白名单字段的 Milvus JSON 过滤表达式。"""
    expressions = []
    for key, value in filters.items():
        if key not in _FILTER_FIELDS:
            continue
        escaped_value = value.replace("\\", "\\\\").replace('"', '\\"')
        expressions.append(f'metadata["{key}"] == "{escaped_value}"')
    return " and ".join(expressions) if expressions else None


def _document_key(document: Document) -> str:
    metadata = document.metadata
    chunk_id = metadata.get("_chunk_id")
    if chunk_id:
        return str(chunk_id)
    return f"{metadata.get('_source', '')}:{metadata.get('chunk_index', '')}:{document.page_content}"


def _merge_ranked_documents(
    dense_docs: list[Document],
    keyword_docs: list[Document],
) -> list[Document]:
    """使用 RRF 合并两路排名，避免直接相加不同量纲的检索分数。"""
    rrf_constant = 60
    scores: dict[str, float] = {}
    documents: dict[str, Document] = {}

    for rank, document in enumerate(dense_docs, start=1):
        key = _document_key(document)
        scores[key] = scores.get(key, 0.0) + 1 / (rrf_constant + rank)
        documents[key] = document

    for rank, document in enumerate(keyword_docs, start=1):
        key = _document_key(document)
        scores[key] = scores.get(key, 0.0) + 1 / (rrf_constant + rank)
        documents.setdefault(key, document)

    ranked_keys = sorted(scores, key=scores.get, reverse=True)
    ranked_documents = []
    for key in ranked_keys:
        document = documents[key]
        document.metadata["rrf_score"] = scores[key]
        ranked_documents.append(document)
    return ranked_documents


def _apply_rerank_threshold(docs: list[Document]) -> list[Document]:
    """只对已经有重排分数的结果应用阈值。未触发重排时保留原结果。"""
    scored_docs = [doc for doc in docs if doc.metadata.get("rerank_score") is not None]
    if not scored_docs:
        return docs
    return [
        doc
        for doc in docs
        if float(doc.metadata.get("rerank_score", 0.0))
        >= config.rag_min_rerank_score
    ]
