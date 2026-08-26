# 领域术语表（CONTEXT）

本项目（OnCall-Agent）的共享语言。命名领域概念时使用下列术语，不漂移到同义词。

## 核心概念

- **诊断（diagnosis）**：系统的核心行为。针对系统异常，通过日志分析、监控检查、知识检索生成根因与处理建议的过程。
- **诊断模式（mode）**：诊断的两种途径。`aiops`（单 Agent 计划-执行-重规划）和 `multi_agent`（监督者并行编排多个专家 Agent）。
- **run_id**：一次诊断运行的唯一标识。同一次诊断可被 `resume` 继续。
- **session_id**：前端对话的会话标识。跨多次诊断、多种模式复用。

## Agent / 工作流

- **RAG（检索增强生成）**：从知识库检索相关文档并注入回答，供 Agent 引用内部运维经验。
- **标准事件（StreamEvent）**：所有下游 Agent 产出的统一流式事件格式（`content` / `done` / `error` / `router_info`），由 `RouterService` 透传。
- **路由（routing）**：`RouterService` 根据用户输入决策分发到 RAG / AIOps / Multi-Agent 的过程。
- **工作流构建器（WorkflowFactory）**：Multi-Agent 图的构建 seam，路由函数 `route_from_supervisor` 是纯函数，可独立测试。

## 报告与持久化

- **诊断报告（DiagnosisReport）**：一次诊断的结构化产物。含 service_name、severity、root_cause、recommendations、findings、report_markdown。
- **报告存储（ReportStore）**：持久化诊断报告的独立 SQLite 存储。与 checkpointer 分离，支持过滤与趋势聚合。
- **趋势（trends）**：按 service / severity / date 对诊断报告的历史聚合，用于识别反复出问题的服务。

## 会话与存储

- **thread_id**：LangGraph checkpoint 的隔离键，格式为 `{mode}-{session_id}`（AIOps/Multi 带 `-{run_id}` 后缀）。隐藏在 `SessionStore` 深模块内，不应在 API / 服务层直接解析。
- **SessionStore**：隐藏 thread-id 惯例的会话元数据深模块，提供 list / get / delete 统一接口。
- **知识预取器（KnowledgePrefetcher）**：判断问题是否需预取知识，并注入 `[内部知识库证据]` 的独立模块。