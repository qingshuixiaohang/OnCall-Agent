"""运行零生成成本的 RAG 召回评测。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from common import (
    config_snapshot,
    dataset_fingerprint,
    evaluate_retrieval_case,
    invoke_retriever,
    load_cases,
    result_to_dict,
    summarize_by,
    summarize_retrieval,
)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="评估 RAG 的召回、Precision 和 MRR")
    parser.add_argument("--k", type=int, default=3, help="评估前 K 个结果，默认 3")
    parser.add_argument(
        "--dataset", type=Path, default=Path(__file__).with_name("dataset.jsonl")
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=Path(__file__).with_name("reports") / "retrieval_report.json",
    )
    parser.add_argument(
        "--group-by",
        nargs="+",
        choices=["category", "question_type", "difficulty", "safety_level"],
        default=["category", "question_type", "difficulty"],
        help="需要输出的分组维度",
    )
    args = parser.parse_args()
    if args.k <= 0:
        parser.error("--k 必须大于 0")

    cases = load_cases(args.dataset)
    results = []
    for index, case in enumerate(cases, start=1):
        print(f"[{index}/{len(cases)}] 检索: {case.question}")
        try:
            context, documents = invoke_retriever(case)
            error = context if context.startswith("检索知识时发生错误:") else None
        except Exception as exc:
            documents = []
            error = f"{type(exc).__name__}: {exc}"
        result = evaluate_retrieval_case(case, documents, args.k, error=error)
        results.append(result)
        print(
            f"  expected={result.expected_sources} "
            f"retrieved={result.retrieved_sources} "
            f"reciprocal_rank={result.reciprocal_rank if result.reciprocal_rank is not None else 'N/A'}"
        )

    summary = summarize_retrieval(results, args.k)
    report = {
        "evaluation": "retrieval",
        "dataset_version": "resume-rag-v1",
        "dataset": str(args.dataset),
        "dataset_fingerprint": dataset_fingerprint(args.dataset),
        "config": config_snapshot(),
        "summary": summary,
        "groups": {field: summarize_by(results, field, args.k) for field in args.group_by},
        "failures": [result_to_dict(result) for result in results if result.error],
        "cases": [result_to_dict(result) for result in results],
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n召回评测结果")
    print(f"Recall@{args.k}:    {summary['recall_at_k']:.3f}")
    print(f"Precision@{args.k}: {summary['precision_at_k']:.3f}")
    print(f"MRR@{args.k}:       {summary['mrr_at_k']:.3f}")
    print(f"无答案空召回率:       {summary['no_answer_empty_retrieval_rate']:.3f}")
    print(f"报告已保存: {args.report}")


if __name__ == "__main__":
    main()
