"""
Planner 节点：制定执行计划
基于 LangGraph 官方教程实现
"""

from textwrap import dedent
from typing import Dict, Any, List
from langchain_core.prompts import ChatPromptTemplate
from langchain_qwq import ChatQwen
from pydantic import BaseModel, Field
from loguru import logger

from app.config import config
from app.tools import get_current_time, retrieve_knowledge
from app.agent.mcp_client import get_mcp_client_with_retry
from .state import PlanExecuteState
from .utils import format_tools_description


class Plan(BaseModel):
    """计划的输出格式"""
    steps: List[str] = Field(
        description="完成任务所需的不同步骤。这些步骤应该按顺序执行，每一步都建立在前一步的基础上。"
    )


# Planner 提示词
planner_prompt = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            dedent("""
                作为一个专家级别的 AIOps 规划者，你需要将复杂的运维诊断任务分解为可执行的步骤。

                ## 可用工具

                以下是当前系统中实际可用的工具列表（由 Executor 负责调用）：

                {tools_description}

                注意：你的职责是制定计划，实际的工具调用由 Executor 负责执行。计划中的步骤必须引用上述列表中**精确的工具名称**，禁止编造不存在的工具名。

                {experience_context}

                ## 制定计划的要求

                对于给定的任务，请创建一个简单的、逐步的计划来完成它。计划应该：

                1. **将任务分解为逻辑上独立的步骤** - 每个步骤应完成一个明确的目标
                2. **明确引用可用工具** - 步骤描述中必须使用上面列出的精确工具名，禁止编造工具名（如 query_logs、get_metrics、TextToSearchLogQuery 等）
                3. **提供工具参数** - 尽可能在步骤中给出具体的参数值（如服务名、查询条件等）
                4. **保持步骤间的依赖关系** - 后续步骤应引用前面步骤的输出（如 topic_id）
                5. **遵循标准工作流** - 参考下面的工作流模板
                6. **参考经验文档** - 如果提供了经验文档，优先参考其中的方法和步骤

                ## 标准工作流模板

                ### 日志查询工作流（必须严格遵循此顺序）
                步骤N: 使用 search_topic_by_service_name 查找目标服务的日志主题，获取 topic_id（参数: service_name="服务名", fuzzy=True）
                步骤N+1: 使用 get_current_timestamp 获取当前时间戳（毫秒）
                步骤N+2: 使用 search_log 查询日志（参数: topic_id=步骤N获取的ID, query="查询条件", start_time=计算值, end_time=当前时间戳）

                禁止跳过 search_topic_by_service_name 直接调用 search_log！
                禁止在 search_log 中传入编造的 topic_id（如 "topic-1234567890"）！

                ### 监控指标查询工作流
                步骤N: 使用 query_cpu_metrics 查询 CPU 使用率（参数: service_name="服务名", start_time="YYYY-MM-DD HH:MM:SS", end_time="YYYY-MM-DD HH:MM:SS"）
                步骤N: 使用 query_memory_metrics 查询内存使用率（参数同上）

                ### 知识检索工作流
                步骤N: 使用 retrieve_knowledge 从知识库检索相关运维经验（参数: query="问题描述"）

                ### 时间工具
                步骤N: 使用 get_current_time 获取格式化的当前时间（参数: timezone="Asia/Shanghai"）

                ## 示例

                示例输入："诊断 data-sync-service 服务是否存在性能问题"
                示例输出（基于实际工具）：
                步骤1: 使用 search_topic_by_service_name 查找 data-sync-service 的日志主题，参数: service_name="data-sync-service", fuzzy=True
                步骤2: 使用 get_current_timestamp 获取当前时间戳（毫秒）
                步骤3: 使用 search_log 查询最近30分钟的错误日志，参数: topic_id=步骤1获取的topic_id, query="level:ERROR OR level:WARN", start_time=当前时间-30*60*1000, end_time=步骤2获取的时间戳, limit=50
                步骤4: 使用 query_cpu_metrics 查询 data-sync-service 最近1小时的 CPU 使用率，参数: service_name="data-sync-service"
                步骤5: 使用 query_memory_metrics 查询 data-sync-service 最近1小时的内存使用率，参数: service_name="data-sync-service"
                步骤6: 综合以上日志和监控数据，分析性能问题的根因并生成诊断报告

                示例输入："查询所有 ERROR 级别的日志"
                示例输出：
                步骤1: 使用 search_topic_by_service_name 查找日志主题，参数: service_name="data-sync-service", fuzzy=True
                步骤2: 使用 get_current_timestamp 获取当前时间戳
                步骤3: 使用 search_log 查询 ERROR 日志，参数: topic_id=步骤1获取的topic_id, query="level:ERROR", start_time=当前时间-60*60*1000, end_time=步骤2获取的时间戳

                ## 重要提醒

                - 所有工具名必须来自上面的"可用工具"列表，禁止编造
                - 日志查询必须先通过 search_topic_by_service_name 获取 topic_id
                - 绝对不要引用不存在的工具（如 query_logs、get_metrics、query_database、TextToSearchLogQuery 等）
                - 计划步骤数控制在 3-6 个之间，避免过于冗长
            """).strip(),
        ),
        ("placeholder", "{messages}"),
    ]
)


async def planner(state: PlanExecuteState) -> Dict[str, Any]:
    """
    规划节点：根据用户输入生成执行计划

    流程：
    1. 先查询内部文档，获取相关经验和最佳实践
    2. 基于经验文档和可用工具制定执行计划
    """
    logger.info("=== Planner：制定执行计划 ===")

    input_text = state.get("input", "")
    logger.info(f"用户输入: {input_text}")

    try:
        # 步骤1: 查询内部文档获取相关经验
        logger.info("查询内部文档，寻找相关经验...")
        experience_docs = ""
        try:
            # retrieve_knowledge 使用 response_format="content_and_artifact"
            # ainvoke() 只返回 content（字符串），不是元组
            context_str = await retrieve_knowledge.ainvoke({"query": input_text})
            if context_str and context_str.strip():
                experience_docs = context_str
                logger.info(f"找到相关经验文档，长度: {len(experience_docs)}")
            else:
                logger.info("未找到相关经验文档")
        except Exception as e:
            logger.warning("查询内部文档失败: {}", e)

        # 步骤2: 获取可用工具列表
        # 获取本地工具
        local_tools = [
            get_current_time,
            retrieve_knowledge
        ]

        # 获取 MCP 工具
        mcp_client = await get_mcp_client_with_retry()
        mcp_tools = await mcp_client.get_tools()

        # 合并所有工具
        all_tools = local_tools + mcp_tools
        logger.info(f"可用工具数量: 本地 {len(local_tools)} + MCP {len(mcp_tools)}")

        # 格式化工具描述
        tools_description = format_tools_description(all_tools)

        # 步骤3: 格式化经验文档上下文（添加工具名映射警告）
        if experience_docs:
            experience_context = dedent(f"""
                ## 相关经验文档

                以下是从知识库中检索到的相关经验和最佳实践，请参考这些经验制定执行计划：

                {experience_docs}

                ---
                注意：经验文档中可能使用了一些通用的工具名称（如 query_logs、get_metrics 等），
                但实际可用的工具以上面列表中列出的为准。请将文档中的工具名映射到实际工具：
                - query_logs -> search_log（需要先通过 search_topic_by_service_name 获取 topic_id）
                - get_metrics -> query_cpu_metrics 或 query_memory_metrics
                - get_current_time -> 实际工具名可能是 get_current_time 或 get_current_timestamp，请以上面列表为准
            """).strip()
        else:
            experience_context = ""

        # 步骤4: 创建 LLM 并生成计划
        llm = ChatQwen(
            model=config.rag_model,
            api_key=config.dashscope_api_key,
            temperature=0
        )

        planner_chain = planner_prompt | llm.with_structured_output(Plan)

        # 调用 LLM 生成计划
        plan_result = await planner_chain.ainvoke({
            "messages": [("user", input_text)],
            "tools_description": tools_description,
            "experience_context": experience_context
        })

        # 提取步骤列表
        if isinstance(plan_result, Plan):
            plan_steps = plan_result.steps
        else:
            # 如果返回的是字典，提取 steps 字段
            plan_steps = plan_result.get("steps", [])  # type: ignore

        logger.info(f"计划已生成，共 {len(plan_steps)} 个步骤")
        for i, step in enumerate(plan_steps, 1):
            logger.info(f"  步骤{i}: {step}")

        return {"plan": plan_steps}

    except Exception as e:
        logger.error("生成计划失败: {}", e, exc_info=True)
        # 返回一个默认计划
        return {
            "plan": [
                "使用 retrieve_knowledge 检索相关运维经验",
                "使用 search_topic_by_service_name 查找相关服务的日志主题",
                "使用 search_log 查询最近的错误和警告日志",
                "使用 query_cpu_metrics 和 query_memory_metrics 检查系统资源使用情况",
                "综合以上信息分析问题根因并生成诊断报告"
            ]
        }
