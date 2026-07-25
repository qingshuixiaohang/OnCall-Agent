"""监控指标 Specialist

职责：
1. 通过 MCP 工具查询 CPU、内存等监控指标
2. 检测资源使用异常
3. 输出结构化分析结果

设计决策：
1. 不进行复杂阈值判断，把原始指标和简单异常一起交给 LLM 总结
2. 某个指标查询失败不影响另一个指标查询
3. 结果保持 cpu、memory、anomalies、summary、confidence 结构
4. P2 优化：限制指标条数为 5 条，prompt 添加输出长度限制
"""

from typing import Any, Dict, List, Optional
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.prompts import ChatPromptTemplate
from loguru import logger

from app.agent.mcp_client import get_mcp_client_with_retry
from app.agent.multi_agent.state import MultiAgentState
from app.agent.multi_agent.base_specialist import BaseSpecialist


MONITOR_SYSTEM_PROMPT = """\
你是一个专业的监控分析专家。请基于查询到的真实监控指标做分析。

## 输出要求
- 只输出分析结论，不要复述原始指标明细
- 若指标不足，明确说明“证据不足”，不要编造
- 给出异常、可能根因、建议下一步
- 分析不超过 300 字（P2 优化：限制输出长度）
"""

MONITOR_HUMAN_TEMPLATE = """\
用户问题：{user_input}

【CPU 指标（样本数：{cpu_count}）】
{cpu_info}

【内存指标（样本数：{memory_count}）】
{memory_info}

请做监控指标层面的分析。要求：分析不超过 300 字。"""


class MonitorExpert(BaseSpecialist):
    """监控指标 Specialist"""

    def __init__(self) -> None:
        super().__init__(
            name="monitor_expert",
            description="分析系统监控指标，检测资源异常",
        )

    async def _execute(self, state: MultiAgentState) -> Dict[str, Any]:
        user_input = state.get("user_input", "")

        mcp_client = await get_mcp_client_with_retry()
        mcp_tools = await mcp_client.get_tools()
        tool_map = {tool.name: tool for tool in mcp_tools}

        service_name = self._extract_service_name(user_input)

        cpu_data: List[Dict[str, Any]] = []
        memory_data: List[Dict[str, Any]] = []

        # 分别查询，互不影响
        if service_name:
            cpu_data = await self._query_metric(
                tool_map=tool_map,
                tool_name="query_cpu_metrics",
                service_name=service_name,
                metric_name="cpu",
            )
            memory_data = await self._query_metric(
                tool_map=tool_map,
                tool_name="query_memory_metrics",
                service_name=service_name,
                metric_name="memory",
            )

        # LLM 分析
        analysis = await self._analyze_with_llm(user_input, cpu_data, memory_data)

        return {
            "monitor_metrics": {
                "cpu": cpu_data,
                "memory": memory_data,
                "anomalies": analysis.get("anomalies", []),
                "summary": analysis.get("summary", ""),
                "confidence": analysis.get("confidence", 0.0),
            },
            "completed_tasks": [f"完成 monitor_expert 分析"],
        }

    async def _query_metric(
        self,
        tool_map: Dict[str, Any],
        tool_name: str,
        service_name: str,
        metric_name: str,
    ) -> List[Dict[str, Any]]:
        tool = tool_map.get(tool_name)
        if not tool:
            return []

        try:
            raw = await tool.ainvoke(
                {
                    "service_name": service_name,
                    "start_time": "1 hour ago",
                    "end_time": "now",
                }
            )
            return self._parse_metrics(raw)
        except Exception as e:
            logger.warning(f"查询 {metric_name} 指标失败: {e}")
            return []

    async def _analyze_with_llm(
        self,
        user_input: str,
        cpu_data: List[Dict[str, Any]],
        memory_data: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        cpu_info = self._format_metrics(cpu_data, "cpu")
        memory_info = self._format_metrics(memory_data, "memory")

        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", MONITOR_SYSTEM_PROMPT),
                ("human", MONITOR_HUMAN_TEMPLATE),
            ]
        )

        messages = prompt.format_messages(
            user_input=user_input,
            cpu_count=len(cpu_data),
            cpu_info=cpu_info,
            memory_count=len(memory_data),
            memory_info=memory_info,
        )

        response = await self.llm.ainvoke(messages)
        content = response.content if hasattr(response, "content") else str(response)

        return {
            "summary": content,
            "anomalies": self._detect_anomalies(cpu_data, memory_data),
            "confidence": 0.7 if (cpu_data or memory_data) else 0.3,
        }

    def _extract_service_name(self, user_input: str) -> Optional[str]:
        """从用户输入中提取服务名
        
        支持模式：
        - "data-sync-service" / "data_sync_service"
        - "xxx 服务"
        - "service xxx"
        """
        import re
        
        # 匹配连字符/下划线分隔的服务名（包含 -service 或 _service 后缀）
        match = re.search(r'\b[a-z]+[-_][a-z\-_]*service\b', user_input, re.IGNORECASE)
        if match:
            return match.group()
        
        # 匹配 "xxx 服务" 模式
        match = re.search(r'([\w-]+)\s*服务', user_input)
        if match:
            return match.group(1)
        
        # 匹配 "service xxx" 模式
        match = re.search(r'service\s+([\w-]+)', user_input, re.IGNORECASE)
        if match:
            return match.group(1)
        
        # 如果提到 cpu/内存但没有明确服务名，返回 None（让调用方决定）
        if any(kw in user_input.lower() for kw in ["cpu", "内存", "memory"]):
            return None
        
        return None

    def _parse_metrics(self, raw: Any) -> List[Dict[str, Any]]:
        if isinstance(raw, list):
            return [item if isinstance(item, dict) else {"raw": item} for item in raw]
        if isinstance(raw, dict):
            for key in ("data", "metrics", "items", "results"):
                if key in raw and isinstance(raw[key], list):
                    return raw[key]
            return [raw]
        return [{"raw": str(raw)}]

    def _format_metrics(self, metrics: List[Dict[str, Any]], metric_type: str) -> str:
        # P2 优化：只取前 5 条，减少 prompt 长度
        if not metrics:
            return "无数据"
        parts = []
        for i, item in enumerate(metrics[:5], 1):
            parts.append(f"[{i}] {item}")
        return "\n".join(parts)

    def _detect_anomalies(
        self,
        cpu_data: List[Dict[str, Any]],
        memory_data: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        anomalies: List[Dict[str, Any]] = []

        for item in cpu_data:
            value = self._first_usage_value(item)
            if isinstance(value, (int, float)) and value > 90:
                anomalies.append(
                    {
                        "type": "cpu_high",
                        "value": value,
                        "message": f"CPU 使用率过高: {value}%",
                    }
                )

        for item in memory_data:
            value = self._first_usage_value(item)
            if isinstance(value, (int, float)) and value > 90:
                anomalies.append(
                    {
                        "type": "memory_high",
                        "value": value,
                        "message": f"内存使用率过高: {value}%",
                    }
                )

        return anomalies

    def _first_usage_value(self, item: Dict[str, Any]) -> Optional[float]:
        for key in ("value", "usage", "cpu_usage", "memory_usage", "percent"):
            if key in item:
                try:
                    return float(item[key])
                except (TypeError, ValueError):
                    continue
        return None