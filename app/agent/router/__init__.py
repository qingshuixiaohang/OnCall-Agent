"""Router Agent

基于 LLM 的意图路由 Agent，负责将用户输入路由到合适的下游 Agent。
"""

import json
import re
from typing import Dict, Any

from langchain_core.messages import HumanMessage, SystemMessage
from loguru import logger

from app.agent.router.prompts import ROUTER_SYSTEM_PROMPT, ROUTER_USER_TEMPLATE
from app.core.llm_factory import llm_factory


class RouterAgent:
    """路由 Agent
    
    只做一次 LLM 分类决策，不执行任何工具调用。
    输出标准化的路由决策 JSON。
    """

    def __init__(self):
        """初始化路由 Agent"""
        self.model = llm_factory.create_chat_model(
            temperature=0.1,
            streaming=False,
        )
        logger.info("Router Agent 初始化完成")

    async def route(self, user_input: str) -> Dict[str, Any]:
        """根据用户输入进行路由决策

        Args:
            user_input: 用户原始输入

        Returns:
            Dict: 包含 target、reason、question 的路由决策
        """
        if not user_input or not user_input.strip():
            logger.warning("Router 收到空输入，默认路由到 rag")
            return {
                "target": "rag",
                "reason": "输入为空，默认走 RAG",
                "question": ""
            }

        try:
            messages = [
                SystemMessage(content=ROUTER_SYSTEM_PROMPT),
                HumanMessage(content=ROUTER_USER_TEMPLATE.format(user_input=user_input))
            ]

            response = await self.model.ainvoke(messages)
            content = response.content if hasattr(response, "content") else str(response)

            logger.info(f"[Router] 原始输出: {content[:200]}")

            return self._parse_routing(content, user_input)

        except Exception as e:
            logger.error(f"[Router] 路由决策失败: {e}", exc_info=True)
            # 失败时降级到 RAG
            return {
                "target": "rag",
                "reason": f"路由决策异常，降级到 RAG: {str(e)}",
                "question": user_input
            }

    def _parse_routing(self, content: str, fallback_input: str) -> Dict[str, Any]:
        """解析 LLM 输出的路由决策

        Args:
            content: LLM 原始输出
            fallback_input: 解析失败时使用的默认问题

        Returns:
            Dict: 标准化的路由决策
        """
        # 先尝试直接解析 JSON
        try:
            parsed = json.loads(content)
            if isinstance(parsed, dict) and "target" in parsed:
                return self._normalize(parsed, fallback_input)
        except json.JSONDecodeError:
            pass

        # 尝试从 Markdown 代码块中提取 JSON
        try:
            # 匹配 ```json ... ``` 或 ``` ... ```
            code_block_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", content)
            if code_block_match:
                parsed = json.loads(code_block_match.group(1))
                if isinstance(parsed, dict) and "target" in parsed:
                    return self._normalize(parsed, fallback_input)
        except (json.JSONDecodeError, AttributeError):
            pass

        # 尝试从文本中提取第一个 JSON 对象
        try:
            json_match = re.search(r"\{[\s\S]*\"target\"[\s\S]*\}", content)
            if json_match:
                parsed = json.loads(json_match.group(0))
                if isinstance(parsed, dict) and "target" in parsed:
                    return self._normalize(parsed, fallback_input)
        except json.JSONDecodeError:
            pass

        # 如果都失败了，做简单的关键词兜底
        target = self._keyword_fallback(content)
        logger.warning(f"[Router] JSON 解析失败，使用关键词兜底: {target}")
        return {
            "target": target,
            "reason": "无法解析 JSON，使用关键词兜底",
            "question": fallback_input
        }

    def _normalize(self, parsed: Dict[str, Any], fallback_input: str) -> Dict[str, Any]:
        """标准化路由决策

        Args:
            parsed: 解析后的 JSON 字典
            fallback_input: 默认问题

        Returns:
            Dict: 标准化的路由决策
        """
        target = parsed.get("target", "rag")
        # 只允许三种目标
        if target not in {"rag", "aiops", "multi_agent"}:
            logger.warning(f"[Router] 非法 target: {target}，降级到 rag")
            target = "rag"

        return {
            "target": target,
            "reason": parsed.get("reason", "无路由理由"),
            "question": parsed.get("question", fallback_input) or fallback_input
        }

    def _keyword_fallback(self, content: str) -> str:
        """关键词兜底策略

        Args:
            content: LLM 原始输出

        Returns:
            str: 兜底目标
        """
        content_lower = content.lower()
        if "multi_agent" in content_lower or "multi-agent" in content_lower or "全面" in content or "协作" in content:
            return "multi_agent"
        if "aiops" in content_lower or "诊断" in content or "日志" in content or "监控" in content or "告警" in content:
            return "aiops"
        return "rag"


# 全局单例
router_agent = RouterAgent()
