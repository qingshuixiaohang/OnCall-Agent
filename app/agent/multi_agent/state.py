"""Multi-Agent 状态定义

设计决策：
1. 使用 TypedDict 定义强类型状态，避免运行时字段名错误
2. messages 使用 Annotated + operator.add 实现自动追加，而不是覆盖
3. 每个 Specialist 有独立的结果字段，避免状态冲突
4. routing 字段记录 Supervisor 的决策历史，便于调试和前端展示
"""

from typing import TypedDict, Annotated, List, Dict, Any, Optional
import operator
from langchain_core.messages import BaseMessage


class MultiAgentState(TypedDict):
    """Multi-Agent 共享状态

    数据流：
    用户输入 → Supervisor 路由 → Specialist 子图执行 → 结果汇总 → 最终报告
    """

    # ========== 输入层 ==========
    messages: Annotated[List[BaseMessage], operator.add]
    """
    对话消息历史。
    使用 operator.add 实现追加式更新：新消息会自动追加到列表末尾，
    而不是替换整个列表。这是 LangGraph 的标准模式。
    """

    user_input: str
    """用户原始输入（任务描述）"""

    # ========== 路由层 ==========
    routing: Annotated[List[Dict[str, Any]], operator.add]
    """
    Supervisor 路由决策历史。
    每次路由决策都会追加一条记录，包含：
    {
        "specialist": "log_analyzer",
        "reason": "用户问题涉及日志查询",
        "timestamp": "2026-07-24T10:00:00"
    }
    """

    # ========== Specialist 结果层 ==========
    log_analysis: Optional[Dict[str, Any]]
    """
    LogAnalyzer 的分析结果。
    结构：{
        "topics": [...],      # 查找到的日志主题
        "logs": [...],        # 查询到的日志条目
        "summary": str,       # 日志分析摘要
        "errors": [...],      # 发现的错误模式
        "confidence": float   # 分析置信度 0.0~1.0
    }
    """

    monitor_metrics: Optional[Dict[str, Any]]
    """
    MonitorExpert 的监控结果。
    结构：{
        "cpu": {...},         # CPU 指标
        "memory": {...},      # 内存指标
        "anomalies": [...],   # 检测到的异常
        "summary": str,       # 监控分析摘要
        "confidence": float   # 分析置信度 0.0~1.0
    }
    """

    knowledge_context: Optional[str]
    """
    KnowledgeRetriever 检索到的知识库上下文（格式化文本）。
    这是直接可读的字符串，供 LLM 在生成报告时参考。
    """

    # ========== 输出层 ==========
    task_plan: List[str]
    """
    Supervisor 生成的任务计划（步骤列表）。
    示例：["查日志", "查监控", "查知识库", "生成报告"]
    """

    completed_tasks: Annotated[List[str], operator.add]
    """
    已完成的任务列表。使用 operator.add 追加。
    前端可以用这个字段展示进度。
    """

    final_report: Optional[str]
    """最终诊断报告（Markdown 格式）"""

    error: Optional[str]
    """错误信息（如果有的话）"""