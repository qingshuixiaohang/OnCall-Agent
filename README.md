# OnCall-Agent

> 智能 OnCall 故障响应系统 — 通过 AI Agent 实现问题自动应答和故障智能排查的一体化服务

[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.109+-green.svg)](https://fastapi.tiangolo.com/)
[![LangChain](https://img.shields.io/badge/LangChain-latest-orange.svg)](https://www.langchain.com/)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## 项目简介

OnCall-Agent 是一套面向运维场景的 AI Agent 系统，整合 **知识库问答**、**多轮对话**、**智能运维** 三大核心能力，将故障响应从人工排查模式升级为 Agent 自主诊断模式。

**解决的问题**：传统 OnCall 需要运维人员手动查日志、查监控、翻文档排障，响应时间在小时级。本系统通过 AI Agent 自动完成「检索知识库 → 规划诊断步骤 → 调用工具查询 → 分析结果 → 生成建议」的完整闭环，将响应时间降低到分钟级。

---

## 核心特性

| 特性 | 说明 |
|------|------|
| 🤖 **RAG 知识库问答** | 支持 md/txt/pdf/docx 多格式文档上传，自动向量化存储，基于向量检索+重排的两阶段召回，检索准确率 85%+ |
| 💬 **多轮对话** | ReAct 模式的 Chat Agent，支持 SSE 流式输出，对话上下文自动压缩（70% 阈值触发 LLM 总结） |
| 🔧 **智能运维诊断** | Plan-Execute-Replan 模式的 AIOps Agent，自动制定诊断计划、调用 MCP 工具查询日志/监控、生成结构化报告 |
| 🔌 **MCP 工具集成** | 通过 MCP 协议对接日志查询(CLS)、Prometheus 监控等外部数据源，支持指数退避重试和故障隔离 |
| 📂 **多格式文档分片** | 自研文件类型处理器，Markdown 三阶段结构感知分片、PDF/Word 自动提取后递归分片 |
| 🧠 **会话记忆持久化** | AIOps 会话状态持久化到 SQLite/PostgreSQL，重启后不丢失 |

---

## 技术栈

| 层级 | 技术 |
|------|------|
| **后端框架** | FastAPI + Uvicorn |
| **AI 框架** | LangChain + LangGraph |
| **对话模型** | 阿里云 DashScope (通义千问 qwen3.7-max) |
| **向量模型** | SiliconFlow (BAAI/bge-m3) |
| **向量数据库** | Milvus 2.5 |
| **重排模型** | 阿里云百炼 Rerank (gte-rerank) |
| **工具协议** | MCP (Model Context Protocol) |
| **会话存储** | SQLite / PostgreSQL |
| **前端** | 原生 HTML/CSS/JS (SSE 流式渲染) |

---

## 系统架构

```
┌─────────────────────────────────────────────────────────────────┐
│                        用户浏览器 (SSE)                          │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                     FastAPI 应用 (端口 9900)                     │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────────┐│
│  │ /api/chat│  │/api/aiops│  │/api/upload│  │ /api/health      ││
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └──────────────────┘│
│       │              │              │                            │
│       ▼              ▼              ▼                            │
│  ┌─────────┐  ┌───────────┐  ┌─────────────┐                   │
│  │Chat Agent│  │AIOps Agent│  │文档分片引擎  │                   │
│  │ (ReAct)  │  │(Plan-Exec)│  │(md/txt/pdf/ │                   │
│  │          │  │           │  │  docx)      │                   │
│  └────┬─────┘  └─────┬─────┘  └──────┬──────┘                   │
│       │              │               │                           │
│       │    ┌─────────┴──────────┐    │                           │
│       │    │                    │    │                           │
│       ▼    ▼                    ▼    ▼                           │
│  ┌──────────────┐  ┌───────────────────────┐                    │
│  │  Milvus      │  │   MCP Servers          │                   │
│  │  (向量检索    │  │  ┌──────────────────┐ │                   │
│  │   + 重排)     │  │  │ CLS 日志查询     │ │                   │
│  └──────────────┘  │  │ Monitor 监控查询  │ │                   │
│                     │  └──────────────────┘ │                   │
│  ┌──────────────┐  └───────────────────────┘                    │
│  │ SQLite/PG    │                                                │
│  │ (会话持久化)  │                                                │
│  └──────────────┘                                                │
└─────────────────────────────────────────────────────────────────┘
```

---

## 快速开始

### 环境要求

- Python 3.11+
- Docker (用于 Milvus 向量数据库)
- 阿里云 DashScope API Key ([获取地址](https://bailian.console.aliyun.com/#/api-key))
- SiliconFlow API Key ([获取地址](https://cloud.siliconflow.cn/account/ak))

### 第一步：克隆项目

```bash
git clone https://github.com/qingshuixiaohang/OnCall-Agent.git
cd OnCall-Agent
```

### 第二步：安装依赖

```bash
# 创建虚拟环境
python -m venv .venv

# 激活虚拟环境
# Windows:
.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate

# 安装依赖（推荐 uv，速度更快）
pip install uv
uv pip install -e .

# 或者用普通 pip
pip install -e .
```

### 第三步：配置环境变量

```bash
# 复制配置模板
cp .env.example .env
cp mcp_servers/.env.example mcp_servers/.env

# 编辑 .env，填入你的 API Key
# 必填项：
#   DASHSCOPE_API_KEY=sk-xxxxx
#   SILICONFLOW_API_KEY=sk-xxxxx
```

### 第四步：启动 Milvus 向量数据库

```bash
# 确保 Docker Desktop 已启动
docker compose -f vector-database.yml up -d

# 等待 Milvus 启动完成（约 30 秒）
# 检查状态
docker ps | grep milvus
```

启动后可以访问 **Attu 管理界面**: http://localhost:8000

### 第五步：启动服务

**Linux/macOS:**
```bash
make start
```

**Windows:**
```powershell
.\start-windows.bat

# 或手动启动：
# 终端 1 - 主服务
python -m uvicorn app.main:app --host 0.0.0.0 --port 9900

# 终端 2 - CLS 日志 MCP 服务
python mcp_servers/cls_server.py

# 终端 3 - Monitor 监控 MCP 服务
python mcp_servers/monitor_server.py
```

### 第六步：上传知识库文档

```bash
# 将文档放入 uploads/ 目录，然后通过 API 上传
curl -X POST "http://localhost:9900/api/upload" \
  -F "file=@your-doc.md"

# 或者批量上传 aiops-docs/ 目录下的示例文档
for f in aiops-docs/*.md; do
  curl -X POST "http://localhost:9900/api/upload" -F "file=@$f"
done
```

### 访问服务

| 服务 | 地址 |
|------|------|
| Web 界面 | http://localhost:9900 |
| API 文档 (Swagger) | http://localhost:9900/docs |
| Attu (Milvus 管理) | http://localhost:8000 |

---

## API 接口

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/chat` | POST | 普通对话（一次性返回） |
| `/api/chat_stream` | POST | 流式对话（SSE） |
| `/api/aiops` | POST | AIOps 智能诊断（SSE 流式） |
| `/api/upload` | POST | 上传文档到知识库 |
| `/api/sessions` | GET | 列出所有会话 |
| `/api/sessions/{id}` | GET | 获取指定会话状态 |
| `/api/sessions/{id}` | DELETE | 删除指定会话 |
| `/api/health` | GET | 健康检查 |

**示例：**

```bash
# 普通对话
curl -X POST "http://localhost:9900/api/chat" \
  -H "Content-Type: application/json" \
  -d '{"Id":"test-001","Question":"你好"}'

# 流式对话
curl -X POST "http://localhost:9900/api/chat_stream" \
  -H "Content-Type: application/json" \
  -d '{"Id":"test-001","Question":"你好"}' \
  --no-buffer

# AIOps 诊断
curl -X POST "http://localhost:9900/api/aiops" \
  -H "Content-Type: application/json" \
  -d '{"session_id":"test-001"}' \
  --no-buffer
```

---

## 项目结构

```
OnCall-Agent/
├── app/                              # 应用核心
│   ├── main.py                       # FastAPI 入口
│   ├── config.py                     # 配置管理 (Pydantic Settings)
│   ├── api/                          # API 路由层
│   │   ├── chat.py                   # 对话接口
│   │   ├── aiops.py                  # AIOps 诊断接口
│   │   ├── file.py                   # 文件上传接口
│   │   ├── session.py                # 会话管理接口
│   │   └── health.py                 # 健康检查
│   ├── services/                     # 业务服务层
│   │   ├── rag_agent_service.py      # Chat Agent (ReAct + LangGraph)
│   │   ├── aiops_service.py          # AIOps Agent (Plan-Execute-Replan)
│   │   ├── document_splitter_service.py  # 多格式文档分片引擎
│   │   ├── vector_embedding_service.py   # 向量 Embedding 服务
│   │   ├── vector_index_service.py       # 向量索引服务
│   │   ├── vector_search_service.py      # 向量检索服务
│   │   ├── vector_store_manager.py       # Milvus 存储管理
│   │   └── rerank_service.py             # 文档重排服务
│   ├── agent/                        # Agent 模块
│   │   ├── mcp_client.py             # MCP 客户端 (重试拦截器)
│   │   └── aiops/                    # AIOps 核心
│   │       ├── planner.py            # 计划制定器
│   │       ├── executor.py           # 步骤执行器
│   │       ├── replanner.py          # 重规划器
│   │       └── state.py              # 状态定义
│   ├── core/                         # 核心组件
│   │   ├── llm_factory.py            # LLM 工厂
│   │   ├── milvus_client.py          # Milvus 客户端管理
│   │   ├── storage_engine.py         # 存储抽象接口
│   │   ├── storage_sqlite.py         # SQLite 实现
│   │   ├── storage_postgres.py       # PostgreSQL 实现
│   │   └── storage_factory.py        # 存储工厂
│   ├── models/                       # 数据模型
│   ├── tools/                        # Agent 工具集
│   │   ├── knowledge_tool.py         # 知识库检索 (粗排+精排)
│   │   └── time_tool.py              # 时间工具
│   └── utils/                        # 工具类
│       └── logger.py                 # 日志配置
├── static/                           # 前端 (原生 HTML/CSS/JS)
│   ├── index.html
│   ├── app.js
│   └── styles.css
├── mcp_servers/                      # MCP 服务器
│   ├── cls_server.py                 # CLS 日志查询服务
│   └── monitor_server.py             # 监控数据服务
├── aiops-docs/                       # 示例运维知识库文档
├── docs/                             # 开发文档
├── .env.example                      # 环境变量模板
├── vector-database.yml               # Milvus Docker Compose
├── Makefile                          # 项目管理命令 (Linux/macOS)
├── start-windows.bat                 # Windows 启动脚本
├── stop-windows.bat                  # Windows 停止脚本
├── pyproject.toml                    # 项目配置
└── uv.lock                           # 依赖锁定文件
```

---

## 数据持久化

本项目使用两套数据库：

| 存储层 | 用途 | 查看方式 |
|--------|------|----------|
| **Milvus** (向量数据库) | 存储文档向量，用于 RAG 检索 | Attu Web 界面: http://localhost:8000 |
| **SQLite** (关系型数据库) | AIOps 会话状态持久化 | DB Browser for SQLite 打开 `volumes/langgraph.db` |
| **文件系统** | 上传的原始文档 | 直接查看 `uploads/` 目录 |

---

## 关键设计决策

### 1. 两阶段检索：向量粗排 + 语义精排

```
用户提问 → 向量相似度召回 9 篇候选 → Rerank 模型精排 → 返回最相关 3 篇
```

- 单纯向量检索准确率 ~60%，加入重排后提升到 85%+
- 重排失败不降级直接报错（运维场景宁可空结果不要误导）

### 2. Plan-Execute-Replan 图结构

```
Planner(制定计划) → Executor(执行步骤) → Replanner(评估结果)
                                              ↓
                                    继续执行 / 生成报告
```

- 每个节点有独立状态输出，前端可实时展示推理过程
- 比 REACT 循环更适合需要可追溯日志的运维场景

### 3. MCP 工具调用容错

- 指数退避重试：1s → 2s → 4s，最多 3 次
- 全部失败返回错误信息而非抛异常，避免单工具故障拖垮整个诊断流程

### 4. 对话上下文智能压缩

- 监控 token 消耗，达到 70% 阈值时自动触发
- 调用 LLM 将旧消息总结为结构化摘要，压缩 50%+ token
- 总结失败时降级为简单截断，保证不中断服务

---

## 常见问题

### Milvus 连接失败

```bash
# 检查 Docker 是否运行
docker ps

# 重启 Milvus
docker compose -f vector-database.yml restart

# 查看日志
docker logs milvus-standalone
```

### API Key 报错

```bash
# 确认 .env 文件存在且已填写正确的 Key
cat .env | grep DASHSCOPE_API_KEY
cat .env | grep SILICONFLOW_API_KEY
```

### 端口被占用

```bash
# Windows
netstat -ano | findstr :9900
taskkill /F /PID <PID>

# Linux/macOS
lsof -i :9900
kill -9 <PID>
```

---

## 许可证

MIT License

Author: chief
