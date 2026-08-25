# 仓库结构与模块边界

本文件是当前仓库结构的维护约定。新代码应优先遵循这些边界，避免把新功能继续堆入已有的大文件。

## 顶层目录

| 目录 | 用途 | 不应放置的内容 |
| --- | --- | --- |
| `app/` | FastAPI 后端、Agent 工作流和业务代码 | 本地运行数据、评测结果、前端构建产物 |
| `frontend/` | React + TypeScript 前端源代码 | 后端 API 逻辑 |
| `mcp_servers/` | 可独立启动的 MCP 服务或适配器 | 主应用的业务编排 |
| `aiops-docs/` | 示例运维知识库语料 | 项目开发说明 |
| `docs/` | 架构、开发、评测和设计说明 | RAG 运行时语料 |
| `evals/` | 数据集、评测脚本和可复现说明 | API 实现 |
| `scripts/` | 开发、数据准备和一次性运维脚本 | 应用运行时模块 |

`uploads/`、`volumes/`、`logs/` 是本地运行数据，不能依赖其内容来使代码通过，也不应提交。

## 后端依赖方向

```text
api -> services -> agent nodes / tools / core
                         -> integrations (MCP、Milvus、LLM 等外部系统)
```

- `app/api/` 只处理 HTTP/SSE、请求校验和响应；不要在 Router 中实现工作流。
- `app/services/` 负责一个完整业务用例或工作流的编排，例如 RAG 对话、单 Agent 诊断、多 Agent 诊断。
- `app/agent/` 只放图节点、状态和 Specialist；不得反向导入 `services`。
- `app/core/` 放可复用的配置、持久化、可观测性和安全能力；避免了解具体 API 路由。
- `app/tools/` 放 Agent 可调用的本地工具；外部系统访问通过 MCP 或对应适配器完成。
- 外部网络、数据库连接应在 FastAPI 生命周期或首次实际调用时建立；模块 import 不应连接 Milvus、调用模型或读取远端数据。

## 前端约定

- `features/` 按用户场景组织；通用组件放 `components/`。
- 展示组件、状态映射和 API 调用分文件；不要把网络请求、事件解析和大段 JSX 混在一个组件中。
- `static/` 是兼容层，不新增功能。

## 提交前检查

```powershell
uv run ruff check app evals
uv run pytest
cd frontend
npm run lint
npm run build
```

当前尚未建立完整测试集，因此新增逻辑时应优先补充 `tests/` 中的单元测试或工作流集成测试。
