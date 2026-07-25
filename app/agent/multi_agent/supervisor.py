"""Supervisor 路由逻辑

职责：
1. 分析用户问题，决定需要调用哪些 Specialist
2. 生成任务计划（步骤列表）
3. 支持并行执行无依赖的任务
4. 汇总各 Specialist 结果并生成最终报告

设计决策：
1. 路由基于用户输入关键词 + LLM 判断，不做过早的硬编码分类
2. 支持一次路由多个 Specialist，且无依赖的 Specialist 可并行执行
3. 路由结果记录到 state.routing 中，便于前端展示和调试
4. 最终报告由 Supervisor 自己生成，而不是交给某个 Specialist
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple
import asyncio

from textwrap import dedent
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.tools import BaseTool
from langgraph.graph import END, START, StateGraph
from loguru import logger
from pydantic import BaseModel, Field

from app.config import config
from app.agent.multi_agent.state import MultiAgentState
from app.agent.multi_agent.base_specialist import BaseSpecialist
from langchain_qwq import ChatQwen


# ========== 路由决策模型 ==========

class RouteDecision(BaseModel):
    """路由决策输出格式"""

    specialists: List[str] = Field(
        description="需要调用的 Specialist 列表，可选值: log_analyzer, monitor_expert, knowledge_retriever"
    )
    reason: str = Field(description="路由决策理由")
    tasks: List[str] = Field(description="对应的任务计划")


# ========== Supervisor 节点函数 ==========

async def supervisor_node(state: MultiAgentState) -> Dict[str, Any]:
    """
    Supervisor 主节点：分析任务并生成路由决策
    
    这是整个 Multi-Agent 系统的"大脑"，负责任务分解和 Specialist 选择。
    """
    logger.info("=== Supervisor：分析任务并路由 ===")

    user_input = state.get("user_input", "")

    # 如果没有用户输入，直接结束
    if not user_input:
        logger.warning("用户输入为空，结束流程")
        return {
            "routing": [{"specialists": [], "reason": "空输入", "tasks": []}],
            "task_plan": [],
            "completed_tasks": [],
        }

    # 1. 构建可用的 Specialist 描述
    specialist_descriptions = [
        "- log_analyzer: 日志分析专家。当问题涉及错误日志、异常堆栈、服务故障排查时使用。",
        "- monitor_expert: 监控专家。当问题涉及 CPU、内存、磁盘等资源指标异常时使用。",
        "- knowledge_retriever: 知识库专家。当问题涉及运维经验、最佳实践、历史案例时使用。",
    ]

    # 2. 调用 LLM 做路由决策
    llm = ChatQwen(
        model=config.rag_model,
        api_key=config.dashscope_api_key,
        temperature=0,
    )

    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                dedent("""\
                    你是 AIOps 系统的 Supervisor，负责任务路由和 Specialist 调度。

                    ## 可用 Specialist

                    {specialist_descriptions}

                    ## 路由规则

                    1. **精准选择相关的 Specialist**，避免过度调用浪费资源
                    2. 日志/错误/异常排查必须选择 log_analyzer
                    3. CPU/内存/性能问题必须选择 monitor_expert
                    4. 运维经验/最佳实践/历史案例查询必须选择 knowledge_retriever
                    5. 复杂故障诊断（如"服务不可用"）需要同时选择多个 Specialist
                    6. tasks 是对应每个 Specialist 的具体任务描述，必须一一对应
                    7. **非运维问题**（如问候、闲聊、通用知识）返回空 specialists 列表
                    8. 如果问题模糊但可能与运维相关，优先选择最相关的 1-2 个 Specialist

                    ## 输出格式

                    返回 specialists（列表）、reason（字符串）、tasks（列表）。
                    specialists 和 tasks 必须一一对应。
                """).strip(),
            ),
            ("human", "用户问题: {user_input}"),
        ]
    )

    chain = prompt | llm.with_structured_output(RouteDecision)

    try:
        decision = await chain.ainvoke(
            {
                "specialist_descriptions": "\n".join(specialist_descriptions),
                "user_input": user_input,
            }
        )

        # 解析决策结果
        if isinstance(decision, RouteDecision):
            specialists = decision.specialists
            reason = decision.reason
            tasks = decision.tasks
        else:
            specialists = decision.get("specialists", []) if isinstance(decision, dict) else []
            reason = decision.get("reason", "") if isinstance(decision, dict) else ""
            tasks = decision.get("tasks", []) if isinstance(decision, dict) else []

        logger.info(f"路由决策: {specialists}")
        logger.info(f"决策理由: {reason}")

    except Exception as e:
        logger.error(f"路由决策失败: {e}", exc_info=True)
        specialists = ["log_analyzer", "monitor_expert", "knowledge_retriever"]
        reason = f"LLM 路由失败，使用默认路由: {str(e)}"
        tasks = [
            "查询并分析系统日志",
            "查询并分析监控指标",
            "检索相关运维知识",
        ]

    # 3. 更新状态
    routing_record = {
        "specialists": specialists,
        "reason": reason,
        "timestamp": _now_iso(),
    }

    return {
        "routing": [routing_record],
        "task_plan": tasks,
        "completed_tasks": [],
    }


# ========== 子图构建函数 ==========

def build_specialist_subgraph(name: str, agent: BaseSpecialist) -> StateGraph:
    """
    为每个 Specialist 构建一个简单的子图
    
    结构：START -> run_specialist -> END
    
    参数：
        name: 子图名称（如 "log_analyzer"）
        agent: Specialist 实例
    
    返回：
        编译后的 LangGraph 子图
    """
    async def run_specialist(state: MultiAgentState) -> Dict[str, Any]:
        """子图节点：运行 Specialist"""
        return await agent.run(state)

    subgraph = StateGraph(MultiAgentState)
    subgraph.add_node("run", run_specialist)
    subgraph.add_edge(START, "run")
    subgraph.add_edge("run", END)

    return subgraph.compile()


# ========== 并行执行辅助 ==========

async def _run_parallel(
    subgraphs: Dict[str, StateGraph],
    specialists: List[str],
    state: MultiAgentState,
) -> List[Tuple[str, Dict[str, Any]]]:
    """
    并行执行多个 Specialist 子图
    
    使用 asyncio.gather 实现并行执行，无依赖的 Specialist 同时运行。
    每个 Specialist 的结果作为 (name, result) 元组返回。
    """
    async def run_one(name: str) -> Tuple[str, Dict[str, Any]]:
        try:
            result = await subgraphs[name].ainvoke(state)
            return name, result
        except Exception as e:
            logger.error(f"Specialist {name} 执行异常: {e}")
            return name, {"error": str(e)}

    tasks = [run_one(name) for name in specialists if name in subgraphs]
    if not tasks:
        return []

    results = await asyncio.gather(*tasks, return_exceptions=False)
    return list(results)


# ========== 时间辅助 ==========

def _now_iso() -> str:
    """返回当前 UTC 时间的 ISO 格式字符串"""
    return datetime.now(timezone.utc).isoformat()