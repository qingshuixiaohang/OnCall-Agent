"""Multi-Agent 状态定义

设计决策：
1. 使用 TypedDict 定义强类型状态，避免运行时字段名错误
2. messages 使用 Annotated + operator.add 实现自动追加，而不是覆盖
3. 每个 Specialist 有独立的结果字段，避免状态冲突
4. routing 字段记录 Supervisor 的决策历史，便于调试和前端展示
"""

import operator
from typing import Annotated, Any, TypedDict

from langchain_core.messages import BaseMessage


class MultiAgentState(TypedDict):
    """Multi-Agent 共享状态

    数据流：
    用户输入 -> Supervisor 路由 -> Specialist 并行执行 -> 结果汇总 -> 最终报告
    """

    # ========== 输入层 ==========
    messages: Annotated[list[BaseMessage], operator.add]
    """对话消息历史（operator.add 自动追加）"""

    user_input: str
    """用户原始输入（任务描述）"""

    specialist_task: str | None
    """Supervisor 为当前 Specialist 分配的具体任务"""

    # ========== 路由层 ==========
    routing: Annotated[list[dict[str, Any]], operator.add]
    """Supervisor 路由决策历史（每次追加一条记录）"""

    # ========== Specialist 结果层 ==========
    log_analysis: dict[str, Any] | None
    """LogAnalyzer 的分析结果（summary 是 LLM 生成的分析文本）"""

    monitor_metrics: dict[str, Any] | None
    """MonitorExpert 的监控结果（summary 是 LLM 生成的分析文本）"""

    knowledge_context: str | None
    """KnowledgeRetriever 检索到的知识库上下文文本"""

    # ========== 输出层 ==========
    task_plan: list[str]
    """Supervisor 生成的任务计划"""

    completed_tasks: Annotated[list[str], operator.add]
    """已完成的任务列表（operator.add 追加，前端展示进度）"""

    final_report: str | None
    """最终诊断报告（Markdown 格式，由 Aggregator 用 LLM 综合生成）"""

    error: str | None
    """错误信息"""
