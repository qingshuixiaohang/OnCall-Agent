# 领域文档

工程技能在探索代码库时应如何消费本仓库的领域文档。

## 探索前先阅读

- **`CONTEXT.md`**（位于仓库根目录），或
- **`CONTEXT-MAP.md`**（位于仓库根目录，如果存在）：它指向每个上下文的 `CONTEXT.md` 文件。请阅读与当前主题相关的每一个。
- **`docs/adr/`**：阅读与你要工作的领域相关的 ADR。在多上下文仓库中，还需检查 `src/<context>/docs/adr/` 中的上下文专属决策。

如果以上任何文件不存在，**静默继续**。不要标记它们的缺失；不要在前期主动建议创建。`/domain-modeling` 技能（通过 `/grill-with-docs` 和 `/improve-codebase-architecture` 调用）会在术语或决策真正被解决时按需创建它们。

## 文件结构

单上下文仓库（大多数仓库）：

```
/
├── CONTEXT.md
├── docs/adr/
│   ├── 0001-event-sourced-orders.md
│   └── 0002-postgres-for-write-model.md
└── src/
```

多上下文仓库（根目录存在 `CONTEXT-MAP.md`）：

```
/
├── CONTEXT-MAP.md
├── docs/adr/                          ← 系统级决策
└── src/
    ├── ordering/
    │   ├── CONTEXT.md
    │   └── docs/adr/                  ← 上下文专属决策
    └── billing/
        ├── CONTEXT.md
        └── docs/adr/
```

## 使用术语表词汇

当你的输出命名领域概念时（如 issue 标题、重构提案、假设、测试名称），请使用 `CONTEXT.md` 中定义的术语。不要漂移到术语表明确避免的同义词。

如果你需要的概念尚未在术语表中，这是一个信号：要么你在创造项目未使用的语言（重新考虑），要么确实存在空白（记录给 `/domain-modeling`）。

## 标记 ADR 冲突

如果你的输出与既有 ADR 矛盾，请显式标出而非默默覆盖：

> _与 ADR-0007（event-sourced orders）矛盾，但由于……值得重新讨论。_