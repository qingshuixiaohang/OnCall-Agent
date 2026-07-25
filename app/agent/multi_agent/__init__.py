"""Multi-Agent 入口

职责：
1. 组装 Supervisor + 3 个 Specialist 子图
2. 构建主 StateGraph 并编译
3. 提供统一的 execute() 接口供上层调用

设计决策（P1 优化）：
1. 主图采用 Supervisor + 并行 Specialist + Aggregator 结构
2. Supervisor 通过 LangGraph Send API 实现 Specialist 并行触发
3. 所有 Specialist 完成后自动汇聚到 aggregator 节点
4. 无依赖 Specialist 真正并行执行，减少总耗时
5. 提供 async_generator 风格的 execute()，与现有 aiops_service.py 兼容
"""

from typing import AsyncGenerator, Dict, Any, List, Union
from langgraph.constants import Send
from langgraph.graph import END, START, StateGraph
from langgraph.checkpoint.memory import MemorySaver
from loguru import logger

from app.agent.multi_agent.state import MultiAgentState
from app.agent.multi_agent.supervisor import supervisor_node
from app.agent.multi_agent.log_analyzer import LogAnalyzer
from app.agent.multi_agent.monitor_expert import MonitorExpert
from app.agent.multi_agent.knowledge_retriever import KnowledgeRetriever
from app.agent.multi_agent.supervisor import build_specialist_subgraph, _run_parallel


class MultiAgentService:
    """
    Multi-Agent 服务
    
    组装 Supervisor + Specialist 子图，提供统一执行接口。
    """

    def __init__(self):
        """初始化服务，预编译所有子图"""
        logger.info("初始化 Multi-Agent Service...")

        # 1. 创建 Specialist 实例
        self.log_analyzer = LogAnalyzer()
        self.monitor_expert = MonitorExpert()
        self.knowledge_retriever = KnowledgeRetriever()

        # 2. 预编译子图
        self.subgraphs = {
            "log_analyzer": build_specialist_subgraph("log_analyzer", self.log_analyzer),
            "monitor_expert": build_specialist_subgraph("monitor_expert", self.monitor_expert),
            "knowledge_retriever": build_specialist_subgraph(
                "knowledge_retriever", self.knowledge_retriever
            ),
        }
        logger.info(f"子图编译完成: {list(self.subgraphs.keys())}")

        # 3. 编译主图
        self.graph = self._build_graph()
        logger.info("Multi-Agent 主图编译完成")

    def _build_graph(self) -> StateGraph:
        """
        构建主工作流图
        
        结构：
        START -> supervisor -> [并行 Specialist] -> aggregator -> END
        
        并行机制（P1 优化）：
        - Supervisor 路由决策后，通过 LangGraph Send API 并行触发所有选中的 Specialist
        - 无依赖的 Specialist 真正并行执行，减少总耗时
        - 所有 Specialist 完成后自动汇聚到 aggregator 节点
        """
        workflow = StateGraph(MultiAgentState)

        # 添加节点
        workflow.add_node("supervisor", supervisor_node)
        workflow.add_node("log_analyzer", self.log_analyzer.run)
        workflow.add_node("monitor_expert", self.monitor_expert.run)
        workflow.add_node("knowledge_retriever", self.knowledge_retriever.run)
        workflow.add_node("aggregator", self._aggregate_results)

        # 入口
        workflow.add_edge(START, "supervisor")

        # Supervisor 后的条件边：使用 Send 实现并行路由
        def route_from_supervisor(state: MultiAgentState) -> List[Union[str, Send]]:
            """根据路由决策并行触发 Specialist（P1 优化：支持并行）"""
            routing = state.get("routing", [])
            if not routing:
                return [Send("aggregator", {})]
            
            specialists = routing[-1].get("specialists", [])
            if not specialists:
                return [Send("aggregator", {})]
            
            # 并行触发所有选中的 Specialist
            # 修复：传递 user_input，否则 Specialist 收不到用户问题
            user_input = state.get("user_input", "")
            return [Send(s, {"user_input": user_input}) for s in specialists]

        workflow.add_conditional_edges(
            "supervisor",
            route_from_supervisor,
            {
                "log_analyzer": "log_analyzer",
                "monitor_expert": "monitor_expert",
                "knowledge_retriever": "knowledge_retriever",
                "aggregator": "aggregator",
            }
        )

        # 所有 Specialist 完成后汇聚到 aggregator（P1 优化：fan-in 结构）
        workflow.add_edge("log_analyzer", "aggregator")
        workflow.add_edge("monitor_expert", "aggregator")
        workflow.add_edge("knowledge_retriever", "aggregator")
        workflow.add_edge("aggregator", END)

        # 添加检查点以支持会话持久化
        checkpointer = MemorySaver()
        return workflow.compile(checkpointer=checkpointer)
    
    async def _aggregate_results(self, state: MultiAgentState) -> Dict[str, Any]:
        """
        聚合节点：收集所有 Specialist 的结果并生成最终报告
        
        这个节点会在所有选中的 Specialist 执行完成后运行。
        """
        logger.info("=== 聚合节点：生成最终报告 ===")
        
        report = await self._generate_final_report(state)
        
        return {
            "final_report": report,
            "completed_tasks": state.get("completed_tasks", []),
        }

    async def execute(
        self,
        user_input: str,
        session_id: str = "default",
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        执行 Multi-Agent 流程
        
        Args:
            user_input: 用户的任务描述
            session_id: 会话 ID（用于持久化，当前版本暂未启用）
        
        Yields:
            Dict[str, Any]: 流式事件，包含：
                - {"type": "routing", "specialists": [...], "reason": "..."}
                - {"type": "specialist_result", "name": "...", "result": {...}}
                - {"type": "complete", "report": "..."}
                - {"type": "error", "message": "..."}
        """
        logger.info(f"[会话 {session_id}] 开始 Multi-Agent 执行: {user_input[:100]}...")

        try:
            # 初始化状态
            initial_state: MultiAgentState = {
                "messages": [],
                "user_input": user_input,
                "routing": [],
                "log_analysis": None,
                "monitor_metrics": None,
                "knowledge_context": None,
                "task_plan": [],
                "completed_tasks": [],
                "final_report": None,
                "error": None,
            }

            # 配置会话持久化
            config = {
                "configurable": {
                    "thread_id": session_id
                }
            }

            # 执行主图
            async for event in self.graph.astream(initial_state, config=config, stream_mode="updates"):
                for node_name, node_output in event.items():
                    logger.debug(f"节点 '{node_name}' 输出: {node_output}")

                    if node_name == "supervisor":
                        # 提取路由决策并发送
                        routing_list = node_output.get("routing", [])
                        if routing_list:
                            routing = routing_list[-1]
                            yield {
                                "type": "routing",
                                "specialists": routing.get("specialists", []),
                                "reason": routing.get("reason", ""),
                                "tasks": routing.get("task_plan", []),
                            }

                    elif node_name in ["log_analyzer", "monitor_expert", "knowledge_retriever"]:
                        # Specialist 执行结果
                        yield {
                            "type": "specialist_result",
                            "name": node_name,
                            "result": node_output,
                        }

                    elif node_name == "aggregator":
                        # aggregator 完成
                        pass

            # 从最终状态获取报告（修复：initial_state 不会被 astream 修改）
            final_state = self.graph.get_state(config)
            final_report = ""
            if final_state and final_state.values:
                final_report = final_state.values.get("final_report", "")
            
            if not final_report:
                final_report = await self._generate_final_report(initial_state)
            
            yield {
                "type": "complete",
                "report": final_report,
            }

            logger.info(f"[会话 {session_id}] Multi-Agent 执行完成")

        except Exception as e:
            logger.error(f"[会话 {session_id}] Multi-Agent 执行失败: {e}", exc_info=True)
            yield {
                "type": "error",
                "message": f"执行失败: {str(e)}",
            }

    async def _generate_final_report(self, state: MultiAgentState) -> str:
        """
        生成最终报告：优先简单拼接，失败时降级为 LLM 生成（P0 优化）
        
        优化前：调用 LLM 生成报告，耗时 ~41s
        优化后：简单字符串拼接，耗时 ~0s
        
        仅当拼接结果为空时，才调用 LLM 作为 fallback。
        """
        log_analysis = state.get("log_analysis") or {}
        monitor_metrics = state.get("monitor_metrics") or {}
        knowledge_context = state.get("knowledge_context") or ""
        
        log_summary = log_analysis.get("summary", "") or "无日志分析结果"
        monitor_summary = monitor_metrics.get("summary", "") or "无监控分析结果"
        
        lines = [
            "# AIOps 诊断报告",
            "",
            "## 概述",
            f"本报告基于 {len(state.get('completed_tasks', []))} 个 Specialist 的分析结果生成。",
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
                knowledge_context[:1000] + "..." if len(knowledge_context) > 1000 else knowledge_context,
                "",
            ])
        
        lines.extend([
            "## 综合建议",
            "以上为各 Specialist 的分析结果，请根据实际情况进行处理。",
            "",
        ])
        
        report = "\n".join(lines)
        
        # Fallback：如果拼接结果异常，使用 LLM 生成
        if not report.strip() or report.strip() == "# AIOps 诊断报告":
            logger.warning("拼接报告为空，降级使用 LLM 生成")
            return await self._generate_report_with_llm(state)
        
        return report

    async def _generate_report_with_llm(self, state: MultiAgentState) -> str:
        """
        使用 LLM 生成报告（仅作为 fallback）
        
        保留原有逻辑，仅在简单拼接失败时调用。
        预期极少触发，仅在 Specialist 全部失败时使用。
        """
        from langchain_core.prompts import ChatPromptTemplate
        from textwrap import dedent
        
        log_analysis = state.get("log_analysis") or {}
        monitor_metrics = state.get("monitor_metrics") or {}
        knowledge_context = state.get("knowledge_context") or ""
        
        log_summary = log_analysis.get("summary", "无日志分析结果")
        monitor_summary = monitor_metrics.get("summary", "无监控分析结果")
        
        prompt = ChatPromptTemplate.from_messages([
            ("system", dedent("""\
                你是 AIOps 系统的报告生成专家。
                请基于以下 Specialist 的分析结果，生成一份结构清晰、重点突出的诊断报告。
                
                ## 报告要求
                1. 使用 Markdown 格式
                2. 包含：概述、日志分析结论、监控指标分析、相关知识库、综合结论与建议
                3. 重点突出异常和建议措施
                4. 语气专业、简洁
            """).strip()),
            ("human", dedent("""\
                请基于以下分析结果生成诊断报告：
                
                ### 日志分析结果
                {log_summary}
                
                ### 监控指标分析
                {monitor_summary}
                
                ### 知识库参考
                {knowledge_context}
                
                请生成完整的诊断报告。
            """).strip()),
        ])
        
        try:
            messages = prompt.format_messages(
                log_summary=log_summary[:2000],
                monitor_summary=monitor_summary[:2000],
                knowledge_context=knowledge_context[:1000] if knowledge_context else "无相关知识库文档",
            )
            
            response = await self.log_analyzer.llm.ainvoke(messages)
            report = response.content if hasattr(response, "content") else str(response)
            logger.info(f"LLM 生成最终报告，长度: {len(report)} 字符")
            return report
            
        except Exception as e:
            logger.error(f"LLM 生成报告失败: {e}")
            # 最终降级：极简拼接
            return f"# AIOps 诊断报告\n\n## 日志分析\n{log_summary}\n\n## 监控指标\n{monitor_summary}\n"


# 全局单例
multi_agent_service = MultiAgentService()