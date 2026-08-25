# 兼容层说明

`static/` 保存 React 前端迁移前的静态页面，仅用于前端构建产物不存在时的本地兼容展示。

当前开发和发布前端以 `frontend/` 为准：

```powershell
cd frontend
npm run build
```

新功能不得继续添加到本目录。前端迁移完成并确认不再需要兼容展示后，可在单独的破坏性变更中移除该目录和 FastAPI 中的回退逻辑。
