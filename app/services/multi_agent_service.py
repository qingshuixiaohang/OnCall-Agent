"""Multi-Agent 服务

对标 app/services/aiops_service.py 的服务层组织方式：
一个服务类 + 全局单例 + _build_workflow/_get_graph/execute 结构。

职责：
1. 组装 Supervisor + 3 个 Specialist 节点
2. 构建主 StateGraph 并编译
3. 提供统一的 execute() 接口供上层调用

设计决策：
1. 主图采用 Supervisor + 并行 Specialist + Aggregator 结构
2. Supervisor 通过 LangGraph Send API 实现 Specialist 并行触发
3. 所有 Specialist 完成后自动汇聚到 aggregator 节点
4. 无依赖 Specialist 真正并行执行，减少总耗时
5. Aggregator 使用 LLM 做跨专家综合分析（而非简单字符串拼接）
6. 使用 LangGraph 原生 checkpointer 持久化

持久化说明：
- 主图使用统一 checkpointer（AsyncSqliteSaver / AsyncPostgresSaver）
- Specialist 节点为无状态执行，不单独持久化
- 每次诊断使用独立 run_id，避免新任务复用旧状态
"""

from collections.abc import AsyncGenerator
from textwrap import dedent
from typing import Any
from uuid import uuid4

from langchain_core.prompts import ChatPromptTemplate
from langgraph.graph import StateGraph
from loguru import logger

from app.agent.multi_agent.knowledge_retriever import KnowledgeRetriever
from app.agent.multi_agent.log_analyzer import LogAnalyzer
from app.agent.multi_agent.monitor_expert import MonitorExpert
from app.agent.multi_agent.state import MultiAgentState
from app.agent.multi_agent.supervisor import supervisor_node
from app.core.checkpointer import get_checkpointer, thread_id_with_prefix
from app.core.diagnosis_report_store import DiagnosisReport, report_store
from app.core.llm_factory import llm_factory
from app.core.mem0_manager import schedule_memory_save
from app.core.observability import langchain_config
from app.core.report_builder import build_report_fields
from app.core.time_context import build_time_context
from app.services.workflow_factory import WorkflowFactory, route_from_supervisor


class MultiAgentService:
    """Multi-Agent 服务

    组装 Supervisor + Specialist 节点，提供统一执行接口。
    graph 延迟编译（等 lifespan 初始化 checkpointer 后）。
    """

    def __init__(self):
        """初始化服务，主图延迟编译"""
        logger.info("初始化 Multi-Agent Service...")

        # 1. 创建 Specialist 实例
        self.log_analyzer = LogAnalyzer()
        self.monitor_expert = MonitorExpert()
        self.knowledge_retriever = KnowledgeRetriever()

        # 主图延迟编译（在 execute 中首次调用时）
        self._workflow = None
        self._graph = None

    def _build_workflow(self) -> StateGraph:
        """构建主工作流（尚未编译）

        结构：START -> supervisor -> [并行 Specialist] -> aggregator -> END
        """
        node_map = {
            "supervisor": supervisor_node,
            "log_analyzer": self.log_analyzer.run,
            "monitor_expert": self.monitor_expert.run,
            "knowledge_retriever": self.knowledge_retriever.run,
            "aggregator": self._aggregate_results,
        }
        return WorkflowFactory.build(node_map, route_fn=route_from_supervisor)

    async def _get_graph(self):
        """获取编译后的主图（延迟编译，带持久化）"""
        if self._graph is None:
            if self._workflow is None:
                self._workflow = self._build_workflow()
            checkpointer = get_checkpointer()
            self._graph = self._workflow.compile(checkpointer=checkpointer)
            logger.info("Multi-Agent 主图已编译（含 checkpointer 持久化）")
        return self._graph

    async def _aggregate_results(self, state: MultiAgentState) -> dict[str, Any]:
        """聚合节点：收集所有 Specialist 的结果，用 LLM 做跨专家综合分析

        与旧版区别：
        - 旧版：把三个 Specialist 的文本拼接在一起（没有交叉推理）
        - 新版：让 LLM 综合所有专家发现，做关联分析和交叉推理
        """
        logger.info("=== 聚合节点：综合分析 Specialist 结果 ===")
        report = await self._generate_final_report(state)
        return {
            "final_report": report,
        }

    async def execute(
        self,
        user_input: str,
        session_id: str = "default",
        run_id: str | None = None,
        resume: bool = False,
    ) -> AsyncGenerator[dict[str, Any]]:
        """执行 Multi-Agent 流程（统一 checkpointer 持久化）"""
        graph = await self._get_graph()
        if resume and not run_id:
            raise ValueError("resume=true 时必须提供 run_id")
        run_id = run_id or uuid4().hex
        thread_id = thread_id_with_prefix(f"{session_id}-{run_id}", "multi")
        config_dict = langchain_config(
            {"configurable": {"thread_id": thread_id}},
            session_id=session_id,
            mode="multi_agent",
            run_id=run_id,
        )

        logger.info(f"[会话 {session_id}] 开始 Multi-Agent 执行: {user_input[:100]}...")
        time_context = build_time_context()
        logger.info(
            "[会话 {}] Multi-Agent Python 统一时间范围: {} 至 {}",
            session_id,
            time_context["log_start"],
            time_context["now"],
        )

        try:
            if resume:
                snapshot = await graph.aget_state(config_dict)
                if not snapshot or not snapshot.values:
                    raise ValueError(f"找不到可恢复的 Multi-Agent 运行: {run_id}")
                initial_state = dict(snapshot.values)
                initial_state["user_input"] = user_input
                initial_state["final_report"] = None
                initial_state["error"] = []
                initial_state.setdefault("time_context", time_context)
                logger.info(f"[会话 {session_id}] 恢复 Multi-Agent 运行: {run_id}")
            else:
                initial_state: MultiAgentState = {
                    "messages": [],
                    "user_input": user_input,
                    "time_context": time_context,
                    "specialist_task": None,
                    "routing": [],
                    "log_analysis": None,
                    "monitor_metrics": None,
                    "knowledge_context": None,
                    "task_plan": [],
                    "completed_tasks": [],
                    "final_report": None,
                    "error": [],
                }
                logger.info(f"[会话 {session_id}] 新建 Multi-Agent 运行: {run_id}")

            async for event in graph.astream(
                initial_state, config=config_dict, stream_mode="updates"
            ):
                for node_name, node_output in event.items():
                    logger.debug(f"节点 '{node_name}' 输出: {node_output}")

                    if node_name == "supervisor":
                        routing_list = node_output.get("routing", [])
                        if routing_list:
                            routing = routing_list[-1]
                            yield {
                                "type": "routing",
                                "specialists": routing.get("specialists", []),
                                "reason": routing.get("reason", ""),
                                "tasks": routing.get("tasks", []),
                                "run_id": run_id,
                            }

                    elif node_name in ["log_analyzer", "monitor_expert", "knowledge_retriever"]:
                        yield {
                            "type": "specialist_result",
                            "name": node_name,
                            "result": node_output,
                            "run_id": run_id,
                        }

            final_state = await graph.aget_state(config_dict)
            final_report = ""
            if final_state and final_state.values:
                final_report = final_state.values.get("final_report", "")

            if not final_report:
                final_report = await self._generate_final_report(initial_state)

            yield {
                "type": "complete",
                "report": final_report,
                "run_id": run_id,
            }

            # === 保存诊断报告（yield 之后，不阻塞收尾）===
            try:
                state_values = final_state.values if final_state and final_state.values else {}
                # 从 routing 决策中提取 fallback service
                routing = state_values.get("routing") or []
                fallback_service = None
                if routing:
                    tasks = routing[-1].get("tasks") or []
                    if tasks:
                        fallback_service = None  # tasks 是自然语言，不直接是服务名
                fields = build_report_fields(
                    report_markdown=final_report,
                    user_input=user_input or "",
                    state_values=state_values,
                    fallback_service=fallback_service,
                )
                report = DiagnosisReport(
                    session_id=session_id,
                    run_id=run_id,
                    mode="multi_agent",
                    severity=fields["severity"],
                    service_name=fields["service_name"],
                    summary=fields["summary"] or (user_input or "")[:200],
                    root_cause=fields["root_cause"],
                    recommendations=fields["recommendations"],
                    findings=fields["findings"],
                    report_markdown=final_report,
                    status="completed",
                )
                await report_store.save(report)
            except Exception as e:
                logger.warning("[会话 {}] 保存诊断报告失败（不影响主流程）: {}", session_id, e)
            # === 结束 ===

            logger.info(f"[会话 {session_id}] Multi-Agent 执行完成")

        except Exception as e:
            logger.error(f"[会话 {session_id}] Multi-Agent 执行失败: {e}", exc_info=True)
            yield {
                "type": "error",
                "message": f"执行失败: {str(e)}",
                "run_id": run_id,
            }

    async def _generate_final_report(self, state: MultiAgentState) -> str:
        """用 LLM 综合所有 Specialist 的结果，生成交叉分析报告

        旧版是字符串拼接（"## 日志分析\\n" + log_summary），
        新版让 LLM 做跨专家关联推理（比如"CPU高 + 日志有OOM → 内存泄漏"）。
        LLM 调用失败时降级为拼接，保证可用性。
        """
        log_analysis = state.get("log_analysis") or {}
        monitor_metrics = state.get("monitor_metrics") or {}
        knowledge_context = state.get("knowledge_context") or ""

        log_summary = log_analysis.get("summary", "") or "无日志分析结果"
        monitor_summary = monitor_metrics.get("summary", "") or "无监控分析结果"
        user_input = state.get("user_input", "")

        # 先尝试 LLM 综合分析
        try:
            report = await self._generate_report_with_llm(
                user_input, log_summary, monitor_summary, knowledge_context
            )
            if report and report.strip():
                return report
        except Exception as e:
            logger.warning(f"LLM 综合分析失败，降级为拼接: {e}")

        # 降级：字符串拼接
        return self._fallback_report(log_summary, monitor_summary, knowledge_context)

    async def get_history(self, session_id: str, run_id: str) -> dict[str, Any] | None:
        """从 Checkpointer 重建 Multi-Agent 诊断时间线。"""
        graph = await self._get_graph()
        thread_id = thread_id_with_prefix(f"{session_id}-{run_id}", "multi")
        snapshot = await graph.aget_state({"configurable": {"thread_id": thread_id}})
        if not snapshot or not snapshot.values:
            return None

        state = snapshot.values
        events: list[dict[str, Any]] = []
        routing = (state.get("routing") or [])[-1:]
        if routing:
            route = routing[0]
            events.append({
                "type": "routing",
                "specialists": route.get("specialists", []),
                "reason": route.get("reason", ""),
                "tasks": route.get("tasks", []),
            })

        specialist_results = (
            ("log_analyzer", state.get("log_analysis")),
            ("monitor_expert", state.get("monitor_metrics")),
        )
        for name, result in specialist_results:
            if result:
                events.append({"type": "specialist_result", "name": name, "result": result})

        knowledge = state.get("knowledge_context")
        if knowledge:
            events.append({
                "type": "specialist_result",
                "name": "knowledge_retriever",
                "result": {"summary": knowledge},
            })

        report = state.get("final_report") or ""
        if report:
            events.append({"type": "complete", "report": report})

        return {
            "mode": "multi",
            "session_id": session_id,
            "run_id": run_id,
            "question": state.get("user_input", ""),
            "events": events,
        }

    async def _generate_report_with_llm(
        self,
        user_input: str,
        log_summary: str,
        monitor_summary: str,
        knowledge_context: str,
    ) -> str:
        """LLM 综合分析：跨专家关联推理 + 最终报告"""
        prompt = ChatPromptTemplate.from_messages([
            ("system", dedent("""\
                你是 AIOps 系统的诊断报告综合分析专家。

                你会收到多个 Specialist（专家）的分析结果，包括：
                - 日志分析专家的结论
                - 监控指标分析专家的结论
                - 知识库检索到的运维经验

                ## 你的任务
                1. 综合所有专家的分析结果，做**跨领域关联推理**
                   - 例如：日志发现 OOM + 监控发现内存持续上升 → 判断为内存泄漏
                   - 例如：日志发现 timeout + 监控发现 CPU 飙高 → 判断为 CPU 饱和导致超时
                2. 生成一份结构化的 Markdown 诊断报告

                ## 报告结构（必须包含）
                - ## 诊断概述：一句话总结系统当前状态
                - ## 交叉分析：各专家发现的关联性分析（这是核心，不要简单罗列）
                - ## 根因判断：基于交叉分析推断的最可能根因
                - ## 处置建议：具体的修复/排查建议
                - ## 后续监控：建议持续关注的关键指标

                ## 注意事项
                - 只基于专家提供的真实数据做分析，不要编造
                - 如果某个专家无数据，在对应位置说明"证据不足"
                - 报告简洁专业，避免冗长
            """).strip()),
            ("human", dedent("""\
                ## 用户原始问题
                {user_input}

                ## 日志分析专家结论
                {log_summary}

                ## 监控指标分析专家结论
                {monitor_summary}

                ## 知识库参考
                {knowledge_context}

                请综合以上所有分析结果，做跨专家关联分析并生成诊断报告。
            """).strip()),
        ])

        llm = llm_factory.create_chat_model(
            temperature=0,
            streaming=False,
        )

        messages = prompt.format_messages(
            user_input=user_input[:500],
            log_summary=log_summary[:2000],
            monitor_summary=monitor_summary[:2000],
            knowledge_context=knowledge_context[:1000]
            if knowledge_context else "无相关知识库文档",
        )

        response = await llm.ainvoke(messages, config=langchain_config())
        report = response.content if hasattr(response, "content") else str(response)
        logger.info(f"LLM 综合分析报告生成完成，长度: {len(report)} 字符")
        # === 新增：保存诊断结果到 Mem0 ===
        try:
            schedule_memory_save(
                messages=[
                    {"role": "user", "content": user_input[:1000]},
                    {"role": "assistant",
                     "content": f"【日志分析】{log_summary[:500]}\n【监控分析】{monitor_summary[:500]}"},
                ],
                metadata={
                    "type": "multi_agent_diagnosis",
                    "log_summary_len": len(log_summary),
                    "monitor_summary_len": len(monitor_summary),
                    "has_knowledge": bool(knowledge_context),
                },
            )
        except Exception as e:
            logger.warning(f"保存到 Mem0 失败（不影响主流程）: {e}")
        # === 结束 ===

        return report

    def _fallback_report(
        self,
        log_summary: str,
        monitor_summary: str,
        knowledge_context: str,
    ) -> str:
        """降级方案：LLM 不可用时用字符串拼接"""
        lines = [
            "# AIOps 诊断报告",
            "",
            "## 日志分析结论",
            log_summary,
            "",
            "## 监控指标分析",
            monitor_summary,
            "",
        ]
        if knowledge_context:
            lines.extend([
                "## 相关知识库",
                knowledge_context[:1000] + "..."
                if len(knowledge_context) > 1000 else knowledge_context,
                "",
            ])
        lines.extend(["## 综合建议", "以上为各 Specialist 的分析结果，请根据实际情况处理。"])
        return "\n".join(lines)

    def to_stream_event(self, event: dict[str, Any]) -> dict[str, Any] | None:
        """将 Multi-Agent 事件标准化为 StreamEvent 格式。"""
        event_type = event.get("type")

        if event_type == "routing":
            specialists = ", ".join(event.get("specialists", []))
            reason = event.get("reason", "")
            return {
                "type": "content",
                "data": f"## 路由决策\n**专家**: {specialists}\n**原因**: {reason}\n\n",
            }
        elif event_type == "specialist_result":
            name = event.get("name", "")
            result = event.get("result", {})
            summary = result.get("summary", "") if isinstance(result, dict) else ""
            return {
                "type": "content",
                "data": f"### {name} 分析完成\n{summary or '已获取分析结果'}\n\n",
            }
        elif event_type == "complete":
            return {"type": "done", "data": event.get("report", "")}
        elif event_type == "error":
            return {"type": "error", "data": event.get("message", "Multi-Agent 诊断失败")}
        return None


# 全局单例
multi_agent_service = MultiAgentService()
