# ADR-0001: RAG 服务收拢为 RAGPipeline 深模块

- **状态**: 已采纳
- **日期**: 2026-08-26
- **决策者**: 架构评审

## 背景

RAG 检索与入库能力原分散在 7 个服务类（vector_embedding / vector_index /
vector_search / vector_store_manager / rerank / document_splitter /
keyword_index），由 rag_agent_service 手动组装。调用方面对的接口复杂度
接近实现复杂度，新增检索策略需改动多个服务，测试需 mock 多个依赖。

## 决策

将检索与入库收拢为单一 `RAGPipeline` 深模块，对外只暴露：

- `query(question, session_id, filters) → str`
- `retrieve(question, filters) → (context, docs)`
- `ingest(file_path) → result`

向量/关键词/重排/分片等实现细节封装在模块内部。

## 关于旧服务的处理

原 issue-04 提议"旧服务改为薄包装委托给 RAGPipeline"。实际实施时改为
**直接删除无引用的死代码**（vector_search_service、vector_index_service），
而非保留薄包装。理由：

- 这两个服务从未被外部调用，薄包装只会增加维护面
- `vector_embedding_service` 保留，因 evals 评估脚本是其第二个真实消费方
  （"两个 adapter 才值得保留 seam"）

## 后果

- 调用方只需依赖 RAGPipeline 一个接口
- 底层存储切换（如 Milvus → 其他向量库）不泄漏到业务代码
- 测试只需 mock RAGPipeline 一个 seam

## 相关

- 原 spec: `.scratch/_archive/rag-pipeline-refactor/spec.md`
- 实施 commit: 9ac3c9a
