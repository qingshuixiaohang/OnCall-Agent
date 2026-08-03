"""知识检索工具 - 从向量数据库中检索相关信息

检索流程（两阶段）：
1. 粗排（向量检索）：使用 Milvus 向量相似度召回 rag_retrieval_k 篇候选文档
2. 精排（语义重排）：使用阿里云百炼重排模型筛选出最相关的 rag_top_k 篇文档

这样做的优势：
- 向量检索速度快但语义理解有限，多召回一些候选
- 重排模型精度高，能准确判断文档与查询的相关性
- 最终返回给 LLM 的文档质量显著提升
"""

from typing import Dict, List, Optional, Tuple

from langchain_core.documents import Document
from langchain_core.tools import tool
from loguru import logger

from app.config import config
from app.services.keyword_index_service import keyword_index_service
from app.services.rerank_service import rerank_service
from app.services.vector_store_manager import vector_store_manager

_FILTER_FIELDS = ("service_name", "environment", "document_type")


@tool(response_format="content_and_artifact")
def retrieve_knowledge(
    query: str,
    service_name: Optional[str] = None,
    environment: Optional[str] = None,
    document_type: Optional[str] = None,
) -> Tuple[str, List[Document]]:
    """从知识库中检索相关信息来回答问题

    当用户的问题涉及专业知识、文档内容或需要参考资料时，使用此工具。

    检索过程：
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
        filter_expr = _build_milvus_filter(filters)
        if filters:
            logger.info(f"知识检索应用元数据过滤: {filters}")

        # ========== 阶段1: 粗排（向量检索多召回） ==========
        retrieval_k = config.rag_retrieval_k
        logger.info(f"阶段1 粗排: 向量检索召回 top-{retrieval_k} 篇候选文档")
        dense_docs = vector_store_manager.similarity_search(
            query,
            k=retrieval_k,
            expr=filter_expr,
        )
        logger.info(f"向量召回完成: {len(dense_docs)} 篇")

        keyword_docs: List[Document] = []
        if config.rag_hybrid_enabled:
            keyword_docs = keyword_index_service.search(
                query=query,
                k=config.rag_keyword_k,
                filters=filters,
            )

        docs = _merge_ranked_documents(dense_docs, keyword_docs)
        if not docs:
            logger.warning("未检索到相关文档")
            return "没有找到相关信息。", []

        logger.info(
            f"阶段1 完成: 向量={len(dense_docs)} 篇, "
            f"关键词={len(keyword_docs)} 篇, 合并去重={len(docs)} 篇"
        )

        # ========== 阶段2: 精排（重排模型筛选） ==========
        top_k = config.rag_top_k
        if len(docs) > top_k:
            logger.info(f"阶段2 精排: 使用重排模型从 {len(docs)} 篇中筛选 top-{top_k}")
            try:
                docs = rerank_service.rerank(query, docs)
                logger.info(
                    f"阶段2 完成: 精排后保留 {len(docs)} 篇, "
                    f"分数: {[d.metadata.get('rerank_score', 'N/A') for d in docs]}"
                )
            except Exception as e:
                # 不降级：重排失败直接抛出
                logger.error(f"重排失败，终止检索: {e}")
                raise RuntimeError(
                    f"文档重排失败: {e}\n"
                    f"请检查 DASHSCOPE_API_KEY 配置和重排模型 {config.rerank_model} 是否可用。"
                ) from e
        else:
            logger.info(
                f"候选文档数({len(docs)}) <= top_k({top_k})，跳过重排直接返回"
            )

        docs = _apply_rerank_threshold(docs)
        if not docs:
            logger.info(
                f"所有候选文档的重排分数低于阈值 {config.rag_min_rerank_score}"
            )
            return "没有找到足够相关的知识信息。", []

        # ========== 格式化文档为上下文 ==========
        context = format_docs(docs)

        logger.info(
            f"检索完成: 最终返回 {len(docs)} 篇文档, "
            f"上下文长度: {len(context)} 字符"
        )
        return context, docs

    except RuntimeError:
        # 重排失败（已知错误），直接向上传播
        raise

    except Exception as e:
        logger.error(f"知识检索工具调用失败: {e}")
        return f"检索知识时发生错误: {str(e)}", []


def format_docs(docs: List[Document]) -> str:
    """
    格式化文档列表为上下文文本

    Args:
        docs: 文档列表

    Returns:
        str: 格式化的上下文文本
    """
    formatted_parts = []

    for i, doc in enumerate(docs, 1):
        # 提取元数据
        metadata = doc.metadata
        source = metadata.get("_file_name", "未知来源")

        # 提取标题信息 (如果有)
        headers = []
        for key in ["h1", "h2", "h3"]:
            if key in metadata and metadata[key]:
                headers.append(metadata[key])

        header_str = " > ".join(headers) if headers else ""

        # 构建格式化文本
        formatted = f"【参考资料 {i}】"
        if header_str:
            formatted += f"\n标题: {header_str}"
        formatted += f"\n来源: {source}"

        # 如果有重排分数，添加相关性标注（便于 LLM 判断文档价值）
        rerank_score = metadata.get("rerank_score")
        if rerank_score is not None:
            relevance = _score_to_label(rerank_score)
            formatted += f"\n相关性: {relevance} ({rerank_score:.4f})"

        formatted += f"\n内容:\n{doc.page_content}\n"

        formatted_parts.append(formatted)

    return "\n".join(formatted_parts)


def _score_to_label(score: float) -> str:
    """将重排分数转换为可读的相关性标签

    Args:
        score: 重排分数 (0.0 ~ 1.0)

    Returns:
        str: 相关性标签
    """
    if score >= 0.8:
        return "高度相关"
    elif score >= 0.6:
        return "相关"
    elif score >= 0.4:
        return "部分相关"
    else:
        return "低相关"


def _build_milvus_filter(filters: Dict[str, str]) -> Optional[str]:
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
    dense_docs: List[Document],
    keyword_docs: List[Document],
) -> List[Document]:
    """使用 RRF 合并两路排名，避免直接相加不同量纲的检索分数。"""
    rrf_constant = 60
    scores: Dict[str, float] = {}
    documents: Dict[str, Document] = {}

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


def _apply_rerank_threshold(docs: List[Document]) -> List[Document]:
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
