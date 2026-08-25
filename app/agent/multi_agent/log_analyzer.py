"""日志分析 Specialist

职责：
1. 自主选择并调用日志相关 MCP 工具（search_topic_by_service_name、search_log 等）
2. 分析日志中的错误、警告和异常模式
3. 输出结构化分析结果

设计决策：
1. 不再硬编码工具调用顺序，而是把可用工具交给 LLM，由 LLM 自主决策
2. 不再用正则提取服务名，由 LLM 在工具调用时自行从用户输入推断
3. 工具调用失败不抛出异常，返回降级结果
4. P2 优化：限制日志展示条数为 20 条，prompt 限制输出长度
"""

from typing import Any

from loguru import logger

from app.agent.mcp_client import get_mcp_client_with_retry
from app.agent.multi_agent.base_specialist import BaseSpecialist
from app.agent.multi_agent.state import MultiAgentState

# LogAnalyzer 可以使用的工具子集（只给日志相关的，不给监控工具）
LOG_TOOLS_NAMES = [
    "search_topic_by_service_name",
    "search_log",
    "get_current_timestamp",
]

ANALYZER_SYSTEM_PROMPT = """\
你是一个专业的日志分析专家（LogAnalyzer）。

## 你的任务
根据用户的运维问题，自主选择并调用以下日志工具来收集信息，然后基于真实数据做分析。

## 可用工具
你只能使用以下工具（不要尝试调用其他工具）：
- search_topic_by_service_name: 根据服务名查找日志主题，获取 topic_id
- search_log: 根据 topic_id 查询日志内容
- get_current_timestamp: 获取当前毫秒时间戳

## 工具调用流程
1. 如果需要查询日志，先调用 search_topic_by_service_name 获取 topic_id
   - 参数: service_name（从用户问题中提取服务名）, fuzzy=True
2. 调用 get_current_timestamp 获取当前时间
3. 调用 search_log 查询日志
   - start_time = 当前时间 - 1*60*60*1000（1小时前）
   - end_time = 当前时间
   - query 建议: "level:ERROR OR level:WARN"
   - limit: 50
4. 基于查询结果做分析

## 输出要求
- 只输出分析结论，不要复述原始日志大段文本
- 从用户问题中自行推断服务名，不需要额外提问
- 若工具返回错误或数据不足，明确说明"证据不足"，不要编造
- 给出异常模式、可能根因、建议下一步
- 分析不超过 300 字
"""


class LogAnalyzer(BaseSpecialist):
    """日志分析 Specialist"""

    # 用于最终结构化输出的字段
    RESULT_KEYS = {
        "topics": [],
        "logs": [],
        "summary": "",
        "errors": [],
    }

    def __init__(self) -> None:
        super().__init__(
            name="log_analyzer",
            description="分析系统日志，识别错误和异常模式（自主选工具）",
        )

    async def _execute(self, state: MultiAgentState) -> dict[str, Any]:
        user_input = state.get("user_input", "")
        mcp_client = await get_mcp_client_with_retry()
        all_mcp_tools = await mcp_client.get_tools()

        # 筛选出日志相关工具子集
        tools = await self.get_tools_by_names(all_mcp_tools, LOG_TOOLS_NAMES)
        if not tools:
            logger.warning(f"[{self.name}] 没有 MCP 工具可用，返回降级结果")
            return {
                "log_analysis": {
                    "topics": [],
                    "logs": [],
                    "summary": "日志工具不可用，无法执行分析",
                    "errors": [],
                },
                "completed_tasks": [f"完成 {self.name} 分析（降级）"],
            }

        logger.info(f"[{self.name}] 可用工具: {[t.name for t in tools]}")

        # 把用户输入交给 LLM，让它自主选工具、传参数、做分析
        analysis_text, tool_traces = await self.run_with_tools(
            task=user_input,
            tools=tools,
            system_prompt=ANALYZER_SYSTEM_PROMPT,
            max_steps=2,
        )

        return {
            "log_analysis": {
                "topics": [],
                "logs": [],
                "summary": analysis_text,
                "errors": [],
                "tool_calls": tool_traces,
            },
            "completed_tasks": [f"完成 {self.name} 分析"],
        }
