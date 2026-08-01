"""通用 Plan-Execute-Replan 服务

基于 LangGraph 官方教程实现。
使用 LangGraph 原生 checkpointer（AsyncSqliteSaver / AsyncPostgresSaver）
替代手搓 storage + MemorySaver 混用方案。

持久化机制：
- LangGraph 在每个节点执行后自动通过 checkpointer 保存 checkpoint
- 状态包含完整 metadata（当前节点、任务队列、通道值等）
- 重启后从最后一个 checkpoint 恢复，可精确续接执行
"""

from typing import AsyncGenerator, Dict, Any
from langgraph.graph import StateGraph, END
from loguru import logger

from app.agent.aiops import PlanExecuteState, planner, executor, replanner
from app.core.checkpointer import get_checkpointer, thread_id_with_prefix
from app.core.mem0_manager import search_memory, save_memory


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
        session_id: str = "default"
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """执行 Plan-Execute-Replan 流程（统一 checkpointer 持久化）

        Args:
            user_input: 用户的任务描述
            session_id: 会话ID

        Yields:
            Dict[str, Any]: 流式事件
        """
        graph = await self._get_graph()
        thread_id = thread_id_with_prefix(session_id, "aiops")
        config_dict = {"configurable": {"thread_id": thread_id}}

        # === Mem0 记忆注入 ===
        memory_context = search_memory(query=user_input, limit=3)
        augmented_input = user_input
        if memory_context:
            augmented_input = f"{user_input}\n\n{memory_context}"
            logger.info(f"[会话 {session_id}] AIOps 注入 {len(memory_context)} 字记忆上下文")
        # === 结束 ===

        logger.info(f"[会话 {session_id}] 开始执行任务: {user_input}")

        try:
            # 从 checkpointer 恢复历史状态
            snapshot = await graph.aget_state(config_dict)
            if snapshot and snapshot.values:
                initial_state = dict(snapshot.values)
                initial_state["input"] = augmented_input
                # 清空旧响应，让 replanner 重新评估（新任务可能不同）
                initial_state["response"] = ""
                logger.info(
                    f"[会话 {session_id}] 从 checkpoint 恢复状态，"
                    f"past_steps: {len(initial_state.get('past_steps', []))} 条"
                )
            else:
                initial_state: PlanExecuteState = {
                    "input": augmented_input,
                    "plan": [],
                    "past_steps": [],
                    "response": ""
                }
                logger.info(f"[会话 {session_id}] 无历史状态，全新执行")

            async for event in graph.astream(
                input=initial_state,
                config=config_dict,
                stream_mode="updates"
            ):
                for node_name, node_output in event.items():
                    logger.info(f"节点 '{node_name}' 输出事件")

                    if node_name == NODE_PLANNER:
                        yield self._format_planner_event(node_output)
                    elif node_name == NODE_EXECUTOR:
                        yield self._format_executor_event(node_output)
                    elif node_name == NODE_REPLANNER:
                        yield self._format_replanner_event(node_output)

            # 获取最终状态（LangGraph 已自动持久化 checkpoint）
            final_state = await graph.aget_state(config_dict)
            final_response = ""
            if final_state and final_state.values:
                final_response = final_state.values.get("response", "")

            # === 保存 AIOps 诊断结果到 Mem0 ===
            try:
                if final_response.strip():
                    save_memory(
                        messages=[
                            {"role": "user", "content": user_input[:1000]},
                            {"role": "assistant", "content": final_response[:2000]},
                        ],
                        metadata={"type": "aiops_diagnosis", "session_id": session_id},
                    )
            except Exception as e:
                logger.warning(f"[会话 {session_id}] 保存 AIOps 记忆失败（不影响主流程）: {e}")
            # === 结束 ===

            yield {
                "type": "complete",
                "stage": "complete",
                "message": "任务执行完成",
                "response": final_response
            }

            logger.info(f"[会话 {session_id}] 任务执行完成")

        except Exception as e:
            logger.error(f"[会话 {session_id}] 任务执行失败: {e}", exc_info=True)
            yield {
                "type": "error",
                "stage": "error",
                "message": f"任务执行出错: {str(e)}"
            }

    async def diagnose(
        self,
        session_id: str = "default",
        user_input: str | None = None
    ) -> AsyncGenerator[Dict[str, Any], None]:
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

        async for event in self.execute(aiops_task, session_id):
            if event.get("type") == "complete":
                yield {
                    "type": "complete",
                    "stage": "diagnosis_complete",
                    "message": "诊断流程完成",
                    "diagnosis": {
                        "status": "completed",
                        "report": event.get("response", "")
                    }
                }
            else:
                yield event

    # ------------------------------------------------------------------
    # 事件格式化
    # ------------------------------------------------------------------

    def _format_planner_event(self, state: Dict | None) -> Dict:
        if not state:
            return {"type": "status", "stage": "planner", "message": "规划节点执行中"}
        plan = state.get("plan", [])
        return {
            "type": "plan",
            "stage": "plan_created",
            "message": f"执行计划已制定，共 {len(plan)} 个步骤",
            "plan": plan
        }

    def _format_executor_event(self, state: Dict | None) -> Dict:
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

    def _format_replanner_event(self, state: Dict | None) -> Dict:
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


# 全局单例
aiops_service = AIOpsService()
