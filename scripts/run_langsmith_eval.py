"""LangSmith 评估运行脚本

功能：
1. 读取 multi-agent-routing-test 数据集中的测试用例
2. 调用 Multi-Agent 服务执行每个测试用例
3. 对比实际路由结果与预期 expected_specialists
4. 将评估结果上传到 LangSmith

运行方式：
    python scripts/run_langsmith_eval.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from loguru import logger

# 确保项目根目录在 sys.path 中
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

# 加载 .env 文件
load_dotenv(_PROJECT_ROOT / ".env")

# 读取配置
LANGCHAIN_API_KEY = os.environ.get("LANGCHAIN_API_KEY", "")
LANGCHAIN_PROJECT = os.environ.get("LANGCHAIN_PROJECT", "OnCall-Agent")
LANGCHAIN_ENDPOINT = os.environ.get("LANGCHAIN_ENDPOINT", "https://api.smith.langchain.com")

if not LANGCHAIN_API_KEY:
    logger.error("LANGCHAIN_API_KEY 未配置，请在 .env 中设置")
    sys.exit(1)

# 设置环境变量，让 langsmith SDK 能读到
os.environ["LANGCHAIN_API_KEY"] = LANGCHAIN_API_KEY
os.environ["LANGCHAIN_PROJECT"] = LANGCHAIN_PROJECT
os.environ["LANGCHAIN_ENDPOINT"] = LANGCHAIN_ENDPOINT


# ========== Multi-Agent Target ==========

# 全局复用事件循环，避免 MCP 客户端 httpx 连接池清理时报错
_main_loop: asyncio.AbstractEventLoop | None = None


def _get_or_create_loop() -> asyncio.AbstractEventLoop:
    """获取或创建全局事件循环"""
    global _main_loop
    if _main_loop is None or _main_loop.is_closed():
        _main_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_main_loop)
    return _main_loop


async def _run_multi_agent(inputs: dict[str, Any]) -> dict[str, Any]:
    """
    调用 Multi-Agent 服务执行用户输入

    返回：
        {
            "user_input": str,
            "actual_specialists": list[str],
            "final_report": str,
        }
    """
    from app.agent.multi_agent import multi_agent_service

    user_input = inputs.get("user_input", "")

    actual_specialists: list[str] = []
    final_report = ""

    async for event in multi_agent_service.execute(
        user_input=user_input,
        session_id=f"eval-{hash(user_input)}",
    ):
        event_type = event.get("type")

        if event_type == "routing":
            actual_specialists = event.get("specialists", [])
            logger.debug(f"[{user_input[:30]}] 路由结果: {actual_specialists}")

        elif event_type == "complete":
            final_report = event.get("report", "")

    return {
        "user_input": user_input,
        "actual_specialists": actual_specialists,
        "final_report": final_report[:200] if final_report else "",
    }


def multi_agent_target(inputs: dict[str, Any]) -> dict[str, Any]:
    """
    LangSmith evaluate 的同步 target 函数

    修复：复用全局事件循环，避免 MCP 客户端 httpx 连接池清理时报错
    """
    loop = _get_or_create_loop()
    return loop.run_until_complete(_run_multi_agent(inputs))


# ========== 评估函数 ==========

def routing_evaluator(
    run: Any,
    example: Any,
) -> dict[str, Any]:
    """
    自定义评估函数：对比预期 Specialist 与实际 Specialist

    返回：
        {
            "key": "routing_accuracy",
            "score": 0.0~1.0,
            "comment": str,
        }
    """
    expected = example.outputs.get("expected_specialists", []) if example.outputs else []
    actual = run.outputs.get("actual_specialists", []) if run.outputs else []

    expected_set = set(expected)
    actual_set = set(actual)

    # 改进的评分逻辑
    if not expected_set and not actual_set:
        score = 1.0
        comment = "正确：无需路由"
    elif expected_set == actual_set:
        score = 1.0
        comment = "路由完全正确"
    elif expected_set & actual_set:
        intersection = expected_set & actual_set
        union = expected_set | actual_set
        score = len(intersection) / len(union)
        comment = f"路由部分正确 (相似度: {score:.2f})"
    else:
        score = 0.0
        comment = f"路由错误，预期: {expected}, 实际: {actual}"

    logger.info(f"评估 [{example.inputs.get('user_input', '')[:30]}]: {score} - {comment}")

    return {
        "key": "routing_accuracy",
        "score": score,
        "comment": comment,
    }


# ========== 主逻辑 ==========

def run_evaluation() -> None:
    """运行 LangSmith 评估（同步版本，兼容最新 SDK）"""
    from langsmith import Client
    from langsmith.evaluation import evaluate

    client = Client()
    dataset_name = "multi-agent-routing-test"

    # 1. 确认数据集存在（同步 API）
    try:
        dataset = client.read_dataset(dataset_name=dataset_name)
        logger.info(f"使用数据集: {dataset_name} (id={dataset.id})")
    except Exception:
        logger.error(f"Dataset '{dataset_name}' 不存在，请先运行 seed_langsmith_dataset.py")
        sys.exit(1)

    # 2. 运行评估
    logger.info("开始 LangSmith 评估...")

    _ = evaluate(
        multi_agent_target,
        data=dataset_name,
        evaluators=[routing_evaluator],
        experiment_prefix="multi-agent-routing",
        metadata={
            "component": "supervisor",
            "model": os.environ.get("DASHSCOPE_MODEL", "unknown"),
        },
    )

    logger.info("评估完成")
    logger.info(f"评估结果已上传到 LangSmith Project: {LANGCHAIN_PROJECT}")
    logger.info("请在 https://smith.langchain.com 查看实验结果")


if __name__ == "__main__":
    run_evaluation()
