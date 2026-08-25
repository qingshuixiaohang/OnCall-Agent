# 问题追踪器：本地 Markdown

本仓库的 issue 与规格说明以 markdown 文件形式存放于 `.scratch/` 目录。

## 约定

- 一个功能对应一个目录：`.scratch/<feature-slug>/`
- 规格说明为 `.scratch/<feature-slug>/spec.md`
- 实现任务单每个文件一个 ticket，存放于 `.scratch/<feature-slug>/issues/<NN>-<slug>.md`，编号从 `01` 开始，禁止合并为单个 tickets 文件
- 分流状态记录在每个 issue 文件顶部的 `Status:` 行（标签字符串详见 `triage-labels.md`）
- 评论与对话历史追加到文件底部的 `## Comments` 标题下

## 当技能说「发布到 issue tracker」时

在 `.scratch/<feature-slug>/` 下创建新文件（目录不存在则自动创建）。

## 当技能说「获取相关 ticket」时

读取对应路径下的文件。用户通常会直接传入路径或 issue 编号。

## Wayfinding 操作

供 `/wayfinder` 使用。**地图（map）** 文件包含多个**子 ticket** 文件。

- **地图**：`.scratch/<effort>/map.md`（Notes / Decisions-so-far / Fog 内容）。
- **子 ticket**：`.scratch/<effort>/issues/NN-<slug>.md`，编号从 `01` 开始，正文为问题。`Type:` 行记录 ticket 类型（`research`/`prototype`/`grilling`/`task`）；`Status:` 行记录 `claimed`/`resolved`。
- **阻塞关系**：文件顶部附近有 `Blocked by: NN, NN` 行。当一个 ticket 列出的所有文件都是 `resolved` 时，它才算解阻。
- **前沿（Frontier）**：扫描 `.scratch/<effort>/issues/` 下处于打开、未解阻、未认领状态的文件；编号小的优先。
- **认领（Claim）**：开始工作前将 `Status` 设为 `claimed` 并保存。
- **解决（Resolve）**：在 `## Answer` 标题下追加答案，将 `Status` 设为 `resolved`，然后将上下文摘要（gist + 链接）追加到地图文件 Decisions-so-far 部分。