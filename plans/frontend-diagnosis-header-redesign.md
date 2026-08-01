# 前端顶部诊断按钮区域重新设计方案

## 目标

在不影响现有交互的前提下，重新设计顶部「快速诊断 / 全面诊断」按钮区域，使其：
- 视觉上更符合当前整体简洁风格
- 信息层级更清晰
- 按钮更优雅，减少突兀感
- 保持响应式适配

## 当前问题

当前实现位于 `static/index.html:47-71`，存在以下问题：
- 标题与操作区混在同一行，视觉密度高
- 按钮样式偏传统，与整体风格略割裂
- 移动端空间利用不佳

## 设计原则

- 保留现有功能与事件绑定
- 不修改现有 `id`，避免 JS 改动
- 采用更轻量的「标签式操作区」表达
- 主次按钮区分明确，但不刺眼

## 具体方案

### HTML 结构

将顶部栏改为：

```html
<div class="chat-header">
    <div class="chat-header-left">
        <div class="brand">
            <h1 class="chat-title">智能OnCall助手</h1>
            <span class="chat-subtitle">AI 驱动的智能运维诊断</span>
        </div>
        <div class="diagnosis-actions">
            <button class="action-chip action-chip-quick" id="aiOpsSidebarBtn" title="快速诊断">
                <span class="chip-icon">
                    <svg>...</svg>
                </span>
                <span class="chip-label">快速诊断</span>
            </button>
            <button class="action-chip action-chip-full" id="multiAgentBtn" title="全面诊断">
                <span class="chip-icon">
                    <svg>...</svg>
                </span>
                <span class="chip-label">全面诊断</span>
            </button>
        </div>
    </div>
</div>
```

### CSS 样式

新增/调整以下类：

```css
/* 品牌区 */
.chat-header-left {
    display: flex;
    flex-direction: column;
    gap: 10px;
}

.brand {
    display: flex;
    flex-direction: column;
    gap: 2px;
}

/* 诊断操作区 */
.diagnosis-actions {
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
}

/* Chip 按钮 */
.action-chip {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    padding: 8px 14px;
    border: none;
    border-radius: 999px;
    cursor: pointer;
    font-size: 13px;
    font-weight: 500;
    transition: all 0.2s ease;
    line-height: 1;
    background: #f3f4f6;
    color: #374151;
}

.action-chip:hover {
    background: #e5e7eb;
    color: #111827;
}

.action-chip-quick {
    background: #eef2ff;
    color: #4338ca;
}

.action-chip-quick:hover {
    background: #e0e7ff;
    color: #312e81;
}

.action-chip-full {
    background: #eff6ff;
    color: #2563eb;
}

.action-chip-full:hover {
    background: #dbeafe;
    color: #1d4ed8;
    box-shadow: 0 2px 6px rgba(37, 99, 235, 0.25);
}

.chip-icon svg {
    width: 16px;
    height: 16px;
    flex-shrink: 0;
}

.chip-label {
    white-space: nowrap;
}
```

### 响应式

- 小屏下按钮自动换行
- 保持可点击区域不小于 44px 高度

## 需要修改的文件

- `static/index.html`
- `static/styles.css`

## 不影响的功能

- 现有 JS 事件绑定保持兼容
- `aiOpsSidebarBtn`、`multiAgentBtn` 的 `id` 不变
- 顶部标题与输入区逻辑不变

## 后续建议

确认后由 Code 模式直接实现，并给出效果截图说明。
