"""校验简历级 RAG 评测数据集的结构和分布。"""

from __future__ import annotations

import argparse
import sys

# 确保能从 evals/ 目录直接 import common（不依赖 CWD）
import sys as _sys
from collections import Counter
from pathlib import Path, Path as _Path

_EVALS_DIR = _Path(__file__).resolve().parent
if str(_EVALS_DIR) not in _sys.path:
    _sys.path.insert(0, str(_EVALS_DIR))
from common import dataset_fingerprint, load_cases


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="校验 RAG 评测数据集")
    parser.add_argument(
        "--dataset", type=Path, default=Path(__file__).with_name("dataset.jsonl")
    )
    parser.add_argument("--expected-count", type=int, default=60)
    args = parser.parse_args()

    cases = load_cases(args.dataset)
    if len(cases) != args.expected_count:
        raise ValueError(f"数据量错误: 期望 {args.expected_count}，实际 {len(cases)}")

    ids = [case.id for case in cases]
    duplicate_ids = [item for item, count in Counter(ids).items() if count > 1]
    if duplicate_ids:
        raise ValueError(f"存在重复 id: {duplicate_ids}")

    upload_dir = Path(__file__).parents[1] / "uploads"
    missing_sources = sorted(
        {
            source
            for case in cases
            for source in case.expected_sources
            if not (upload_dir / Path(source).name).exists()
        }
    )
    if missing_sources:
        raise ValueError(f"expected_sources 不存在: {missing_sources}")

    category_counts = Counter(case.category for case in cases)
    answerable_count = sum(case.answerable for case in cases)
    no_answer_count = len(cases) - answerable_count
    answerable_single_source = [
        case for case in cases if case.answerable and len(case.expected_sources) == 1
    ]
    source_counts = Counter(
        Path(case.expected_sources[0]).name for case in answerable_single_source
    )
    expected_sources = {
        "cpu_high_usage.md",
        "disk_high_usage.md",
        "memory_high_usage.md",
        "service_unavailable.md",
        "slow_response.md",
    }
    if set(source_counts) != expected_sources:
        raise ValueError(
            f"单文档来源不完整: 期望 {sorted(expected_sources)}，实际 {sorted(source_counts)}"
        )
    for source in expected_sources:
        if source_counts[source] != 10:
            raise ValueError(f"{source} 应有 10 条单文档问题，实际 {source_counts[source]} 条")

    cross_count = sum(case.category == "cross_system" for case in cases)
    if cross_count != 5:
        raise ValueError(f"cross_system 应有 5 条，实际 {cross_count} 条")
    if any(
        case.category == "cross_system"
        and (not case.answerable or len(case.expected_sources) < 2)
        for case in cases
    ):
        raise ValueError("跨文档问题必须 answerable=true 且至少包含两个 expected_sources")
    if no_answer_count != 5 or any(case.answerable for case in cases if case.category == "out_of_scope"):
        raise ValueError("无答案数据集应有 5 条，且 answerable 必须为 false")

    print(f"数据集校验通过: {args.dataset}")
    print(f"总数: {len(cases)}, 可回答: {answerable_count}, 无答案: {no_answer_count}")
    print(f"分类: {dict(sorted(category_counts.items()))}")
    print(f"fingerprint: {dataset_fingerprint(args.dataset)}")


if __name__ == "__main__":
    main()
