# RAG 评测

本目录提供一套可复现的 RAG 基线，评测生产检索链路和回答质量，但不修改生产检索算法。

评测分成两层：

1. `run_retrieval_eval.py` 调用现有 `retrieve_knowledge`，验证向量召回、SQLite FTS5 关键词召回、RRF 合并和重排是否找到了正确来源。这个阶段不调用回答 LLM，成本低，适合反复调参。
2. `run_ragas_eval.py` 复用同一套检索链路，调用当前 Qwen 生成回答，再由 Ragas 评估 Faithfulness、Answer Relevancy、Context Precision 和 Context Recall。这个阶段会产生模型和嵌入调用费用。

## 数据集

`dataset.jsonl` 是冻结的简历级基线，共 60 条：

- 50 条单文档问题：5 份运维文档各 10 条。
- 5 条跨文档问题：`expected_sources` 包含多个来源，检查多来源召回。
- 5 条无答案问题：`answerable=false`，检查系统是否拒答，而不是把无关文档当答案。

每条数据包含 `id`、`category`、`question_type`、`difficulty`、`answerable`、`safety_level`、`question`、`expected_sources` 和 `reference_answer`。数据由 Qwen 辅助生成、人工抽查后冻结；修改后必须重新记录 fingerprint，不能直接把候选数据当正式基线。

`smoke_dataset.jsonl` 保留原来的 5 条小数据集，用于快速检查代码和 API。它不是简历基线，正式结果使用 60 条数据。

## 安装

生产服务不需要 Ragas。只在当前项目环境安装评测依赖：

```powershell
uv sync --extra eval
```

如果 `uv sync --extra eval` 因项目已有依赖冲突失败，不要修改生产依赖，使用独立环境：

```powershell
uv venv .venv-eval
uv pip install --python .venv-eval\Scripts\python.exe -e .
uv pip install --python .venv-eval\Scripts\python.exe "ragas>=0.3,<1" "datasets>=2.14"
```

## 第一步：校验并测召回

先确保 Milvus 正常运行、`uploads/` 文档已经索引、`.env` 中的嵌入和重排 API Key 可用：

```powershell
uv run python evals/validate_dataset.py
uv run python evals/run_retrieval_eval.py
uv run python evals/run_retrieval_eval.py --k 5
```

报告位于 `evals/reports/retrieval_report.json`。重点观察：

- `Recall@3`：每个问题的期望来源有多少被召回；跨文档问题会要求召回多个来源。
- `Precision@3`：前三个结果中有多少是期望来源。
- `MRR@3`：第一个正确来源的排名倒数平均值，越接近 1 越好。
- `groups`：按主题、问题类型和难度拆分指标，定位是哪个场景拖低整体结果。
- `no_answer_empty_retrieval_rate`：无答案问题返回空结果的比例，只作拒答前置参考，不混入普通 Recall/MRR。

评测报告会记录数据集 SHA-256 `dataset_fingerprint` 和 RAG 配置快照。比较两次实验时，先确认 fingerprint 相同，再比较指标；否则不能把结果当成同一数据集上的对照实验。

## 第二步：测回答质量

召回指标稳定后再运行，避免一开始就产生模型调用费用：

评测使用两套模型：`RAG_MODEL` 生成测试答案，`RAG_EVAL_MODEL` 负责 Ragas 评分。将 StepFun 配置填入项目 `.env`：

```dotenv
RAG_EVAL_API_KEY=your-stepfun-api-key
RAG_EVAL_API_BASE=https://api.stepfun.com/step_plan/v1
RAG_EVAL_MODEL=step-3.7-flash
```

```powershell
uv run python evals/run_ragas_eval.py --workers 1
```

脚本默认单并发执行评分，速度较慢但更稳定，适合 DashScope 有并发限制或偶尔返回空 JSON 的情况。确认接口和额度足够后，可用 `--workers 2` 或更高提高速度。

脚本会保存两份文件：

- `evals/reports/ragas_input.json`：每个问题、召回上下文、模型回答和参考答案，便于人工复核。
- `evals/reports/ragas_report.json`：Ragas 分数、分组统计、失败样本和拒答统计。

默认只评测 `answerable=true` 的 55 条问题。5 条无答案问题不参与普通 Ragas 平均分，而是在 `no_answer` 中输出拒答检测结果。单题评分失败会进入 `failures`，对应指标写为 `null`，不会静默变成 `NaN`。

Ragas 会重新使用已经保存的中间结果：

```powershell
uv run python evals/run_ragas_eval.py --reuse-intermediate --workers 1
```

只有中间结果和当前数据集 fingerprint、条数都一致时才会复用；数据集发生变化会明确报错，防止把旧回答错配到新问题。

## 如何扩展数据集

每行一个 JSON 对象，至少包含：

```json
{"question":"问题","expected_sources":["文件名.md"],"reference_answer":"人工确认的标准答案"}
```

可选字段 `service_name`、`environment` 和 `document_type` 会原样传给现有检索工具。

也可以用 Qwen 生成候选数据，但候选文件不能直接覆盖冻结数据集：

```powershell
uv run python evals/generate_dataset.py --count-per-source 10
```

人工检查来源约束、答案、危险操作建议和字段分布后，再把合格记录合并进 `dataset.jsonl`，并重新运行：

```powershell
uv run python evals/validate_dataset.py
```

## 推荐验证顺序

```powershell
uv run python evals/validate_dataset.py
uv run python -m compileall -q evals
uv run ruff check evals
uv lock --check
uv run python evals/run_retrieval_eval.py
uv run python evals/run_ragas_eval.py --workers 1
uv run python evals/run_ragas_eval.py --reuse-intermediate --workers 1
```

召回评测应先稳定，再运行 Ragas。Ragas 的报告只能作为基线和定位工具，简历中应同时说明数据规模、数据集 fingerprint、检索配置和人工抽查范围，不应只展示单个自动评分。

## 正确的排查顺序

1. `Recall@K` 低：先查文档分块、索引、混合召回、RRF 或重排。
2. `Recall@K` 高但 Ragas 忠实性低：查上下文拼接、提示词或模型是否编造。
3. 忠实性高但回答相关性低：查问题理解、回答格式和上下文噪声。
4. 无答案拒答率低：查拒答提示词、检索阈值和无答案样本设计。
5. 自动指标必须结合 `ragas_input.json` 人工抽查，尤其是运维场景的危险操作建议。
