"""通用 Plan-Execute-Replan 服务

基于 LangGraph 官方教程实现。
使用 LangGraph 原生 checkpointer（AsyncSqliteSaver / AsyncPostgresSaver）
替代手搓 storage + MemorySaver 混用方案。

持久化机制：
- LangGraph 在每个节点执行后自动通过 checkpointer 保存 checkpoint
- 状态包含完整 metadata（当前节点、任务队列、通道值等）
- 重启后从最后一个 checkpoint 恢复，可精确续接执行
"""

from collections.abc import AsyncGenerator
from typing import Any
from uuid import uuid4

from langgraph.graph import END, StateGraph
from loguru import logger

from app.agent.aiops import PlanExecuteState, executor, planner, replanner
from app.core.checkpointer import get_checkpointer, thread_id_with_prefix
from app.core.diagnosis_report_store import DiagnosisReport, report_store
from app.core.mem0_manager import asearch_memory, schedule_memory_save
from app.core.report_builder import build_report_fields

# 节点名称常量
NODE_PLANNER = "planner"
NODE_EXECUTOR = "executor"
NODE_REPLANNER = "replanner"


class AIOpsService:
    """通用 Plan-Execute-Replan 服务（统一 checkpointer 持久化）"""

    def __init__(self):
        """初始化服务（延迟编译 graph，等 lifespan 初始化 checkpointer 后）"""
        self.workflow = self._build_workflow()
        self._graph = None  # CompiledStateGraph，延迟编译缓存
        logger.info("AIOps Service 初始化完成（graph 延迟编译）")

    def _build_workflow(self) -> StateGraph:
        """构建 Plan-Execute-Replan 工作流（尚未编译）"""
        logger.info("构建 AIOps 工作流...")

        workflow = StateGraph(PlanExecuteState)

        # 添加节点
        workflow.add_node(NODE_PLANNER, planner)
        workflow.add_node(NODE_EXECUTOR, executor)
        workflow.add_node(NODE_REPLANNER, replanner)

        # 设置入口点
        workflow.set_entry_point(NODE_PLANNER)

        # 定义边
        workflow.add_edge(NODE_PLANNER, NODE_EXECUTOR)
        workflow.add_edge(NODE_EXECUTOR, NODE_REPLANNER)

        # replanner 的条件边
        def should_continue(state: PlanExecuteState) -> str:
            """判断是否继续执行"""
            if state.get("response"):
                logger.info("已生成最终响应，结束流程")
                return END

            plan = state.get("plan", [])
            if plan:
                logger.info(f"继续执行，剩余 {len(plan)} 个步骤")
                return NODE_EXECUTOR

            logger.info("计划执行完毕，生成最终响应")
            return END

        workflow.add_conditional_edges(
            NODE_REPLANNER,
            should_continue,
            {NODE_EXECUTOR: NODE_EXECUTOR, END: END}
        )

        logger.info("AIOps 工作流构建完成")
        return workflow

    async def _get_graph(self):
        """获取编译后的 graph（延迟编译，带持久化）"""
        if self._graph is None:
            checkpointer = get_checkpointer()
            self._graph = self.workflow.compile(checkpointer=checkpointer)
            logger.info("AIOps graph 已编译（含 checkpointer 持久化）")
        return self._graph

    async def execute(
        self,
        user_input: str,
        session_id: str = "default",
        run_id: str | None = None,
        resume: bool = False,
    ) -> AsyncGenerator[dict[str, Any]]:
        """执行 Plan-Execute-Replan 流程（统一 checkpointer 持久化）

        Args:
            user_input: 用户的任务描述
            session_id: 会话ID

        Yields:
            Dict[str, Any]: 流式事件
        """
        graph = await self._get_graph()
        if resume and not run_id:
            raise ValueError("resume=true 时必须提供 run_id")
        run_id = run_id or uuid4().hex
        thread_id = thread_id_with_prefix(f"{session_id}-{run_id}", "aiops")
        config_dict = {"configurable": {"thread_id": thread_id}}

        # === Mem0 记忆注入 ===
        memory_context = await asearch_memory(query=user_input, limit=3)
        augmented_input = user_input
        if memory_context:
            augmented_input = f"{user_input}\n\n{memory_context}"
            logger.info(f"[会话 {session_id}] AIOps 注入 {len(memory_context)} 字记忆上下文")
        # === 结束 ===

        logger.info(f"[会话 {session_id}] 开始执行任务: {user_input}")

        try:
            if resume:
                snapshot = await graph.aget_state(config_dict)
                if not snapshot or not snapshot.values:
                    raise ValueError(f"找不到可恢复的诊断运行: {run_id}")
                initial_state = dict(snapshot.values)
                initial_state["input"] = augmented_input
                initial_state["response"] = ""
                logger.info(f"[会话 {session_id}] 恢复诊断运行: {run_id}")
            else:
                # 新问题不复用旧 plan/past_steps，避免不同诊断任务互相污染。
                initial_state: PlanExecuteState = {
                    "input": augmented_input,
                    "plan": [],
                    "past_steps": [],
                    "response": "",
                    "last_tool_call": {},
                }
                logger.info(f"[会话 {session_id}] 新建诊断运行: {run_id}")

            async for event in graph.astream(
                input=initial_state,
                config=config_dict,
                stream_mode="updates"
            ):
                for node_name, node_output in event.items():
                    logger.info(f"节点 '{node_name}' 输出事件")

                    if node_name == NODE_PLANNER:
                        event_output = self._format_planner_event(node_output)
                        event_output["run_id"] = run_id
                        yield event_output
                    elif node_name == NODE_EXECUTOR:
                        event_output = self._format_executor_event(node_output)
                        event_output["run_id"] = run_id
                        yield event_output
                    elif node_name == NODE_REPLANNER:
                        event_output = self._format_replanner_event(node_output)
                        event_output["run_id"] = run_id
                        yield event_output

            # 获取最终状态（LangGraph 已自动持久化 checkpoint）
            final_state = await graph.aget_state(config_dict)
            final_response = ""
            if final_state and final_state.values:
                final_response = final_state.values.get("response", "")

            # === 保存 AIOps 诊断结果到 Mem0 ===
            try:
                if final_response.strip():
                    schedule_memory_save(
                        messages=[
                            {"role": "user", "content": user_input[:1000]},
                            {"role": "assistant", "content": final_response[:2000]},
                        ],
                        metadata={"type": "aiops_diagnosis", "session_id": session_id},
                    )
            except Exception as e:
                logger.warning(
                    "[会话 {}] 保存 AIOps 记忆失败（不影响主流程）: {}",
                    session_id,
                    e,
                )
            # === 结束 ===

            yield {
                "type": "complete",
                "stage": "complete",
                "message": "任务执行完成",
                "response": final_response,
                "run_id": run_id,
            }

            # === 保存诊断报告（yield 之后，不阻塞收尾）===
            try:
                state_values = final_state.values if final_state and final_state.values else {}
                fields = build_report_fields(
                    report_markdown=final_response,
                    user_input=user_input or "",
                    state_values=state_values,
                )
                report = DiagnosisReport(
                    session_id=session_id,
                    run_id=run_id,
                    mode="aiops",
                    severity=fields["severity"],
                    service_name=fields["service_name"],
                    summary=fields["summary"] or (user_input or "")[:200],
                    root_cause=fields["root_cause"],
                    recommendations=fields["recommendations"],
                    findings=fields["findings"],
                    report_markdown=final_response,
                    status="completed",
                )
                await report_store.save(report)
            except Exception as e:
                logger.warning("[会话 {}] 保存诊断报告失败（不影响主流程）: {}", session_id, e)
            # === 结束 ===

            logger.info(f"[会话 {session_id}] 任务执行完成")

        except Exception as e:
            logger.error(
                "[会话 {}] 任务执行失败: {}",
                session_id,
                e,
                exc_info=True,
            )
            yield {
                "type": "error",
                "stage": "error",
                "message": f"任务执行出错: {str(e)}",
                "run_id": run_id,
            }

    async def diagnose(
        self,
        session_id: str = "default",
        user_input: str | None = None,
        run_id: str | None = None,
        resume: bool = False,
    ) -> AsyncGenerator[dict[str, Any]]:
        """AIOps 诊断接口（支持自然语言自定义输入）"""
        from textwrap import dedent

        if user_input and user_input.strip():
            aiops_task = user_input.strip()
            logger.info(
                f"[会话 {session_id}] 使用自定义诊断问题: {aiops_task[:100]}..."
            )
        else:
            logger.info(f"[会话 {session_id}] 使用默认全系统告警诊断模板")
            aiops_task = dedent("""诊断当前系统是否存在告警，如果存在告警请详细分析告警原因并生成诊断报告。

诊断步骤建议：
1. 先使用 search_topic_by_service_name 查找相关服务的日志主题
2. 使用 search_log 查询最近的 ERROR 和 WARN 级别日志
3. 使用 query_cpu_metrics 和 query_memory_metrics 检查系统资源
4. 使用 retrieve_knowledge 检索相关运维经验
5. 综合以上信息生成诊断报告

诊断报告请使用 Markdown 格式，包含以下部分：
- 活跃告警清单
- 告警根因分析
- 处理方案建议
- 结论和后续建议

重要提醒：
- 最终输出必须是纯 Markdown 文本，不要包含 JSON 结构
- 所有内容必须基于工具查询的真实数据，严禁编造
- 如果某个步骤失败，在结论中如实说明，不要跳过
- 工具名称必须使用系统提供的精确名称（如 search_log 而不是 query_logs）""")

        async for event in self.execute(
            aiops_task,
            session_id,
            run_id=run_id,
            resume=resume,
        ):
            if event.get("type") == "complete":
                yield {
                    "type": "complete",
                    "stage": "diagnosis_complete",
                    "message": "诊断流程完成",
                    "diagnosis": {
                        "status": "completed",
                        "report": event.get("response", "")
                    },
                    "run_id": event.get("run_id"),
                }
            else:
                yield event

    async def get_history(self, session_id: str, run_id: str) -> dict[str, Any] | None:
        """从 Checkpointer 重建单 Agent 诊断时间线。"""
        graph = await self._get_graph()
        thread_id = thread_id_with_prefix(f"{session_id}-{run_id}", "aiops")
        config_dict = {"configurable": {"thread_id": thread_id}}

        snapshots = []
        async for snapshot in graph.aget_state_history(config_dict):
            snapshots.append(snapshot)
        if not snapshots:
            return None

        events: list[dict[str, Any]] = []
        seen_plans = set()
        processed_steps = 0
        response = ""
        question = ""

        for snapshot in reversed(snapshots):
            state = snapshot.values or {}
            question = question or state.get("input", "")
            plan = state.get("plan", []) or []
            plan_key = tuple(plan)
            if plan and plan_key not in seen_plans:
                events.append({"type": "plan", "plan": list(plan)})
                seen_plans.add(plan_key)

            past_steps = state.get("past_steps", []) or []
            if len(past_steps) > processed_steps:
                for step, _ in past_steps[processed_steps:]:
                    events.append({
                        "type": "step_complete",
                        "current_step": step,
                        "message": "步骤执行完成",
                        "remaining_steps": max(len(plan), 0),
                        "tool_call": state.get("last_tool_call") or {},
                    })
                processed_steps = len(past_steps)

            if state.get("response"):
                response = state["response"]

        if response:
            events.append({"type": "report", "report": response})
            events.append({"type": "complete", "response": response})

        return {
            "mode": "aiops",
            "session_id": session_id,
            "run_id": run_id,
            "question": question,
            "events": events,
        }

    # ------------------------------------------------------------------
    # 事件格式化
    # ------------------------------------------------------------------

    def _format_planner_event(self, state: dict | None) -> dict:
        if not state:
            return {"type": "status", "stage": "planner", "message": "规划节点执行中"}
        plan = state.get("plan", [])
        return {
            "type": "plan",
            "stage": "plan_created",
            "message": f"执行计划已制定，共 {len(plan)} 个步骤",
            "plan": plan
        }

    def _format_executor_event(self, state: dict | None) -> dict:
        if not state:
            return {"type": "status", "stage": "executor", "message": "执行节点运行中"}
        plan = state.get("plan", [])
        past_steps = state.get("past_steps", [])
        if past_steps:
            last_step, _ = past_steps[-1]
            tool_call = state.get("last_tool_call") or {}
            return {
                "type": "step_complete",
                "stage": "step_executed",
                "message": f"步骤执行完成 ({len(past_steps)}/{len(past_steps) + len(plan)})",
                "current_step": last_step,
                "remaining_steps": len(plan),
                "tool_call": tool_call,
            }
        return {"type": "status", "stage": "executor", "message": "开始执行步骤"}

    def _format_replanner_event(self, state: dict | None) -> dict:
        if not state:
            return {"type": "status", "stage": "replanner", "message": "评估节点运行中"}
        response = state.get("response", "")
        plan = state.get("plan", [])
        if response:
            return {
                "type": "report",
                "stage": "final_report",
                "message": "最终报告已生成",
                "report": response
            }
        return {
            "type": "status",
            "stage": "replanner",
            "message": f"评估完成，{'继续执行剩余步骤' if plan else '准备生成最终响应'}",
            "remaining_steps": len(plan)
        }

    def to_stream_event(self, event: dict[str, Any]) -> dict[str, Any] | None:
        """将 AIOps 事件标准化为 StreamEvent 格式。"""
        event_type = event.get("type")

        if event_type == "status":
            return {"type": "content", "data": f"⏳ {event.get('message', '')}\n"}
        elif event_type == "plan":
            plan = event.get("plan", [])
            plan_text = "\n".join([f"- {p}" for p in plan]) if isinstance(plan, list) else str(plan)
            return {"type": "content", "data": f"## 执行计划\n{plan_text}\n\n"}
        elif event_type == "step_complete":
            return {"type": "content", "data": f"✅ {event.get('message', '')}\n"}
        elif event_type == "report":
            return {"type": "content", "data": f"## 诊断报告\n\n{event.get('report', '')}\n"}
        elif event_type == "complete":
            diagnosis = event.get("diagnosis", {})
            report = diagnosis.get("report", "") or event.get("response", "")
            return {"type": "done", "data": report}
        elif event_type == "error":
            return {"type": "error", "data": event.get("message", "AIOps 诊断失败")}
        return None


# 全局单例
aiops_service = AIOpsService()
