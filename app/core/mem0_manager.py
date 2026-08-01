"""Mem0 长期记忆管理

职责：
1. 管理 Mem0 全局单例
2. 提供统一的记忆存取接口
3. 用持久 user_id（机器指纹），不用 session_id（避免跨会话丢失）

设计决策：
- 所有 Agent 共享同一个 mem0 实例（单例）
- 不设 agent_id 隔离：运维经验不分入口，学到就是赚到
"""

import hashlib
import platform
from typing import Any, Dict, List, Optional

from loguru import logger

from app.config import config

_MEMORY: Any = None


def _get_machine_id() -> str:
    """生成持久机器标识

    为什么不直接用 session_id？
    - session_id 每次重开对话就换，记忆无法跨 session 积累
    - 用机器指纹生成"持久匿名 ID"，重启项目记忆仍在

    为什么不用真实 user id？
    - 项目没有用户认证系统
    - 先顶住，等加了登录再换成 request.user.id
    """
    raw = f"{platform.node()}-{platform.machine()}"
    return "mem0-" + hashlib.md5(raw.encode()).hexdigest()[:12]


def get_memory() -> Any:
    """获取 Mem0 全局单例

    初始化配置说明：
    - llm: 用 DashScope（阿里云百炼兼容模式）
    - embedder: 用 SiliconFlow（BGE-M3，与 Milvus 向量维度 1024 一致）
     - vector_store: 用 Qdrant 本地模式（Mem0 v2.0.14 不支持 sqlite）

    为什么 llm 也用 SiliconFlow？
    - DashScope 的 OpenAI 兼容模式不是 100% 兼容
    - Mem0 内部做事实抽取时可能调用失败
    - SiliconFlow 也提供 Qwen 模型，兼容性更好
    """
    global _MEMORY

    if _MEMORY is not None:
        return _MEMORY

    logger.info("初始化 Mem0 长期记忆...")

    from mem0 import Memory

    config_dict = {
        "history_db_path": "./volumes/mem0_history.db",  # ← 新增，挪到项目目录下
        "llm": {
            "provider": "openai",
            "config": {
                "model": config.dashscope_model,
                "openai_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                "api_key": config.dashscope_api_key,
            },
        },
        "embedder": {
            "provider": "openai",
            "config": {
                "model": config.siliconflow_embedding_model,
                "openai_base_url": config.siliconflow_api_base,
                "api_key": config.siliconflow_api_key,
            },
        },
        "vector_store": {
            "provider": "qdrant",
            "config": {
                "path": "./volumes/mem0_qdrant",
                "embedding_model_dims": 1024,# ← 加这一行
            },
        },
    }

    _MEMORY = Memory.from_config(config_dict)
    logger.info(f"Mem0 初始化完成, user_id={_get_machine_id()}")
    return _MEMORY


def search_memory(query: str, limit: int = 3) -> str:
    try:
        memory = get_memory()
        response = memory.search(
            query=query,
            filters={"user_id": _get_machine_id()},
            top_k=limit,
        )

        results_list = response.get("results", [])
        if not results_list:
            return ""

        sorted_results = sorted(
            results_list, key=lambda r: r.get("score", 0), reverse=True
        )

        lines = ["【历史相关经验】"]
        for i, r in enumerate(sorted_results, 1):
            mem_text = r.get("memory", "").strip()
            score = r.get("score", 0)
            if mem_text:
                lines.append(f"{i}. [相关性={score:.2f}] {mem_text[:200]}")

        logger.info(f"从 Mem0 召回 {len(sorted_results)} 条记忆")
        return "\n".join(lines)

    except Exception as e:
        logger.warning(f"Mem0 检索失败（不影响主流程）: {e}")
        return ""

def save_memory(messages: List[Dict[str, str]], metadata: Optional[Dict] = None):
    """保存对话到 Mem0 长期记忆

    什么时机存：
    - Multi-Agent 的 Aggregator 生成最终报告后
    - RAG Agent 完成一次对话后
    - AIOps Planner 执行完整诊断后

    存什么内容：
    - messages: 对话内容（Mem0 自动做事实抽取）
    - metadata: 标记来源，方便追溯
    """
    try:
        memory = get_memory()
        memory.add(
            messages=messages,
            user_id=_get_machine_id(),
            metadata=metadata or {},
        )
        logger.info(f"已保存 {len(messages)} 条消息到 Mem0")
    except Exception as e:
        logger.warning(f"Mem0 保存失败（不影响主流程）: {e}")