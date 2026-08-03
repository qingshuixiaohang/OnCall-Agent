"""RAG 评测共用的数据加载、检索调用和指标计算逻辑。"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from langchain_core.documents import Document

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@dataclass(frozen=True)
class EvalCase:
    id: str
    category: str
    question_type: str
    difficulty: str
    answerable: bool
    safety_level: str
    question: str
    expected_sources: list[str]
    reference_answer: str
    service_name: str | None = None
    environment: str | None = None
    document_type: str | None = None


@dataclass(frozen=True)
class RetrievalCaseResult:
    id: str
    category: str
    question_type: str
    difficulty: str
    answerable: bool
    safety_level: str
    question: str
    expected_sources: list[str]
    retrieved_sources: list[str]
    hit: bool
    recall: float | None
    precision: float | None
    reciprocal_rank: float | None
    retrieved_empty: bool
    error: str | None
    documents: list[dict[str, Any]]


def load_cases(path: Path | None = None) -> list[EvalCase]:
    dataset_path = path or Path(__file__).with_name("dataset.jsonl")
    cases: list[EvalCase] = []
    for line_number, line in enumerate(
        dataset_path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
            required_fields = (
                "id",
                "category",
                "question_type",
                "difficulty",
                "answerable",
                "safety_level",
                "question",
                "expected_sources",
                "reference_answer",
            )
            missing_fields = [field for field in required_fields if field not in item]
            if missing_fields:
                raise ValueError(f"缺少字段: {', '.join(missing_fields)}")
            if not isinstance(item["answerable"], bool):
                raise ValueError("answerable 必须是布尔值")
            if not isinstance(item["expected_sources"], list):
                raise ValueError("expected_sources 必须是数组")
            cases.append(
                EvalCase(
                    id=str(item["id"]),
                    category=str(item["category"]),
                    question_type=str(item["question_type"]),
                    difficulty=str(item["difficulty"]),
                    answerable=item["answerable"],
                    safety_level=str(item["safety_level"]),
                    question=str(item["question"]),
                    expected_sources=[str(source) for source in item["expected_sources"]],
                    reference_answer=str(item["reference_answer"]),
                    service_name=item.get("service_name"),
                    environment=item.get("environment"),
                    document_type=item.get("document_type"),
                )
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise ValueError(f"评测数据第 {line_number} 行格式错误: {error}") from error
    if not cases:
        raise ValueError(f"评测数据为空: {dataset_path}")
    return cases


def normalize_tool_result(result: Any) -> tuple[str, list[Document]]:
    """兼容 LangChain content_and_artifact 工具的 tuple、字符串和列表返回值。"""
    if isinstance(result, tuple) and len(result) == 2:
        content, artifact = result
        content_text = str(content or "")
        documents = normalize_documents(artifact)
        return content_text, documents or documents_from_context(content_text)
    if isinstance(result, str):
        return result, documents_from_context(result)
    if isinstance(result, list):
        return "", normalize_documents(result)
    if isinstance(result, dict):
        content = result.get("content", result.get("text", ""))
        artifact = result.get("artifact", result.get("documents", []))
        return str(content or ""), normalize_documents(artifact)
    return str(result or ""), []


def documents_from_context(context: str) -> list[Document]:
    """从 retrieve_knowledge 的格式化文本中恢复来源，兼容直接 Tool.invoke。"""
    if "【参考资料" not in context:
        return []
    documents: list[Document] = []
    sections = re.split(r"(?=【参考资料\s*\d+】)", context)
    for section in sections:
        if "来源:" not in section or "内容:" not in section:
            continue
        source_match = re.search(r"来源:\s*(.+)", section)
        content_marker = "内容:\n"
        content_start = section.find(content_marker)
        if not source_match or content_start < 0:
            continue
        content = section[content_start + len(content_marker) :].strip()
        metadata: dict[str, Any] = {"_file_name": source_match.group(1).strip()}
        score_match = re.search(r"相关性:.*?\(([0-9.]+)\)", section)
        if score_match:
            metadata["rerank_score"] = float(score_match.group(1))
        documents.append(Document(page_content=content, metadata=metadata))
    return documents


def normalize_documents(value: Any) -> list[Document]:
    if value is None:
        return []
    if isinstance(value, Document):
        return [value]
    if not isinstance(value, list):
        return []
    documents: list[Document] = []
    for item in value:
        if isinstance(item, Document):
            documents.append(item)
        elif isinstance(item, dict):
            documents.append(
                Document(
                    page_content=str(item.get("page_content", item.get("content", ""))),
                    metadata=dict(item.get("metadata", {})),
                )
            )
    return documents


def invoke_retriever(case: EvalCase) -> tuple[str, list[Document]]:
    from app.tools.knowledge_tool import retrieve_knowledge

    result = retrieve_knowledge.invoke(
        {
            "query": case.question,
            "service_name": case.service_name,
            "environment": case.environment,
            "document_type": case.document_type,
        }
    )
    return normalize_tool_result(result)


def document_source(document: Document) -> str:
    metadata = document.metadata or {}
    source = metadata.get("_file_name") or metadata.get("_source") or "unknown"
    return Path(str(source)).name


def document_snapshot(document: Document) -> dict[str, Any]:
    metadata = document.metadata or {}
    return {
        "source": document_source(document),
        "chunk_id": metadata.get("_chunk_id"),
        "rerank_score": metadata.get("rerank_score"),
        "rrf_score": metadata.get("rrf_score"),
        "content_preview": document.page_content[:300],
    }


def evaluate_retrieval_case(
    case: EvalCase, documents: list[Document], k: int, error: str | None = None
) -> RetrievalCaseResult:
    top_documents = documents[:k]
    expected = {Path(source).name for source in case.expected_sources}
    retrieved_sources = [document_source(document) for document in top_documents]
    relevant_positions = [
        index for index, source in enumerate(retrieved_sources, start=1) if source in expected
    ]
    matched_sources = set(retrieved_sources) & expected
    recall = len(matched_sources) / len(expected) if expected else None
    precision = len(relevant_positions) / k if expected and k > 0 else None
    reciprocal_rank = 1 / relevant_positions[0] if relevant_positions else None
    return RetrievalCaseResult(
        id=case.id,
        category=case.category,
        question_type=case.question_type,
        difficulty=case.difficulty,
        answerable=case.answerable,
        safety_level=case.safety_level,
        question=case.question,
        expected_sources=sorted(expected),
        retrieved_sources=retrieved_sources,
        hit=bool(relevant_positions),
        recall=recall,
        precision=precision,
        reciprocal_rank=reciprocal_rank,
        retrieved_empty=not bool(top_documents),
        error=error,
        documents=[document_snapshot(document) for document in top_documents],
    )


def summarize_retrieval(results: list[RetrievalCaseResult], k: int) -> dict[str, Any]:
    answerable_results = [result for result in results if result.answerable]
    negative_results = [result for result in results if not result.answerable]
    if not answerable_results:
        return {
            "k": k,
            "case_count": 0,
            "answerable_count": 0,
            "no_answer_count": len(negative_results),
            "hit_rate_at_k": 0.0,
            "recall_at_k": 0.0,
            "precision_at_k": 0.0,
            "mrr_at_k": 0.0,
            "no_answer_empty_retrieval_rate": _empty_rate(negative_results),
        }
    return {
        "k": k,
        "case_count": len(results),
        "answerable_count": len(answerable_results),
        "no_answer_count": len(negative_results),
        "hit_rate_at_k": sum(result.hit for result in answerable_results)
        / len(answerable_results),
        "recall_at_k": _average(answerable_results, "recall"),
        "precision_at_k": _average(answerable_results, "precision"),
        "mrr_at_k": _average(answerable_results, "reciprocal_rank"),
        "no_answer_empty_retrieval_rate": _empty_rate(negative_results),
    }


def summarize_by(
    results: list[RetrievalCaseResult], field_name: str, k: int
) -> dict[str, dict[str, Any]]:
    values = sorted({str(getattr(result, field_name)) for result in results})
    return {
        value: summarize_retrieval(
            [result for result in results if str(getattr(result, field_name)) == value],
            k,
        )
        for value in values
    }


def dataset_fingerprint(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def config_snapshot() -> dict[str, Any]:
    from app.config import config

    return {
        "rag_model": config.rag_model,
        "rag_eval_model": config.rag_eval_model,
        "rag_eval_api_base": config.rag_eval_api_base,
        "rag_top_k": config.rag_top_k,
        "rag_retrieval_k": config.rag_retrieval_k,
        "rag_keyword_k": config.rag_keyword_k,
        "rag_hybrid_enabled": config.rag_hybrid_enabled,
        "rag_min_rerank_score": config.rag_min_rerank_score,
        "rerank_backend": config.rerank_backend,
        "rerank_model": config.rerank_model,
        "embedding_model": config.siliconflow_embedding_model,
    }


def _average(results: list[RetrievalCaseResult], field_name: str) -> float:
    values = [
        value
        for value in (getattr(result, field_name) for result in results)
        if value is not None
    ]
    return sum(values) / len(values) if values else 0.0


def _empty_rate(results: list[RetrievalCaseResult]) -> float:
    return sum(result.retrieved_empty for result in results) / len(results) if results else 0.0


def result_to_dict(result: RetrievalCaseResult) -> dict[str, Any]:
    return asdict(result)
