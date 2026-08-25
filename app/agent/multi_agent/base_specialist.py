"""Specialist Agent 基类

设计决策：
1. 抽象基类确保所有 Specialist 都有统一的 run() 接口
2. LLM 延迟创建（property），不需要 LLM 的 Specialist 不会白白占资源
3. 提供 run_with_tools() 通用 ReAct 辅助方法，让 Specialist 自主选工具
4. Mem0 记忆注入在 run() 中统一完成，子类 _execute() 无需关心
"""

import json
from abc import ABC, abstractmethod
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import BaseTool
from langgraph.prebuilt import ToolNode
from loguru import logger

from app.agent.multi_agent.state import MultiAgentState
from app.core.llm_factory import llm_factory
from app.core.mem0_manager import asearch_memory


class BaseSpecialist(ABC):
    """Specialist Agent 抽象基类"""

    def __init__(self, name: str, description: str):
        self.name = name
        self.description = description
        self._llm: BaseChatModel | None = None  # 延迟创建

    @property
    def llm(self) -> BaseChatModel:
        """延迟创建 LLM 实例，不需要 LLM 的 Specialist 不会触发创建"""
        if self._llm is None:
            self._llm = llm_factory.create_chat_model(
                temperature=0,
                streaming=False,
            )
        return self._llm

    @abstractmethod
    async def _execute(self, state: MultiAgentState) -> dict[str, Any]:
        """子类必须实现：Specialist 的核心执行逻辑"""
        ...

    async def run(self, state: MultiAgentState) -> dict[str, Any]:
        """执行 Specialist 的完整流程（统一异常包装 + Mem0 记忆注入）

        注意：Mem0 记忆注入统一在这里完成。
        子类的 _execute() 收到的 state["user_input"] 已经包含历史经验，
        不需要自己再查一次 Mem0。
        """
        logger.info(f"=== {self.name} 开始执行 ===")

        try:
            # === Mem0 记忆注入：在 _execute 之前把历史经验塞进 user_input ===
            user_input = state.get("specialist_task") or state.get("user_input", "")
            working_state = dict(state)
            working_state["user_input"] = user_input
            if user_input:
                memory_context = await asearch_memory(query=user_input, limit=3)
                if memory_context:
                    working_state["user_input"] = f"{user_input}\n\n{memory_context}"
                    logger.info(
                        f"[{self.name}] 注入 {len(memory_context)} 字记忆上下文"
                    )

            result = await self._execute(working_state)
            result.setdefault("specialist_name", self.name)
            result.setdefault("status", "success")
            logger.info(f"=== {self.name} 执行完成 ===")
            return result

        except Exception as e:
            logger.error(f"{self.name} 执行失败: {e}", exc_info=True)
            return {
                "specialist_name": self.name,
                "status": "error",
                "error": str(e),
            }

    async def run_with_tools(
        self,
        task: str,
        tools: list[BaseTool],
        system_prompt: str,
        max_steps: int = 2,
    ) -> tuple[str, list[dict[str, Any]]]:
        """有界 ReAct 循环：让 LLM 自主选工具并执行

        这是一个通用的工具调用辅助方法，Specialist 不再硬编码调哪个工具，
        而是把可用工具列表交给 LLM，由 LLM 决定调用哪个工具、传什么参数。

        与 Plan-Execute-Replan 的 Executor 区别：
        - 这里只给 Specialist 领域相关的工具子集（而非全部工具）
        - max_steps 限制为 2，避免无限循环
        - LLM 选完工具并执行后，直接基于结果生成分析摘要

        Args:
            task: 要执行的任务描述
            tools: 可用工具列表（领域相关子集）
            system_prompt: Specialist 的角色提示词
            max_steps: 最大工具调用轮次（默认 2）

        Returns:
            LLM 分析文本，以及供前端结构化渲染的工具调用轨迹
        """
        llm_with_tools = self.llm.bind_tools(tools)
        tool_node = ToolNode(tools)

        messages: list = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=task),
        ]
        tool_traces: list[dict[str, Any]] = []

        for step in range(max_steps):
            response = await llm_with_tools.ainvoke(messages)

            if not hasattr(response, "tool_calls") or not response.tool_calls:
                # LLM 认为不需要工具，直接返回分析
                return (
                    response.content if hasattr(response, "content") else str(response),
                    tool_traces,
                )

            # LLM 选择了工具 → 执行
            for tc in response.tool_calls:
                logger.info(f"[{self.name}] 调用工具: {tc['name']}, 参数: {tc['args']}")

            messages.append(response)
            tool_messages = await tool_node.ainvoke({"messages": messages})
            messages.extend(tool_messages["messages"])

            for tool_call, tool_message in zip(
                response.tool_calls, tool_messages["messages"]
            ):
                raw_result = getattr(tool_message, "content", "")
                try:
                    parsed_result = json.loads(raw_result) if isinstance(raw_result, str) else raw_result
                except (json.JSONDecodeError, TypeError):
                    parsed_result = raw_result
                tool_traces.append({
                    "name": tool_call["name"],
                    "args": tool_call.get("args", {}),
                    "result": parsed_result,
                })

            # 检查工具结果中是否有错误
            for msg in tool_messages["messages"]:
                if hasattr(msg, "content") and isinstance(msg.content, str):
                    try:
                        parsed = json.loads(msg.content)
                        if isinstance(parsed, dict) and "error" in parsed:
                            logger.warning(f"[{self.name}] 工具返回错误: {parsed['error']}")
                    except (json.JSONDecodeError, TypeError):
                        pass

        # 达到 max_steps 后，让 LLM 基于已收集的数据做最终分析
        logger.info(f"[{self.name}] 工具调用达到上限({max_steps})，生成最终分析")
        final_response = await self.llm.ainvoke(messages)
        return (
            final_response.content if hasattr(final_response, "content") else str(final_response),
            tool_traces,
        )

    async def get_tools_by_names(
        self,
        all_tools: list[BaseTool],
        names: list[str],
    ) -> list[BaseTool]:
        """从全部工具中筛选出本 Specialist 需要的工具子集"""
        tool_map = {tool.name: tool for tool in all_tools}
        return [tool_map[name] for name in names if name in tool_map]
