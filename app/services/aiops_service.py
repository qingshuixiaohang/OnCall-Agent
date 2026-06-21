"""
通用 Plan-Execute-Replan 服务
基于 LangGraph 官方教程实现
支持持久化存储，重启后保留会话状态
"""

from typing import AsyncGenerator, Dict, Any
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from loguru import logger

from app.agent.aiops import PlanExecuteState, planner, executor, replanner
from app.core.storage_factory import get_storage_engine


# 节点名称常量
NODE_PLANNER = "planner"
NODE_EXECUTOR = "executor"
NODE_REPLANNER = "replanner"


class AIOpsService:
    """通用 Plan-Execute-Replan 服务（支持持久化）"""

    def __init__(self):
        """初始化服务"""
        self.storage = get_storage_engine()
        self.checkpointer = MemorySaver()
        self.graph = self._build_graph()
        logger.info("Plan-Execute-Replan Service 初始化完成")
        logger.info(f"存储后端: {type(self.storage).__name__}")

    def _build_graph(self):
        """构建 Plan-Execute-Replan 工作流"""
        logger.info("构建工作流图...")

        # 创建状态图
        workflow = StateGraph(PlanExecuteState)

        # 添加节点
        workflow.add_node(NODE_PLANNER, planner)      # 制定计划
        workflow.add_node(NODE_EXECUTOR, executor)  # 执行步骤
        workflow.add_node(NODE_REPLANNER, replanner)  # 重新规划

        # 设置入口点
        workflow.set_entry_point(NODE_PLANNER)

        # 定义边
        workflow.add_edge(NODE_PLANNER, NODE_EXECUTOR)     # planner -> executor
        workflow.add_edge(NODE_EXECUTOR, NODE_REPLANNER)   # executor -> replanner

        # replanner 的条件边
        def should_continue(state: PlanExecuteState) -> str:
            """判断是否继续执行"""
            # 如果已经生成了最终响应，结束
            if state.get("response"):
                logger.info("已生成最终响应，结束流程")
                return END

            # 如果还有计划步骤，继续执行
            plan = state.get("plan", [])
            if plan:
                logger.info(f"继续执行，剩余 {len(plan)} 个步骤")
                return NODE_EXECUTOR

            # 计划为空但没有响应，返回 replanner 生成响应
            logger.info("计划执行完毕，生成最终响应")
            return END

        workflow.add_conditional_edges(
            NODE_REPLANNER,
            should_continue,
            {
                NODE_EXECUTOR: NODE_EXECUTOR,
                END: END
            }
        )

        # 编译工作流
        compiled_graph = workflow.compile(checkpointer=self.checkpointer)

        logger.info("工作流图构建完成")
        return compiled_graph

    async def execute(
        self,
        user_input: str,
        session_id: str = "default"
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        执行 Plan-Execute-Replan 流程（支持持久化）

        Args:
            user_input: 用户的任务描述
            session_id: 会话ID

        Yields:
            Dict[str, Any]: 流式事件
        """
        logger.info(f"[会话 {session_id}] 开始执行任务: {user_input}")

        try:
            # 尝试从持久化存储恢复历史状态
            saved_state = await self.storage.get_state(session_id)
            logger.info(f"[会话 {session_id}] 加载历史状态: {'成功' if saved_state else '无历史'}")

            # 初始化或恢复状态
            if saved_state:
                initial_state: PlanExecuteState = dict(saved_state)
                initial_state["input"] = user_input
                logger.info(f"[会话 {session_id}] 已恢复历史状态，past_steps: {len(initial_state.get('past_steps', []))} 条")
            else:
                initial_state: PlanExecuteState = {
                    "input": user_input,
                    "plan": [],
                    "past_steps": [],
                    "response": ""
                }

            # 流式执行工作流
            config_dict = {
                "configurable": {
                    "thread_id": session_id
                }
            }

            async for event in self.graph.astream(
                input=initial_state,
                config=config_dict,
                stream_mode="updates"
            ):
                # 解析事件
                for node_name, node_output in event.items():
                    logger.info(f"节点 '{node_name}' 输出事件")

                    # 根据节点类型生成不同的事件
                    if node_name == NODE_PLANNER:
                        yield self._format_planner_event(node_output)

                    elif node_name == NODE_EXECUTOR:
                        yield self._format_executor_event(node_output)

                    elif node_name == NODE_REPLANNER:
                        yield self._format_replanner_event(node_output)

                    # 每个步骤后自动持久化状态
                    current_state = self.graph.get_state(config_dict)
                    if current_state and current_state.values:
                        await self.storage.save_state(
                            session_id,
                            dict(current_state.values)
                        )
                        logger.debug(f"[会话 {session_id}] 状态已持久化")

            # 获取最终状态
            final_state = self.graph.get_state(config_dict)
            final_response = ""

            # 安全地获取响应（处理 values 可能为 None 的情况）
            if final_state and final_state.values:
                final_response = final_state.values.get("response", "")

            # 发送完成事件
            yield {
                "type": "complete",
                "stage": "complete",
                "message": "任务执行完成",
                "response": final_response
            }

            # 最终状态也要持久化
            if final_state and final_state.values:
                await self.storage.save_state(session_id, dict(final_state.values))
                logger.info(f"[会话 {session_id}] 最终状态已持久化")

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
        """
        AIOps 诊断接口（支持自然语言自定义输入）

        Args:
            session_id: 会话ID
            user_input: 用户自定义的诊断问题（自然语言）。如果为 None 或空字符串，则使用默认的全系统告警诊断模板

        Yields:
            Dict[str, Any]: 诊断过程的流式事件
        """
        from textwrap import dedent

        # 如果用户提供了自定义问题，直接使用
        if user_input and user_input.strip():
            aiops_task = user_input.strip()
            logger.info(f"[会话 {session_id}] 使用自定义诊断问题（前100字符）: {aiops_task[:100]}...")
        else:
            # 使用默认的全系统告警诊断模板
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
            # 转换事件格式以兼容旧的 API
            if event.get("type") == "complete":
                # 将 response 包装为 diagnosis 格式
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

    def _format_planner_event(self, state: Dict | None) -> Dict:
        """格式化 Planner 节点事件"""
        if not state:
            return {
                "type": "status",
                "stage": "planner",
                "message": "规划节点执行中"
            }

        plan = state.get("plan", [])

        return {
            "type": "plan",
            "stage": "plan_created",
            "message": f"执行计划已制定，共 {len(plan)} 个步骤",
            "plan": plan
        }

    def _format_executor_event(self, state: Dict | None) -> Dict:
        """格式化 Executor 节点事件"""
        if not state:
            return {
                "type": "status",
                "stage": "executor",
                "message": "执行节点运行中"
            }

        plan = state.get("plan", [])
        past_steps = state.get("past_steps", [])

        if past_steps:
            last_step, _ = past_steps[-1]
            return {
                "type": "step_complete",
                "stage": "step_executed",
                "message": f"步骤执行完成 ({len(past_steps)}/{len(past_steps) + len(plan)})",
                "current_step": last_step,
                "remaining_steps": len(plan)
            }
        else:
            return {
                "type": "status",
                "stage": "executor",
                "message": "开始执行步骤"
            }

    def _format_replanner_event(self, state: Dict | None) -> Dict:
        """格式化 Replanner 节点事件"""
        if not state:
            return {
                "type": "status",
                "stage": "replanner",
                "message": "评估节点运行中"
            }

        response = state.get("response", "")
        plan = state.get("plan", [])

        if response:
            # 已生成最终响应
            return {
                "type": "report",
                "stage": "final_report",
                "message": "最终报告已生成",
                "report": response
            }
        else:
            # 重新规划
            return {
                "type": "status",
                "stage": "replanner",
                "message": f"评估完成，{'继续执行剩余步骤' if plan else '准备生成最终响应'}",
                "remaining_steps": len(plan)
            }


# 全局单例
aiops_service = AIOpsService()
