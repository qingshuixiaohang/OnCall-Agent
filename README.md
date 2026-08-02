# SuperBizAgent

> 面向企业运维场景的智能 OnCall 平台，集成知识库问答、单 Agent 故障诊断和多 Agent 协同诊断。

[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.109+-green.svg)](https://fastapi.tiangolo.com/)
[![LangGraph](https://img.shields.io/badge/LangGraph-Agent-orange.svg)](https://www.langchain.com/langgraph)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## 项目简介

SuperBizAgent（仓库名：OnCall-Agent）是一个面向企业运维和 OnCall 场景的 AI Agent 系统。它通过 MCP 连接日志、监控等外部工具，结合 RAG 知识库、LangGraph 工作流和长期记忆，辅助用户完成从问题理解、信息检索、工具调用到诊断报告生成的完整流程。

系统当前提供三种使用模式：

1. **智能对话**：基于 RAG Agent 的普通运维问答。Agent 可以检索内部知识库并调用可用的 MCP 工具，支持流式输出和多轮会话。
2. **快速诊断**：基于 Plan-Execute-Replan 的单 Agent 诊断流程。Agent 先制定计划，再逐步执行日志、监控和知识检索任务，根据结果重新评估后生成报告。
3. **全面诊断**：基于 Supervisor + Specialist 的多 Agent 诊断流程。Supervisor 负责任务拆分和专家调度，日志分析、监控分析、知识检索等 Specialist 可以并行工作，最后由 Aggregator 综合结果。

项目重点是辅助分析和诊断，不会在没有明确授权的情况下自动执行删除 Pod、扩容或修改线上配置等破坏性操作。

## 核心能力

| 能力 | 说明 |
|------|------|
| RAG 知识库问答 | 支持 `.md`、`.txt`、`.pdf`、`.docx` 文档上传、分片、向量化、向量召回和语义重排 |
| 单 Agent 诊断 | 使用 Planner、Executor、Replanner 构成可追踪的 Plan-Execute-Replan 工作流 |
| 多 Agent 诊断 | 使用 Supervisor 调度 LogAnalyzer、MonitorExpert、KnowledgeRetriever 等 Specialist，并行收集诊断信息 |
| MCP 工具调用 | 通过 Model Context Protocol 访问 CLS 日志服务和监控服务，支持工具筛选、重试和异常降级 |
| 结构化前端 | React + TypeScript 前端按指标、日志、知识文档和工具调用类型渲染诊断结果 |
| 流式响应 | 普通对话和诊断流程通过 SSE 返回内容、计划、步骤、工具状态和最终报告 |
| 会话持久化 | LangGraph checkpointer 保存会话状态，支持会话列表和历史恢复 |
| 长期记忆 | Mem0 保存跨会话的运维经验，在 RAG、AIOps 和 Multi-Agent 流程中召回相关记忆 |

## 系统架构

```text
浏览器
  │
  ├── React + Vite + TypeScript 前端
  │       ├── 智能对话视图
  │       ├── 单 Agent 诊断时间线
  │       └── 多 Agent 诊断时间线
  │
  ▼
FastAPI 应用（默认端口 9900）
  │
  ├── RAG Agent
  │     ├── LangGraph 对话流程
  │     ├── MCP 工具调用
  │     └── Milvus 检索 + Rerank
  │
  ├── AIOps Agent
  │     └── Planner → Executor → Replanner
  │
  ├── Multi-Agent Service
  │     └── Supervisor → Specialist 并行执行 → Aggregator
  │
  ├── Mem0 长期记忆
  │
  └── LangGraph Checkpointer
        │
        ├── Milvus：知识库文档向量
        ├── Qdrant 本地目录：Mem0 记忆向量
        ├── SQLite：会话状态和 Mem0 操作历史
        └── MCP Servers：日志和监控数据源
```

## 技术栈

| 层级 | 技术 |
|------|------|
| 后端 | Python、FastAPI、Uvicorn |
| Agent 编排 | LangChain、LangGraph |
| 对话模型 | DashScope 兼容接口，模型统一由 `RAG_MODEL` 配置 |
| Embedding | SiliconFlow `BAAI/bge-m3` |
| Rerank | SiliconFlow `BAAI/bge-reranker-v2-m3`，也支持 DashScope 后端 |
| 知识库向量库 | Milvus |
| 长期记忆 | Mem0 + 本地 Qdrant |
| 外部工具协议 | MCP，支持 SSE 和 Streamable HTTP |
| 会话状态 | LangGraph Checkpointer，默认 SQLite |
| 前端 | React、TypeScript、Vite、Tailwind CSS、Lucide React |

## 快速开始

### 环境要求

- Python 3.11 或更高版本
- Node.js 18 或更高版本
- Docker Desktop，用于运行 Milvus
- DashScope API Key
- SiliconFlow API Key
- CLS 和监控 MCP 服务，或指向兼容服务的 MCP 地址

### 1. 获取代码并安装后端依赖

```bash
git clone https://github.com/qingshuixiaohang/OnCall-Agent.git
cd OnCall-Agent

# 推荐使用 uv
uv sync

# 或使用 pip
pip install -e .
```

### 2. 配置环境变量

```bash
cp .env.example .env
```

至少配置以下变量：

```dotenv
DASHSCOPE_API_KEY=your_dashscope_api_key
SILICONFLOW_API_KEY=your_siliconflow_api_key

# 可选：模型
RAG_MODEL=qwen3.7-plus
RERANK_BACKEND=siliconflow
RERANK_MODEL=BAAI/bge-reranker-v2-m3

# 可选：MCP 服务地址
MCP_CLS_TRANSPORT=sse
MCP_CLS_URL=http://localhost:3000/sse
MCP_MONITOR_TRANSPORT=streamable-http
MCP_MONITOR_URL=http://localhost:8004/mcp
```

不要把真实 API Key 提交到 Git 仓库。`.env` 已被 `.gitignore` 忽略。

### 3. 启动 Milvus

```bash
docker compose -f vector-database.yml up -d
```

默认连接地址为 `localhost:19530`。如果使用 Attu，可以访问 `http://localhost:8000` 查看 Milvus 数据。

### 4. 安装并启动前端

```bash
cd frontend
npm install
npm run dev
```

开发前端地址为 `http://localhost:5173`，Vite 会将 `/api` 和 `/mcp` 请求代理到 `http://localhost:9900`。

### 5. 启动后端

在项目根目录执行：

```bash
python app/main.py
```

后端默认地址为 `http://localhost:9900`。生产模式下，先构建前端：

```bash
cd frontend
npm run build
cd ..
python app/main.py
```

构建后的 `frontend/dist` 会由 FastAPI 托管；如果构建目录不存在，后端会回退到旧的 `static/` 目录。

## API 接口

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/chat` | POST | 普通对话，非流式 |
| `/api/chat_stream` | POST | RAG Agent 流式对话，SSE |
| `/api/aiops` | POST | 单 Agent Plan-Execute-Replan 诊断，SSE |
| `/api/aiops_multi` | POST | Supervisor + Specialist 多 Agent 诊断，SSE |
| `/api/router` | POST | 根据问题自动路由到 RAG、AIOps 或 Multi-Agent |
| `/api/upload` | POST | 上传知识库文档 |
| `/api/sessions` | GET | 获取会话列表 |
| `/api/chat/session/{id}` | GET | 获取会话历史 |
| `/api/chat/clear` | POST | 清空会话历史 |
| `/api/health` | GET | 检查应用和 Milvus 健康状态 |

### 普通对话请求

`/api/chat` 和 `/api/chat_stream` 使用 `id`、`question` 字段：

```bash
curl -X POST "http://localhost:9900/api/chat_stream" \
  -H "Content-Type: application/json" \
  -d '{"id":"session-001","question":"看看当前 CPU 有什么问题"}' \
  --no-buffer
```

### 单 Agent 诊断请求

```bash
curl -X POST "http://localhost:9900/api/aiops" \
  -H "Content-Type: application/json" \
  -d '{"session_id":"session-001","question":"诊断 test 服务的 CPU 使用率问题"}' \
  --no-buffer
```

每次未指定 `run_id` 的诊断都会创建一个新的独立运行，避免复用同一会话上一次诊断的计划和执行步骤。如果需要从已保存的工作流继续执行，传入原来的 `run_id` 和 `"resume": true`：

```json
{
  "session_id": "session-001",
  "run_id": "诊断事件中返回的 run_id",
  "resume": true,
  "question": "继续上一次诊断"
}
```

### 多 Agent 诊断请求

```bash
curl -X POST "http://localhost:9900/api/aiops_multi" \
  -H "Content-Type: application/json" \
  -d '{"session_id":"session-002","question":"全面诊断 test 服务当前状态"}' \
  --no-buffer
```

Multi-Agent 诊断同样支持 `run_id` 和 `resume`。Supervisor 返回的每个 Specialist 任务会随路由事件传递给对应专家，专家返回的工具调用轨迹也会随结果事件返回，前端可以据此渲染日志、指标和知识文档组件。

### 上传知识库文档

```bash
curl -X POST "http://localhost:9900/api/upload" \
  -F "file=@aiops-docs/cpu_high_usage.md"
```

## Mem0 与数据存储

项目使用不同存储层承担不同职责：

| 存储 | 用途 | 默认位置或地址 |
|------|------|----------------|
| Milvus | 保存知识库文档向量，服务 RAG 检索 | `localhost:19530`，默认 collection 为 `biz` |
| LangGraph Checkpointer | 保存 Agent 会话状态和工作流检查点 | `volumes/langgraph.db` |
| Mem0 Qdrant | 保存跨会话长期记忆向量 | `volumes/mem0_qdrant/` |
| Mem0 history | 保存 Mem0 的历史操作记录 | `volumes/mem0_history.db` |
| 文件系统 | 保存上传文档和运行时文件 | `uploads/`、`volumes/` |

Mem0 的使用流程是：请求进入 Agent 后先按持久化用户标识召回相关经验；Agent 完成回答或诊断后，再将本轮问题和结果写入 Mem0。Mem0 的写入失败会记录警告，但不会阻断主流程。

## 诊断流程

### 快速诊断：Plan-Execute-Replan

```text
用户问题
   ↓
Planner：生成诊断计划
   ↓
Executor：选择工具并执行当前步骤
   ↓
Replanner：评估结果，决定继续执行或生成报告
   ↓
最终诊断报告
```

### 全面诊断：Supervisor + Specialist

```text
用户问题
   ↓
Supervisor：分析问题并选择专家
   ├── LogAnalyzer：分析日志和日志主题
   ├── MonitorExpert：分析 CPU、内存等监控指标
   └── KnowledgeRetriever：检索运维经验和最佳实践
   ↓
Aggregator：关联分析并生成综合报告
```

诊断过程中，前端会将计划、步骤、工具状态、指标图表、日志表格、知识文档和最终报告分别渲染，便于用户追踪 Agent 当前进度和判断依据。

## 项目结构

```text
OnCall-Agent/
├── app/
│   ├── main.py                         # FastAPI 应用入口和前端托管
│   ├── api/                            # API 路由
│   │   ├── chat.py                     # RAG 对话接口
│   │   ├── aiops.py                    # 单 Agent 诊断接口
│   │   ├── multi_agent.py              # 多 Agent 诊断接口
│   │   ├── router.py                   # 智能路由接口
│   │   ├── session.py                  # 会话管理接口
│   │   ├── file.py                     # 文件上传接口
│   │   └── health.py                   # 健康检查接口
│   ├── agent/
│   │   ├── aiops/                      # Planner、Executor、Replanner
│   │   ├── multi_agent/                # Supervisor、Specialist、Aggregator
│   │   ├── router/                     # Agent 路由决策
│   │   └── mcp_client.py               # MCP 客户端和重试逻辑
│   ├── services/
│   │   ├── rag_agent_service.py        # RAG Agent
│   │   ├── aiops_service.py            # 单 Agent 工作流
│   │   ├── router_service.py           # 统一路由服务
│   │   ├── document_splitter_service.py # 文档解析和分片
│   │   ├── vector_store_manager.py     # Milvus 向量存储
│   │   └── rerank_service.py           # 文档重排
│   ├── core/
│   │   ├── milvus_client.py            # Milvus 连接管理
│   │   ├── checkpointer.py             # LangGraph 持久化
│   │   └── mem0_manager.py             # Mem0 长期记忆
│   └── tools/                          # 本地 Agent 工具
├── frontend/                           # React + Vite 前端
│   └── src/
│       ├── features/chat/              # 对话视图
│       └── features/diagnosis/         # 诊断时间线和工具结果组件
├── mcp_servers/                        # MCP 服务实现或适配器
├── aiops-docs/                         # 示例运维知识库文档
├── vector-database.yml                 # Milvus 部署配置
├── pyproject.toml                      # 后端依赖和项目配置
└── uv.lock                             # Python 依赖锁定文件
```

## 常见问题

### `/api/health` 返回 404

确认请求发送到后端 `9900` 端口，而不是只启动了前端开发服务器。前端开发地址 `5173` 通过 Vite 代理访问后端 API。

### `/api/chat_stream` 返回 422

普通对话接口需要发送 `id` 和 `question`，例如：

```json
{
  "id": "session-001",
  "question": "查询最近的错误日志"
}
```

### MCP 连接超时

确认 MCP 服务已启动，并检查 `.env` 中的 `MCP_CLS_URL`、`MCP_MONITOR_URL` 和对应 transport 配置。Windows 环境还需要确保 `localhost` 不经过系统代理。

### Milvus 连接失败

```bash
docker ps
docker compose -f vector-database.yml up -d
```

### 前端页面空白

开发模式确认 `npm run dev` 正常运行；生产模式重新构建：

```bash
cd frontend
npm run build
```

然后重启 FastAPI。

## 许可证

MIT License

Author: chief
