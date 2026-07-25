你是一个 LangGraph 和 Agent 性能优化专家。请根据 LangSmith 追踪结果优化 Multi-Agent 模块的性能。

## 背景

当前 Multi-Agent 系统总耗时 104 秒，通过 LangSmith 追踪发现以下瓶颈：

| 节点 | 耗时 | 问题 |
|------|------|------|
| supervisor | 5.12s | 正常 |
| monitor_expert | 39.14s | LLM 分析太慢 |
| log_analyzer | 18.45s | 正常 |
| aggregator | 41.72s | 最慢，LLM 生成报告 |

**关键发现**：
1. aggregator 节点用 LLM 生成报告耗时 41s，占总时间 40%
2. monitor_expert 和 log_analyzer 是串行执行，应该并行
3. Specialist 内部 LLM 调用可以优化 prompt 缩短输出

## 任务

按以下优先级进行优化：

### P0：简化 aggregator 节点（目标：41s → 0s）

**当前问题**：`_generate_final_report` 方法调用 LLM 生成报告，耗时 41s

**优化要求**：
1. 将 `_generate_final_report` 改为简单拼接，不调用 LLM
2. 保持 Markdown 格式，包含以下章节：
   - 概述
   - 日志分析结论（从 `state["log_analysis"]["summary"]` 获取）
   - 监控指标分析（从 `state["monitor_metrics"]["summary"]` 获取）
   - 知识库参考（从 `state["knowledge_context"]` 获取）
   - 综合建议（简单总结）
3. 保留原有的 LLM 生成逻辑作为 fallback（当拼接结果为空时使用）

**修改文件**：`app/agent/multi_agent/__init__.py`

### P1：实现 Specialist 并行执行（目标：57s → 39s）

**当前问题**：`monitor_expert` 和 `log_analyzer` 串行执行

**优化要求**：
1. 修改 `_build_graph` 中的条件边逻辑
2. Supervisor 路由后，让所有选中的 Specialist **同时执行**
3. 所有 Specialist 完成后，统一进入 aggregator 节点
4. 使用 LangGraph 的原生并行能力（多个节点指向同一个下游节点）

**关键代码模式**：
```python
# Supervisor 路由到多个 Specialist（并行）
workflow.add_conditional_edges("supervisor", route_function, {
    "log_analyzer": "log_analyzer",
    "monitor_expert": "monitor_expert",
    "knowledge_retriever": "knowledge_retriever",
})

# 所有 Specialist 完成后汇聚到 aggregator
workflow.add_edge("log_analyzer", "aggregator")
workflow.add_edge("monitor_expert", "aggregator")
workflow.add_edge("knowledge_retriever", "aggregator")
```

**注意**：需要确保 `route_to_specialists` 函数能正确返回第一个待执行的节点，而不是阻塞等待。

### P2：优化 Specialist 内部 LLM 调用（目标：52s → 25s）

**当前问题**：MonitorExpert 和 LogAnalyzer 的 LLM 分析耗时过长

**优化要求**：
1. 在 prompt 中添加输出长度限制（如"分析不超过 300 字"）
2. 限制传入的原始数据量（如监控指标只取前 5 条）
3. 简化 prompt，去掉不必要的上下文

**修改文件**：
- `app/agent/multi_agent/log_analyzer.py`
- `app/agent/multi_agent/monitor_expert.py`

## 约束条件

1. **保持向后兼容**：优化后的接口和返回格式不能变
2. **保持容错**：Specialist 失败不应影响整体流程
3. **状态流转正确**：并行执行后状态仍正确写回
4. **添加注释**：解释优化决策和性能收益

## 输出要求

1. 提供修改后的完整代码文件
2. 每个修改点添加注释说明优化原因和预期收益
3. 说明如何验证优化效果（用 LangSmith 对比前后耗时）

## 参考资料

当前代码位置：
- `app/agent/multi_agent/__init__.py` - 主服务和 aggregator
- `app/agent/multi_agent/log_analyzer.py` - 日志分析 Specialist
- `app/agent/multi_agent/monitor_expert.py` - 监控分析 Specialist

预期优化效果：
- 优化前：104s
- 优化后：~45s（减少 57%）
