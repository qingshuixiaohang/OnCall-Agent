"""Mem0 长期记忆管理

职责：
1. 管理 Mem0 全局单例
2. 提供统一的记忆存取接口
3. 用持久 user_id（机器指纹），不用 session_id（避免跨会话丢失）

设计决策：
- 所有 Agent 共享同一个 mem0 实例（单例）
- 不设 agent_id 隔离：运维经验不分入口，学到就是赚到
"""

import asyncio
import hashlib
import platform
import threading
import time
from pathlib import Path
from typing import Any

from loguru import logger

from app.config import config, mem0_config

_MEMORY: Any = None
_MEMORY_LOCK = threading.RLock()
_MEMORY_TASKS: set[asyncio.Task] = set()


def _get_machine_id() -> str:
    """生成持久机器标识

    为什么不直接用 session_id？
    - session_id 每次重开对话就换，记忆无法跨 session 积累
    - 用机器指纹生成"持久匿名 ID"，重启项目记忆仍在

    为什么不用真实 user id？
    - 项目没有用户认证系统
    - 先顶住，等加了登录再换成 request.user.id
    """
    configured_user_id = mem0_config.mem0_user_id.strip()
    if configured_user_id:
        return configured_user_id

    raw = f"{platform.node()}-{platform.machine()}"
    # 保持历史版本的标识算法，避免升级后无法召回已有记忆。
    return "mem0-" + hashlib.md5(raw.encode()).hexdigest()[:12]


def get_memory() -> Any:
    """获取 Mem0 全局单例

    初始化配置说明：
    - llm: 用 DashScope（阿里云百炼兼容模式），模型由 config.mem0_model 指定
      （独立于主对话模型 rag_model，避免抢占额度）
    - embedder: 用 SiliconFlow（BGE-M3，与 Milvus 向量维度 1024 一致）
    - vector_store: 用 Qdrant 本地模式（Mem0 v2.0.14 不支持 sqlite）

    LLM 使用 DashScope，Embedding 使用 SiliconFlow；两者职责不同，
    Embedding 维度必须与 Mem0 Qdrant collection 的 1024 维配置一致。
    """
    global _MEMORY

    with _MEMORY_LOCK:
        if _MEMORY is not None:
            return _MEMORY

        logger.info("初始化 Mem0 长期记忆...")

        from mem0 import Memory

        project_root = Path(__file__).resolve().parents[2]
        volumes_dir = project_root / "volumes"
        volumes_dir.mkdir(parents=True, exist_ok=True)

        config_dict = {
            "history_db_path": str(volumes_dir / "mem0_history.db"),
            "llm": {
                "provider": "openai",
                "config": {
                    "model": config.mem0_model,
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
                    "path": str(volumes_dir / "mem0_qdrant"),
                    "embedding_model_dims": 1024,
                },
            },
        }

        _MEMORY = Memory.from_config(config_dict)
        logger.info(f"Mem0 初始化完成, user_id={_get_machine_id()}")
        return _MEMORY


def search_memory(query: str, limit: int = 3) -> str:
    try:
        memory = get_memory()
        with _MEMORY_LOCK:
            response = memory.search(
                query=query,
                filters={"user_id": _get_machine_id()},
                top_k=limit,
            )

        if isinstance(response, dict):
            results_list = response.get("results", response.get("memories", []))
        elif isinstance(response, list):
            results_list = response
        else:
            results_list = []

        if not isinstance(results_list, list):
            results_list = []

        normalized_results = []
        for item in results_list or []:
            if isinstance(item, str):
                normalized_results.append({"memory": item, "score": 0.0})
            elif isinstance(item, dict):
                normalized_results.append(item)

        results_list = normalized_results
        if not results_list:
            return ""

        sorted_results = sorted(
            results_list,
            key=lambda r: _score_value(r.get("score", 0)),
            reverse=True,
        )

        lines = ["【历史相关经验】"]
        for i, r in enumerate(sorted_results, 1):
            mem_text = str(r.get("memory", "")).strip()
            score = _score_value(r.get("score", 0))
            if mem_text:
                lines.append(f"{i}. [相关性={score:.2f}] {mem_text[:200]}")

        logger.info(f"从 Mem0 召回 {len(sorted_results)} 条记忆")
        return "\n".join(lines)

    except Exception as e:
        logger.warning(f"Mem0 检索失败（不影响主流程）: {e}")
        return ""


def _score_value(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


async def asearch_memory(query: str, limit: int = 3) -> str:
    """异步调用同步 Mem0，避免阻塞 FastAPI/LangGraph 事件循环。"""
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(search_memory, query, limit),
            timeout=5,
        )
    except TimeoutError:
        logger.warning("Mem0 检索超时（5 秒），跳过本次记忆注入")
        return ""


def save_memory(messages: list[dict[str, str]], metadata: dict | None = None):
    """保存对话到 Mem0 长期记忆

    什么时机存：
    - Multi-Agent 的 Aggregator 生成最终报告后
    - RAG Agent 完成一次对话后
    - AIOps Planner 执行完整诊断后

    存什么内容：
    - messages: 对话内容（Mem0 自动做事实抽取）
    - metadata: 标记来源，方便追溯
    """
    started_at = time.perf_counter()
    try:
        memory = get_memory()
        with _MEMORY_LOCK:
            memory.add(
                messages=messages,
                user_id=_get_machine_id(),
                metadata=metadata or {},
            )
        elapsed = time.perf_counter() - started_at
        logger.info("已保存 {} 条消息到 Mem0，耗时 {:.1f}s", len(messages), elapsed)
    except Exception as e:
        elapsed = time.perf_counter() - started_at
        logger.warning("Mem0 保存失败（不影响主流程，耗时 {:.1f}s）: {}", elapsed, e)


async def asave_memory(
    messages: list[dict[str, str]], metadata: dict | None = None
) -> None:
    """异步调用同步 Mem0 写入，避免阻塞请求处理。"""
    await asyncio.to_thread(save_memory, messages, metadata)


async def _save_memory_background(
    messages: list[dict[str, str]], metadata: dict | None = None
) -> None:
    try:
        timeout = mem0_config.mem0_save_timeout
        await asyncio.wait_for(asave_memory(messages, metadata), timeout=timeout)
    except TimeoutError:
        logger.warning(
            "Mem0 后台写入等待超过 {} 秒，底层线程仍可能继续执行，不影响主流程",
            mem0_config.mem0_save_timeout,
        )
    except Exception as e:
        logger.warning("Mem0 后台写入异常（不影响主流程）: {}", e)


def schedule_memory_save(
    messages: list[dict[str, str]], metadata: dict | None = None
) -> None:
    """将 Mem0 写入放入后台，避免阻塞 SSE/HTTP 响应。"""
    task = asyncio.create_task(_save_memory_background(messages, metadata))
    _MEMORY_TASKS.add(task)
    task.add_done_callback(_MEMORY_TASKS.discard)
    logger.info("Mem0 记忆写入已加入后台队列")


async def flush_memory_tasks(timeout: float = 5) -> None:
    """应用关闭前尽量等待已排队的记忆写入。"""
    if not _MEMORY_TASKS:
        return
    pending = list(_MEMORY_TASKS)
    try:
        await asyncio.wait_for(asyncio.gather(*pending, return_exceptions=True), timeout)
    except TimeoutError:
        logger.warning("应用关闭时仍有 Mem0 写入未完成，已跳过等待")
