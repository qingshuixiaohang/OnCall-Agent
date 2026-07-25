"""LangSmith 评估数据集初始化脚本

功能：
1. 自动创建/读取名为 multi-agent-routing-test 的 Dataset
2. 批量导入 15-20 条标准测试用例（Input -> Expected Output）
3. 支持从项目 .env 读取 LangSmith 配置
4. 可重复运行，不会重复创建数据集

运行方式：
    python scripts/seed_langsmith_dataset.py
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger(__name__)

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

# ========== 测试用例定义 ==========

TEST_CASES: list[tuple[dict[str, Any], dict[str, Any]]] = [
    # 日志分析相关
    (
        {"user_input": "data-sync-service 有什么错误日志？"},
        {"expected_specialists": ["log_analyzer"], "category": "log_query"},
    ),
    (
        {"user_input": "payment-service 最近一小时的异常堆栈有哪些？"},
        {"expected_specialists": ["log_analyzer"], "category": "log_query"},
    ),
    (
        {"user_input": "分析 user-service 的日志错误模式"},
        {"expected_specialists": ["log_analyzer"], "category": "log_query"},
    ),
    # 监控指标相关
    (
        {"user_input": "订单服务 CPU 使用率最高是多少？"},
        {"expected_specialists": ["monitor_expert"], "category": "monitor_query"},
    ),
    (
        {"user_input": "memory-service 内存使用率突增，请排查原因"},
        {"expected_specialists": ["monitor_expert"], "category": "monitor_query"},
    ),
    (
        {"user_input": "database 服务的 QPS 和延迟指标如何？"},
        {"expected_specialists": ["monitor_expert"], "category": "monitor_query"},
    ),
    # 知识库检索相关
    (
        {"user_input": "服务重启的最佳实践流程是什么？"},
        {"expected_specialists": ["knowledge_retriever"], "category": "knowledge"},
    ),
    (
        {"user_input": "Kubernetes Pod 频繁重启的常见原因有哪些？"},
        {"expected_specialists": ["knowledge_retriever"], "category": "knowledge"},
    ),
    (
        {"user_input": "数据库连接池泄漏的排查经验"},
        {"expected_specialists": ["knowledge_retriever"], "category": "knowledge"},
    ),
    # 多 Specialist 并行诊断
    (
        {"user_input": "全面诊断 payment-service 故障，包括日志、监控和知识库"},
        {
            "expected_specialists": [
                "log_analyzer",
                "monitor_expert",
                "knowledge_retriever",
            ],
            "category": "multi_agent_diagnosis",
        },
    ),
    (
        {"user_input": "order-service 不可用，请从日志、指标和历史案例三个角度排查"},
        {
            "expected_specialists": [
                "log_analyzer",
                "monitor_expert",
                "knowledge_retriever",
            ],
            "category": "multi_agent_diagnosis",
        },
    ),
    # 边界情况：非运维问题
    (
        {"user_input": "今天天气怎么样？"},
        {"expected_specialists": [], "category": "off_topic"},
    ),
    (
        {"user_input": "你好，请做个自我介绍"},
        {"expected_specialists": [], "category": "off_topic"},
    ),
    # 边界情况：模糊问题
    (
        {"user_input": "服务出问题了"},
        {
            "expected_specialists": ["log_analyzer", "monitor_expert"],
            "category": "vague_issue",
        },
    ),
    (
        {"user_input": "帮我查一下系统状态"},
        {
            "expected_specialists": ["log_analyzer", "monitor_expert"],
            "category": "vague_issue",
        },
    ),
]


# ========== 主逻辑 ==========

def seed_dataset() -> None:
    """创建/更新 LangSmith 测试数据集（同步版本，兼容最新 SDK）"""
    from langsmith import Client

    client = Client()
    dataset_name = "multi-agent-routing-test"

    # 1. 确保数据集存在（使用同步 API）
    try:
        dataset = client.read_dataset(dataset_name=dataset_name)
        logger.info(f"Dataset 已存在: {dataset_name} (id={dataset.id})")
    except Exception:
        dataset = client.create_dataset(
            dataset_name=dataset_name,
            description="AIOps 运维 Agent 路由与诊断测试集，覆盖日志分析、监控查询、知识库检索及多 Agent 并行场景",
        )
        logger.info(f"Dataset 创建成功: {dataset_name} (id={dataset.id})")

    # 2. 清空旧示例（确保测试集干净）
    examples = list(client.list_examples(dataset_id=dataset.id))
    example_ids = [ex.id for ex in examples]
    if example_ids:
        client.delete_examples(example_ids=example_ids)
        logger.info(f"已清空 {len(example_ids)} 条旧示例")

    # 3. 批量导入新示例
    for inputs, outputs in TEST_CASES:
        client.create_example(
            inputs=inputs,
            outputs=outputs,
            dataset_id=dataset.id,
        )

    logger.info(f"测试集导入完成，共 {len(TEST_CASES)} 条示例")
    logger.info(f"请在 LangSmith WebUI 的 Datasets & Experiments 中查看")


if __name__ == "__main__":
    seed_dataset()
