"""日志分析 Specialist

职责：
1. 通过 MCP 工具查询指定服务的日志主题和日志内容
2. 分析日志中的错误、警告和异常模式
3. 输出结构化分析结果，供 Supervisor 或报告生成器使用

设计决策：
1. 优先复用现有 MCP 工具，保持与现有系统兼容
2. 工具调用失败不抛出异常，返回降级结果
3. 日志分析结果包含 topics、logs、summary、errors、confidence 五个字段
4. P2 优化：限制日志条数为 20 条，prompt 添加输出长度限制
"""

from typing import Any, Dict, List, Optional
import re
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.prompts import ChatPromptTemplate
from loguru import logger

from app.agent.mcp_client import get_mcp_client_with_retry
from app.agent.multi_agent.state import MultiAgentState
from app.agent.multi_agent.base_specialist import BaseSpecialist


ANALYZER_SYSTEM_PROMPT = """\
你是一个专业的日志分析专家。请基于查询到的真实日志内容做分析。

## 输出要求
- 只输出分析结论，不要复述原始日志大段文本
- 若日志不足，明确说明"证据不足"，不要编造
- 给出异常、可能根因、建议下一步
- 分析不超过 300 字（P2 优化：限制输出长度）
"""

ANALYZER_HUMAN_TEMPLATE = """\
用户问题：{user_input}

【日志主题信息】
{topics_info}

【查询到的日志（最多展示 {log_count} 条）】
{logs_info}

请做日志层面的分析。要求：分析不超过 300 字。
"""


class LogAnalyzer(BaseSpecialist):
    """日志分析 Specialist"""

    def __init__(self) -> None:
        super().__init__(
            name="log_analyzer",
            description="分析系统日志，识别错误和异常模式",
        )

    async def _execute(self, state: MultiAgentState) -> Dict[str, Any]:
        user_input = state.get("user_input", "")

        # 获取 MCP 工具
        mcp_client = await get_mcp_client_with_retry()
        mcp_tools = await mcp_client.get_tools()
        tool_map = {tool.name: tool for tool in mcp_tools}

        # 1) 先查日志主题
        topic_id = await self._resolve_topic_id(user_input, tool_map)

        # 2) 再查日志
        logs: List[Dict[str, Any]] = []
        if topic_id:
            logs = await self._query_logs(user_input, topic_id, tool_map)

        # 3) 调用 LLM 做日志分析
        analysis = await self._analyze_with_llm(user_input, topic_id, logs)

        return {
            "log_analysis": {
                "topics": [{"topic_id": topic_id}] if topic_id else [],
                "logs": logs,
                "summary": analysis.get("summary", ""),
                "errors": analysis.get("errors", []),
                "confidence": analysis.get("confidence", 0.0),
            },
            "completed_tasks": [f"完成 log_analyzer 分析"],
        }

    async def _resolve_topic_id(
        self,
        user_input: str,
        tool_map: Dict[str, Any],
    ) -> Optional[str]:
        """根据用户输入解析服务名并查询日志主题"""
        service_name = self._extract_service_name(user_input)
        if not service_name:
            return None

        tool = tool_map.get("search_topic_by_service_name")
        if not tool:
            return None

        try:
            raw = await tool.ainvoke({"service_name": service_name, "fuzzy": True})
            return self._extract_field(raw, ["topic_id", "id"])
        except Exception as e:
            logger.warning(f"查询日志主题失败: {e}")
            return None

    async def _query_logs(
        self,
        user_input: str,
        topic_id: str,
        tool_map: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """查询日志并做简单清洗"""
        search_tool = tool_map.get("search_log")
        time_tool = tool_map.get("get_current_timestamp")
        if not search_tool or not time_tool:
            return []

        try:
            now_raw = await time_tool.ainvoke({})
            now_ms = self._to_milliseconds(now_raw)
            start_ms = now_ms - 60 * 60 * 1000

            raw = await search_tool.ainvoke(
                {
                    "topic_id": topic_id,
                    "query": "level:ERROR OR level:WARN",
                    "start_time": start_ms,
                    "end_time": now_ms,
                    "limit": 50,
                }
            )
            return self._parse_logs(raw)
        except Exception as e:
            logger.warning(f"查询日志失败: {e}")
            return []

    async def _analyze_with_llm(
        self,
        user_input: str,
        topic_id: Optional[str],
        logs: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """基于 LLM 做日志分析，不执行额外工具调用"""
        topics_info = f"topic_id={topic_id}" if topic_id else "未查询到日志主题"
        logs_info = self._format_logs(logs) if logs else "未查询到日志"

        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", ANALYZER_SYSTEM_PROMPT),
                ("human", ANALYZER_HUMAN_TEMPLATE),
            ]
        )

        messages = prompt.format_messages(
            user_input=user_input,
            topics_info=topics_info,
            logs_info=logs_info,
            log_count=len(logs),
        )

        response = await self.llm.ainvoke(messages)
        content = response.content if hasattr(response, "content") else str(response)

        return {
            "summary": content,
            "errors": [log for log in logs if str(log.get("level", "")).upper() in {"ERROR", "FATAL"}],
            "confidence": 0.7 if logs else 0.3,
        }

    # ---------- 以下为工具/文本解析辅助方法 ----------

    def _extract_service_name(self, user_input: str) -> Optional[str]:
        """从用户输入中提取服务名
        
        支持模式：
        - "data-sync-service" / "data_sync_service"
        - "xxx 服务"
        - "service xxx"
        """
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
        
        return None

    def _extract_field(self, raw: Any, candidates: List[str]) -> Optional[str]:
        """从工具返回中提取首个命中的字段"""
        if isinstance(raw, dict):
            for name in candidates:
                if name in raw and raw[name]:
                    return str(raw[name])
        text = str(raw)
        for name in candidates:
            marker = f'"{name}"'
            if marker in text:
                match = re.search(rf'{re.escape(marker)}\s*:\s*"([^"]+)"', text)
                if match:
                    return match.group(1)
        return None

    def _to_milliseconds(self, raw: Any) -> int:
        """把时间工具返回的值尽量转成毫秒时间戳"""
        import time
        try:
            return int(float(str(raw).strip()))
        except Exception:
            return int(time.time() * 1000)

    def _parse_logs(self, raw: Any) -> List[Dict[str, Any]]:
        """尽量把日志结果解析成列表"""
        if isinstance(raw, list):
            return [item if isinstance(item, dict) else {"raw": item} for item in raw]
        if isinstance(raw, dict):
            for key in ("data", "logs", "items", "results"):
                if key in raw and isinstance(raw[key], list):
                    return raw[key]
            return [raw]
        return [{"raw": str(raw)}]

    def _format_logs(self, logs: List[Dict[str, Any]]) -> str:
        # P2 优化：只取前 20 条，减少 prompt 长度
        parts = []
        for i, log in enumerate(logs[:20], 1):
            ts = log.get("timestamp", log.get("time", "N/A"))
            level = log.get("level", "N/A")
            message = log.get("message", log.get("content", log.get("msg", "")))
            parts.append(f"[{i}] {ts} [{level}] {message}")
        return "\n".join(parts)
