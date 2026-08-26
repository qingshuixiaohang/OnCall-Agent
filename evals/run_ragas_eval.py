"""运行 Ragas 端到端 RAG 质量评测。"""

from __future__ import annotations

import argparse
import json
import math
import sys

# 确保能从 evals/ 目录直接 import common（不依赖 CWD）
import sys as _sys
import warnings
from pathlib import Path, Path as _Path
from typing import Any

_EVALS_DIR = _Path(__file__).resolve().parent
if str(_EVALS_DIR) not in _sys.path:
    _sys.path.insert(0, str(_EVALS_DIR))
from common import config_snapshot, dataset_fingerprint, invoke_retriever, load_cases

_ABSTENTION_MARKERS = (
    "没有覆盖",
    "未覆盖",
    "资料不足",
    "无法根据现有资料",
    "不能据此",
    "无法给出",
)


def build_generation_llm() -> Any:
    from langchain_qwq import ChatQwen

    from app.config import config

    return ChatQwen(
        model=config.rag_model,
        api_key=config.dashscope_api_key,
        base_url=config.dashscope_api_base,
        temperature=0,
    )


def build_evaluation_llm() -> Any:
    from langchain_openai import ChatOpenAI

    from app.config import config

    if not config.rag_eval_api_key:
        raise RuntimeError(
            "未配置 RAG_EVAL_API_KEY，请在 .env 中填写 StepFun 评审模型 API Key"
        )
    return ChatOpenAI(
        model=config.rag_eval_model,
        api_key=config.rag_eval_api_key,
        base_url=config.rag_eval_api_base,
        temperature=0,
    )


def build_answer(question: str, context: str, llm: Any) -> str:
    prompt = (
        "你是企业运维知识库问答助手。只能依据给定资料回答，不要补充资料中没有的事实。"
        "如果资料不足，请明确说明。回答简洁、分点，并给出资料来源。\n\n"
        f"问题：{question}\n\n资料：\n{context}"
    )
    response = llm.invoke(prompt)
    return str(getattr(response, "content", response))


def _load_legacy_metrics() -> list[Any]:
    """加载 evaluate() 在 Ragas 0.x 使用的兼容指标实例。"""
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message="Importing .* from 'ragas.metrics' is deprecated.*",
            category=DeprecationWarning,
        )
        from ragas import metrics

        metric_names = (
            ("faithfulness", "Faithfulness"),
            ("answer_relevancy", "ResponseRelevancy"),
            ("context_precision", "LLMContextPrecisionWithReference"),
            ("context_recall", "LLMContextRecall"),
        )
        selected = []
        for old_name, new_name in metric_names:
            metric = getattr(metrics, old_name, None)
            if metric is None:
                metric_class = getattr(metrics, new_name, None)
                metric = metric_class() if metric_class is not None else None
            if metric is not None:
                selected.append(metric)
        for metric in selected:
            if getattr(metric, "name", None) == "answer_relevancy":
                metric.strictness = 1
    return selected


def load_ragas_symbols() -> tuple[Any, list[Any], Any]:
    try:
        from ragas import evaluate
    except ImportError as error:
        raise RuntimeError(
            "未安装 Ragas 评测依赖，请先执行: uv sync --extra eval"
        ) from error

    try:
        from ragas import EvaluationDataset

        dataset_type = EvaluationDataset
    except ImportError:
        from datasets import Dataset

        dataset_type = Dataset

    # Ragas 0.4 exposes the new collections path, but its collection metrics
    # are standalone modern metrics and are not accepted by evaluate(). The
    # legacy instances remain the compatible path until the evaluator changes.
    try:
        from ragas.metrics.collections import (
            AnswerRelevancy,
            ContextPrecisionWithReference,
            ContextRecall,
            Faithfulness,
        )

        collections_metrics = (
            Faithfulness,
            AnswerRelevancy,
            ContextPrecisionWithReference,
            ContextRecall,
        )
        if all(hasattr(metric, "single_turn_ascore") for metric in collections_metrics):
            return evaluate, [metric() for metric in collections_metrics], dataset_type
    except (ImportError, TypeError):
        pass

    return evaluate, _load_legacy_metrics(), dataset_type


def load_or_generate_rows(
    cases: list[Any], intermediate_path: Path, fingerprint: str, llm: Any | None, reuse: bool
) -> list[dict[str, Any]]:
    if reuse:
        if not intermediate_path.exists():
            raise FileNotFoundError(f"中间结果不存在: {intermediate_path}")
        payload = json.loads(intermediate_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("dataset_fingerprint") != fingerprint:
            raise ValueError("中间结果与当前数据集 fingerprint 不一致，请重新生成")
        rows = payload.get("rows")
        if not isinstance(rows, list) or len(rows) != len(cases):
            raise ValueError("中间结果行数与当前数据集不一致，请重新生成")
        return rows

    rows: list[dict[str, Any]] = []
    for index, case in enumerate(cases, start=1):
        print(f"[{index}/{len(cases)}] 生成回答: {case.question}")
        row = {
            "id": case.id,
            "category": case.category,
            "question_type": case.question_type,
            "difficulty": case.difficulty,
            "answerable": case.answerable,
            "safety_level": case.safety_level,
            "user_input": case.question,
            "retrieved_contexts": [],
            "response": "",
            "reference": case.reference_answer,
            "error": None,
        }
        try:
            context, documents = invoke_retriever(case)
            row["retrieved_contexts"] = [document.page_content for document in documents]
            if context.startswith("检索知识时发生错误:"):
                raise RuntimeError(context)
            row["response"] = build_answer(case.question, context, llm)
        except Exception as exc:
            row["error"] = f"{type(exc).__name__}: {exc}"
            print(f"  生成失败: {row['error']}")
        rows.append(row)
    return rows


def _is_nan(value: Any) -> bool:
    try:
        return math.isnan(float(value))
    except (TypeError, ValueError):
        return value is None


def _safe_score(value: Any) -> Any:
    return None if _is_nan(value) else value


def _metric_summary(rows: list[dict[str, Any]], metric_names: list[str]) -> dict[str, Any]:
    summary: dict[str, Any] = {"case_count": len(rows), "valid_count": {}}
    for name in metric_names:
        values = [float(row[name]) for row in rows if not _is_nan(row.get(name))]
        summary[name] = sum(values) / len(values) if values else None
        summary["valid_count"][name] = len(values)
    return summary


def _group_summaries(
    rows: list[dict[str, Any]], metric_names: list[str], field_name: str
) -> dict[str, Any]:
    values = sorted({str(row[field_name]) for row in rows})
    return {
        value: _metric_summary(
            [row for row in rows if str(row[field_name]) == value], metric_names
        )
        for value in values
    }


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="使用 Ragas 评估 RAG 生成质量")
    parser.add_argument(
        "--dataset", type=Path, default=Path(__file__).with_name("dataset.jsonl")
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=Path(__file__).with_name("reports") / "ragas_report.json",
    )
    parser.add_argument(
        "--intermediate",
        type=Path,
        default=Path(__file__).with_name("reports") / "ragas_input.json",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Ragas 并发评测任务数，默认 1，降低模型返回空结果的概率",
    )
    parser.add_argument(
        "--reuse-intermediate",
        action="store_true",
        help="复用同一数据集 fingerprint 的已有回答和上下文",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=60,
        help="单个 Ragas 任务超时时间（秒），默认 60",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=3,
        help="单个 Ragas 任务最大重试次数，默认 3",
    )
    args = parser.parse_args()
    if args.workers <= 0:
        parser.error("--workers 必须大于 0")
    if args.timeout <= 0:
        parser.error("--timeout 必须大于 0")
    if args.max_retries < 0:
        parser.error("--max-retries 不能小于 0")

    cases = load_cases(args.dataset)
    fingerprint = dataset_fingerprint(args.dataset)
    generation_llm = None if args.reuse_intermediate else build_generation_llm()
    evaluation_llm = build_evaluation_llm()
    rows = load_or_generate_rows(
        cases, args.intermediate, fingerprint, generation_llm, args.reuse_intermediate
    )

    args.intermediate.parent.mkdir(parents=True, exist_ok=True)
    args.intermediate.write_text(
        json.dumps(
            {
                "dataset": str(args.dataset),
                "dataset_fingerprint": fingerprint,
                "rows": rows,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    evaluate, metrics, dataset_type = load_ragas_symbols()
    if not metrics:
        raise RuntimeError("当前 Ragas 版本没有找到兼容的评测指标，请检查 ragas 版本")

    metric_names = [getattr(metric, "name", metric.__class__.__name__) for metric in metrics]
    answerable_rows = [row for row in rows if row["answerable"]]
    valid_answerable_rows = [
        row for row in answerable_rows if not row.get("error") and row.get("response")
    ]
    ragas_rows = [
        {
            "user_input": row["user_input"],
            "retrieved_contexts": row["retrieved_contexts"],
            "response": row["response"],
            "reference": row["reference"],
        }
        for row in valid_answerable_rows
    ]

    if ragas_rows:
        try:
            from ragas.run_config import RunConfig

            from app.services.vector_embedding_service import vector_embedding_service

            result = evaluate(
                dataset_type.from_list(ragas_rows),
                metrics=metrics,
                llm=evaluation_llm,
                embeddings=vector_embedding_service,
                run_config=RunConfig(
                    timeout=args.timeout,
                    max_workers=args.workers,
                    max_retries=args.max_retries,
                    max_wait=min(10, args.timeout),
                ),
                raise_exceptions=False,
            )
        except TypeError:
            result = evaluate(dataset_type.from_list(ragas_rows), metrics=metrics)
    else:
        result = None

    score_rows: list[dict[str, Any]] = []
    if result is not None and hasattr(result, "to_pandas"):
        score_rows = result.to_pandas().to_dict(orient="records")
    elif result is not None:
        score_rows = list(dict(result).get("scores", []))

    scores_by_question: dict[str, list[dict[str, Any]]] = {}
    for score_row in score_rows:
        scores_by_question.setdefault(score_row["user_input"], []).append(score_row)
    detailed_scores: list[dict[str, Any]] = []
    for row in answerable_rows:
        scores = (
            scores_by_question.get(row["user_input"], []).pop(0)
            if scores_by_question.get(row["user_input"])
            else {}
        )
        failed_metrics = [name for name in metric_names if _is_nan(scores.get(name))]
        if row.get("error"):
            failed_metrics = ["generation"]
        detailed_scores.append(
            {
                "id": row["id"],
                "category": row["category"],
                "question_type": row["question_type"],
                "difficulty": row["difficulty"],
                "question": row["user_input"],
                "status": "failed" if failed_metrics else "ok",
                "failed_metrics": failed_metrics,
                "error": row.get("error"),
                **{name: _safe_score(scores.get(name)) for name in metric_names},
            }
        )

    no_answer_rows = [row for row in rows if not row["answerable"]]
    no_answer_scores = [
        {
            "id": row["id"],
            "category": row["category"],
            "question": row["user_input"],
            "abstention_detected": any(
                marker in row["response"] for marker in _ABSTENTION_MARKERS
            ),
            "error": row.get("error"),
        }
        for row in no_answer_rows
    ]
    failures = [row for row in detailed_scores if row["status"] == "failed"]
    report = {
        "evaluation": "ragas",
        "dataset_version": "resume-rag-v1",
        "dataset": str(args.dataset),
        "dataset_fingerprint": fingerprint,
        "config": config_snapshot(),
        "metrics": metric_names,
        "metric_config": {"answer_relevancy_strictness": 1},
        "evaluation_config": {
            "workers": args.workers,
            "timeout_seconds": args.timeout,
            "max_retries": args.max_retries,
        },
        "summary": _metric_summary(detailed_scores, metric_names),
        "groups": {
            field: _group_summaries(detailed_scores, metric_names, field)
            for field in ("category", "question_type", "difficulty")
        },
        "no_answer": {
            "case_count": len(no_answer_scores),
            "abstention_count": sum(item["abstention_detected"] for item in no_answer_scores),
            "abstention_rate": (
                sum(item["abstention_detected"] for item in no_answer_scores)
                / len(no_answer_scores)
                if no_answer_scores
                else 0.0
            ),
            "cases": no_answer_scores,
        },
        "failures": failures,
        "scores": detailed_scores,
        "intermediate": str(args.intermediate),
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8"
    )
    print("\nRagas 评测完成")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print(f"失败样本: {len(failures)}")
    print(f"无答案拒答率: {report['no_answer']['abstention_rate']:.3f}")
    print(f"报告已保存: {args.report}")


if __name__ == "__main__":
    main()
