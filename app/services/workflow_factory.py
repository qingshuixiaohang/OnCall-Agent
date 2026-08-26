"""WorkflowFactory - Multi-Agent 工作流构建器

将 StateGraph 的构建与节点装配逻辑从 MultiAgentService 中抽出，
提供可测试的 seam：
- 路由函数是纯函数，可独立测试
- 节点列表可配置，测试时可替换为假节点
"""

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send
from loguru import logger

if TYPE_CHECKING:
    pass

# 三个 Specialist 节点的固定名称
SPECIALIST_NODES = {
    "log_analyzer",
    "monitor_expert",
    "knowledge_retriever",
}


def route_from_supervisor(state: dict[str, Any]) -> list[str | Send]:
    """根据路由决策并行触发 Specialist（纯函数，可测试）

    Args:
        state: 当前图状态（dict），可能含 routing 决策

    Returns:
        list[str | Send]: 若路由到 aggregator 则返回 ["aggregator"],
        否则返回触发各 Specialist 的 Send 指令列表。
    """
    routing = state.get("routing", [])
    if not routing:
        return ["aggregator"]

    specialists = routing[-1].get("specialists", [])
    if not specialists:
        return ["aggregator"]

    user_input = state.get("user_input", "")
    tasks = routing[-1].get("tasks", [])
    return [
        Send(
            specialist,
            {
                "user_input": user_input,
                "specialist_task": tasks[index] if index < len(tasks) else user_input,
                "time_context": state.get("time_context", {}),
            },
        )
        for index, specialist in enumerate(specialists)
    ]


class WorkflowFactory:
    """构建 Multi-Agent 主工作流"""

    @staticmethod
    def build(
        node_map: dict[str, Callable[..., Any]],
        route_fn: Callable[[dict[str, Any]], list[str | Send]] = route_from_supervisor,
    ) -> StateGraph:
        """构建 StateGraph。

        Args:
            node_map: 节点名 → 可调用对象的映射。至少需包含
                supervisor / aggregator 以及各 Specialist。
            route_fn: 路由函数（可注入假实现以便测试）。

        Returns:
            StateGraph: 已注册节点与边、但未编译的工作流。
        """
        workflow = StateGraph(dict)
        for name, callable_ in node_map.items():
            workflow.add_node(name, callable_)

        workflow.add_edge(START, "supervisor")

        # 条件边：从 supervisor 根据路由决策分发到 Specialist 或 aggregator
        workflow.add_conditional_edges(
            "supervisor",
            route_fn,
            {**SPECIALIST_NODES, "aggregator": "aggregator"},
        )

        for specialist in SPECIALIST_NODES:
            workflow.add_edge(specialist, "aggregator")
        workflow.add_edge("aggregator", END)

        logger.info(
            f"构建 Multi-Agent 工作流: nodes={list(node_map.keys())}, "
            f"specialists={sorted(SPECIALIST_NODES)}"
        )
        return workflow
