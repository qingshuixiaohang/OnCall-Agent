"""使用 Qwen 为单份知识文档生成评测候选数据，结果需人工审核后再冻结。"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


def extract_json_array(text: str) -> list[dict[str, Any]]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.IGNORECASE)
    start = cleaned.find("[")
    end = cleaned.rfind("]")
    if start < 0 or end <= start:
        raise ValueError("模型输出中没有找到 JSON 数组")
    data = json.loads(cleaned[start : end + 1])
    if not isinstance(data, list) or not all(isinstance(item, dict) for item in data):
        raise ValueError("模型输出不是对象数组")
    return data


def build_llm() -> Any:
    from langchain_qwq import ChatQwen

    from app.config import config

    return ChatQwen(
        model=config.rag_model,
        api_key=config.dashscope_api_key,
        base_url=config.dashscope_api_base,
        temperature=0.2,
    )


def generate_for_source(llm: Any, source_name: str, content: str, count: int) -> list[dict[str, Any]]:
    prompt = f"""
你是 RAG 评测数据集设计员。只根据下面的运维文档生成 {count} 条不同问法。
不得引入文档没有的事实、命令、阈值或处理建议。
每条输出字段：question、question_type、difficulty、safety_level、reference_answer。
question_type 只能是 direct、paraphrase、procedure、threshold、root_cause、command、validation、colloquial、multi_condition、emergency。
difficulty 只能是 easy、medium、hard；safety_level 只能是 low、medium、high。
reference_answer 必须是人工可以依据文档核对的简洁答案。
只输出 JSON 数组，不要输出解释或 Markdown。

来源文件：{source_name}
文档内容：
{content}
""".strip()
    response = llm.invoke(prompt)
    return extract_json_array(str(getattr(response, "content", response)))


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="生成 RAG 评测候选数据")
    parser.add_argument("--count-per-source", type=int, default=10)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).with_name("dataset_candidates.jsonl"),
    )
    args = parser.parse_args()
    if args.count_per_source <= 0:
        parser.error("--count-per-source 必须大于 0")

    upload_dir = Path(__file__).parents[1] / "uploads"
    llm = build_llm()
    candidates = []
    for source_path in sorted(upload_dir.glob("*.md")):
        print(f"生成候选: {source_path.name}")
        items = generate_for_source(
            llm,
            source_path.name,
            source_path.read_text(encoding="utf-8"),
            args.count_per_source,
        )
        for index, item in enumerate(items[: args.count_per_source], start=1):
            candidates.append(
                {
                    "id": f"candidate-{source_path.stem}-{index:03d}",
                    "category": source_path.stem.replace("_high_usage", "").replace(
                        "_unavailable", "_unavailable"
                    ),
                    "question_type": str(item.get("question_type", "paraphrase")),
                    "difficulty": str(item.get("difficulty", "medium")),
                    "answerable": True,
                    "safety_level": str(item.get("safety_level", "medium")),
                    "question": str(item["question"]),
                    "expected_sources": [source_path.name],
                    "reference_answer": str(item["reference_answer"]),
                }
            )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in candidates) + "\n",
        encoding="utf-8",
    )
    print(f"候选数据已保存: {args.output}, 数量={len(candidates)}")
    print("请人工审核后，再合并到 dataset.jsonl 冻结")


if __name__ == "__main__":
    main()
