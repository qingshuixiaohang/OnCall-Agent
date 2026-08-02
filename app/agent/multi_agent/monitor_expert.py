"""监控指标 Specialist

职责：
1. 自主选择并调用监控相关 MCP 工具（query_cpu_metrics、query_memory_metrics）
2. 检测资源使用异常
3. 输出结构化分析结果

设计决策：
1. 不再硬编码工具调用，把监控工具子集交给 LLM 自主决策
2. 修复旧版时间格式 bug（旧版传 "1 hour ago" / "now"，MCP Server 只认 "YYYY-MM-DD HH:MM:SS"）
3. LLM 负责从用户输入推断服务名并生成正确格式的时间参数
4. P2 优化：限制指标展示条数为 5 条，prompt 限制输出长度
"""

from typing import Any, Dict, List, Optional
import json
from datetime import datetime, timedelta
from loguru import logger

from app.agent.mcp_client import get_mcp_client_with_retry
from app.agent.multi_agent.state import MultiAgentState
from app.agent.multi_agent.base_specialist import BaseSpecialist


# MonitorExpert 可以使用的工具子集
MONITOR_TOOLS_NAMES = [
    "query_cpu_metrics",
    "query_memory_metrics",
    "get_current_time",
]

MONITOR_SYSTEM_PROMPT = """\
你是一个专业的监控分析专家（MonitorExpert）。

## 你的任务
根据用户的运维问题，自主选择并调用以下监控工具来收集指标数据，然后基于真实数据做分析。

## 可用工具
你只能使用以下工具（不要尝试调用其他工具）：
- query_cpu_metrics: 查询服务的 CPU 使用率监控数据
- query_memory_metrics: 查询服务的内存使用率监控数据
- get_current_time: 获取格式化的当前时间（用于构造 start_time / end_time）

## 工具调用注意事项
1. 从用户问题中自行推断服务名（service_name 参数）
2. 时间参数格式：query_cpu_metrics 和 query_memory_metrics 需要字符串时间格式 "YYYY-MM-DD HH:MM:SS"
   - 先调用 get_current_time 获取当前时间
   - start_time 为 1 小时前的时间
   - end_time 为当前时间
   - 示例: start_time="2026-07-28 14:00:00", end_time="2026-07-28 15:00:00"
3. interval 参数可选，默认 "1m"

## 输出要求
- 只输出分析结论，不要复述原始指标明细
- 给出异常模式、可能根因、建议下一步
- 分析不超过 300 字
"""


class MonitorExpert(BaseSpecialist):
    """监控指标 Specialist"""

    def __init__(self) -> None:
        super().__init__(
            name="monitor_expert",
            description="分析系统监控指标，检测资源异常（自主选工具）",
        )

    async def _execute(self, state: MultiAgentState) -> Dict[str, Any]:
        user_input = state.get("user_input", "")
        mcp_client = await get_mcp_client_with_retry()
        all_mcp_tools = await mcp_client.get_tools()

        # 筛选出监控相关工具子集
        tools = await self.get_tools_by_names(all_mcp_tools, MONITOR_TOOLS_NAMES)
        if not tools:
            logger.warning(f"[{self.name}] 没有 MCP 工具可用，返回降级结果")
            return {
                "monitor_metrics": {
                    "cpu": [],
                    "memory": [],
                    "anomalies": [],
                    "summary": "监控工具不可用，无法执行分析",
                },
                "completed_tasks": [f"完成 {self.name} 分析（降级）"],
            }

        logger.info(f"[{self.name}] 可用工具: {[t.name for t in tools]}")

        # 把用户输入交给 LLM，让它自主选工具、传参数、做分析
        analysis_text, tool_traces = await self.run_with_tools(
            task=user_input,
            tools=tools,
            system_prompt=MONITOR_SYSTEM_PROMPT,
            max_steps=2,
        )

        return {
            "monitor_metrics": {
                "cpu": [],
                "memory": [],
                "anomalies": [],
                "summary": analysis_text,
                "tool_calls": tool_traces,
            },
            "completed_tasks": [f"完成 {self.name} 分析"],
        }
