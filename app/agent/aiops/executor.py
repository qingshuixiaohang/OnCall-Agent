"""
Executor 节点：执行单个步骤

设计原则：Executor 只做 Action，不做 Reasoning。
- 一次 LLM 调用决定使用哪个工具
- 执行工具后直接返回原始结果，不调第二次 LLM 去解读
- 解读和评估工作交给 Replanner 节点（宏观 ReAct 循环在节点之间）

这样 LangGraph 能在每次工具调用后自动 checkpoint，
LangSmith 也能看到每一步的细节，而不是 executor 黑盒。
"""

import json
from typing import Dict, Any, Optional
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_qwq import ChatQwen
from langgraph.prebuilt import ToolNode
from loguru import logger

from app.config import config
from app.tools import get_current_time, retrieve_knowledge
from app.agent.mcp_client import get_mcp_client_with_retry
from .state import PlanExecuteState


# ============================================================================
# 第一级：参数预校验（纯 Python，不调 LLM）
# ============================================================================

def validate_tool_params(tool_name: str, params: dict) -> Optional[str]:
    """校验工具参数，返回错误信息或 None（表示参数OK）"""

    if tool_name == "search_log":
        topic_id = params.get("topic_id", "")
        if not topic_id or topic_id.strip() == "":
            return "topic_id 为空，必须先调用 search_topic_by_service_name 获取真实 topic_id"

        start_time = params.get("start_time", 0)
        end_time = params.get("end_time", 0)
        if isinstance(start_time, (int, float)) and isinstance(end_time, (int, float)):
            if start_time > end_time:
                return f"start_time({start_time}) 不能大于 end_time({end_time})"
            if start_time <= 0 or end_time <= 0:
                return "start_time 和 end_time 必须是正的毫秒时间戳"

    if tool_name == "search_topic_by_service_name":
        if not params.get("service_name"):
            return "service_name 为空，请提供要搜索的服务名称"

    return None


# ============================================================================
# 第二级：结果质量检查（纯 Python，不调 LLM）
# ============================================================================

def check_tool_result(tool_name: str, result: dict) -> Optional[str]:
    """检查结果质量，返回错误信息或 None（表示结果OK）"""

    if isinstance(result, str):
        try:
            result = json.loads(result)
        except (json.JSONDecodeError, TypeError):
            return None

    if not isinstance(result, dict):
        return None

    if "error" in result:
        return f"工具返回错误: {result['error']}"

    if tool_name == "search_log":
        if result.get("total", 0) == 0:
            return "查不到日志，可能 query 太严格或时间范围不对，请尝试放宽 query 条件"

    if tool_name == "search_topic_by_service_name":
        if result.get("total", 0) == 0:
            return "没找到匹配的 topic，请尝试更短的服务名关键词（如用 'sync' 代替 'data-sync-service'）"

    return None


# ============================================================================
# Executor 主逻辑
# ============================================================================

# 参数校验失败时最多重试 2 次（每次重试 = 1 次 LLM 调用）
# 正常流程只需要 1 次 LLM 调用（选工具），不再调第二次 LLM 解读结果
MAX_RETRIES = 2

SYSTEM_PROMPT = """你是一个负责执行具体任务步骤的助手。

你可以使用各种工具来完成任务。对于每个步骤：
1. 理解步骤的目标
2. 选择合适的工具（如果步骤已指定工具，则使用指定的工具）
3. 调用工具获取信息

重要原则：
- 你只需要选择工具并调用它，不需要解读工具返回的结果
- 工具返回的原始数据会由后续的 Replanner 节点负责解读和评估
- 不要编造数据，只返回工具的实际输出

注意：
- 不要编造数据，只返回实际获取的信息
- 专注于当前步骤，不要考虑其他任务"""


async def executor(state: PlanExecuteState) -> Dict[str, Any]:
    """
    执行节点：执行计划中的下一个步骤（单次 LLM 调用）

    职责边界：
    - Executor 只负责 Action：选工具 → 执行 → 返回原始结果
    - Replanner 负责 Observation + Reasoning：解读结果、评估、决定下一步
    - ReAct 循环发生在节点之间（LangGraph 可见），而非节点内部（黑盒）

    优化点（相比旧版）：
    - 去掉第二次 LLM 调用（旧版在工具执行后再调 LLM 解读结果）
    - 每个步骤从 2 次 LLM 调用降为 1 次，约节省 50% executor 耗时
    """
    logger.info("=== Executor：执行步骤 ===")

    plan = state.get("plan", [])

    if not plan:
        logger.info("计划为空，跳过执行")
        return {}

    task = plan[0]
    logger.info(f"当前任务: {task}")

    try:
        local_tools = [get_current_time, retrieve_knowledge]

        mcp_client = await get_mcp_client_with_retry()
        mcp_tools = await mcp_client.get_tools()
        logger.info(f"可用工具数量: 本地 {len(local_tools)} + MCP {len(mcp_tools)}")

        all_tools = local_tools + mcp_tools

        llm = ChatQwen(
            model=config.rag_model,
            api_key=config.dashscope_api_key,
            temperature=0
        )
        llm_with_tools = llm.bind_tools(all_tools)

        tool_node = ToolNode(all_tools)

        messages = [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=f"请执行以下任务: {task}"),
        ]

        # ====================================================================
        # 参数校验重试循环（仅在参数不合法时重试，最多 MAX_RETRIES 次）
        # ====================================================================
        result = None
        last_tool_name = None
        last_tool_call = None
        retry_history: list[Dict[str, str]] = []

        for attempt in range(1, MAX_RETRIES + 1):
            logger.info(f"第 {attempt}/{MAX_RETRIES} 次尝试")

            # --- 唯一的 LLM 调用：决定调什么工具 ---
            llm_response = await llm_with_tools.ainvoke(messages)

            if not hasattr(llm_response, "tool_calls") or not llm_response.tool_calls:
                # LLM 决定不调工具，直接用它的文字回复作为结果
                result = llm_response.content if hasattr(llm_response, 'content') else str(llm_response)
                logger.info("LLM 未调用工具，直接返回文字结果")
                break

            # --- 提取工具调用参数 ---
            tool_call = llm_response.tool_calls[0]
            tool_name = tool_call["name"]
            tool_args = tool_call["args"]
            last_tool_name = tool_name
            logger.info(f"LLM 选择工具: {tool_name}, 参数: {tool_args}")

            # --- 第一级：参数预校验（纯 Python，不调 LLM）---
            validation_error = validate_tool_params(tool_name, tool_args)
            if validation_error:
                logger.warning(f"[校验失败] {validation_error}")
                retry_history.append({"attempt": attempt, "stage": "validation", "error": validation_error})
                messages.append(HumanMessage(content=f"参数校验未通过: {validation_error}。请修正参数后重试。"))
                continue

            # --- 执行工具（不调 LLM）---
            messages.append(llm_response)
            tool_messages = await tool_node.ainvoke({"messages": messages})
            tool_result_msg = tool_messages["messages"][-1]
            tool_result = tool_result_msg.content if hasattr(tool_result_msg, 'content') else str(tool_result_msg)

            # 解析工具返回的 JSON
            try:
                result_dict = json.loads(tool_result) if isinstance(tool_result, str) else tool_result
            except (json.JSONDecodeError, TypeError):
                result_dict = {"raw": tool_result}

            # --- 第二级：结果质量检查（纯 Python，不调 LLM）---
            quality_error = check_tool_result(tool_name, result_dict)
            if quality_error:
                logger.warning(f"[质量检查] {quality_error}")
                # 质量问题交给 Replanner 决策，不再在 executor 内重试
                # 返回包含警告信息的原始结果
                result = json.dumps({
                    "warning": quality_error,
                    "raw_result": result_dict,
                }, ensure_ascii=False)
                break

            # --- 成功：直接返回工具原始结果，不调第二次 LLM ---
            # 旧版这里会再调一次 LLM 来解读结果（浪费 5-10s）
            # 新版直接返回原始数据，由 Replanner 负责解读
            result = tool_result
            last_tool_call = {"name": tool_name, "args": tool_args, "result": result}
            logger.info(f"工具执行成功，结果长度: {len(str(result))}")
            break

        # ====================================================================
        # 参数校验全部失败后的处理
        # ====================================================================
        if result is None:
            last_error = f"工具 {last_tool_name} 参数校验失败，已重试 {MAX_RETRIES} 次"
            logger.error(last_error)
            result = json.dumps({
                "error": last_error,
                "tool": last_tool_name,
                "attempts": MAX_RETRIES,
                "retry_history": retry_history,
                "suggestion": "建议 Replanner: 跳过此步骤或改用替代工具",
            }, ensure_ascii=False)

        logger.info(f"步骤执行完成")

        return {
            "plan": plan[1:],
            "past_steps": [(task, result)],
            "last_tool_call": last_tool_call,
        }

    except Exception as e:
        logger.error(f"执行步骤失败: {e}", exc_info=True)
        return {
            "plan": plan[1:],
            "past_steps": [(task, f"执行异常: {str(e)}")],
            "last_tool_call": last_tool_call,
        }
