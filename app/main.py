"""FastAPI 应用入口

主应用程序，配置路由、中间件、静态文件等
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from contextlib import asynccontextmanager
import os

from app.config import config
from loguru import logger
from app.api import chat, health, file, aiops, session, multi_agent, router
from app.core.milvus_client import milvus_manager
from app.core.checkpointer import setup_checkpointer, close_checkpointer


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时执行
    logger.info("=" * 60)
    logger.info(f"🚀 {config.app_name} v{config.app_version} 启动中...")
    logger.info(f"📝 环境: {'开发' if config.debug else '生产'}")
    logger.info(f"🌐 监听地址: http://{config.host}:{config.port}")
    logger.info(f"📚 API 文档: http://{config.host}:{config.port}/docs")

    # 修复 MCP 本地连接超时：排除 localhost 走代理
    _no_proxy = os.environ.get("NO_PROXY") or os.environ.get("no_proxy") or ""
    _localhost_excluded = any(
        host in _no_proxy for host in ["localhost", "127.0.0.1", "::1"]
    )
    if not _localhost_excluded:
        _new_no_proxy = (
            f"{_no_proxy},localhost,127.0.0.1,::1"
            if _no_proxy
            else "localhost,127.0.0.1,::1"
        )
        os.environ["NO_PROXY"] = _new_no_proxy
        os.environ["no_proxy"] = _new_no_proxy
        logger.info(f"🔧 已设置 NO_PROXY={_new_no_proxy}")

    # LangSmith 追踪状态
    _tracing = os.environ.get("LANGCHAIN_TRACING_V2", "").lower()
    if _tracing == "true":
        logger.info("🔍 LangSmith 追踪: 已开启")
        logger.info(f"📊 LangSmith 项目: {os.environ.get('LANGCHAIN_PROJECT', 'default')}")
    else:
        logger.info("🔍 LangSmith 追踪: 未开启")

    # 连接 Milvus
    logger.info("🔌 正在连接 Milvus...")
    milvus_manager.connect()
    logger.info("✅ Milvus 连接成功")

    # 初始化 LangGraph checkpointer（统一持久化层）
    logger.info("🗄️ 正在初始化 checkpointer...")
    try:
        await setup_checkpointer()
        logger.info("✅ Checkpointer 初始化成功")
    except Exception as e:
        logger.error(f"❌ Checkpointer 初始化失败: {e}")
        raise

    logger.info("=" * 60)

    yield

    # 关闭时执行
    logger.info("🔌 正在关闭 Milvus 连接...")
    milvus_manager.close()

    logger.info("🗄️ 正在关闭 checkpointer...")
    await close_checkpointer()

    logger.info(f"👋 {config.app_name} 关闭")


# 创建 FastAPI 应用
app = FastAPI(
    title=config.app_name,
    version=config.app_version,
    description="基于 LangChain 的智能oncall运维系统",
    lifespan=lifespan
)

# 配置 CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 生产环境应该限制具体域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(health.router, prefix="/api", tags=["健康检查"])
app.include_router(chat.router, prefix="/api", tags=["对话"])
app.include_router(file.router, prefix="/api", tags=["文件管理"])
app.include_router(aiops.router, prefix="/api", tags=["AIOps智能运维"])
app.include_router(multi_agent.router, prefix="/api", tags=["Multi-Agent智能运维"])
app.include_router(router.router, prefix="/api", tags=["智能路由"])
app.include_router(session.router, prefix="/api", tags=["会话管理"])

# 挂载静态文件：优先前端构建产物 frontend/dist，缺失时回退到旧 static/
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_frontend_dist = os.path.join(_project_root, "frontend", "dist")
_legacy_static = os.path.join(_project_root, "static")
static_dir = _frontend_dist if os.path.isdir(_frontend_dist) else _legacy_static
# 前端构建产物（assets/、favicon 等）挂载到根路径，让 /assets/*.js /css 能直接访问
_assets_dir = os.path.join(static_dir, "assets")
if os.path.isdir(_assets_dir):
    app.mount("/assets", StaticFiles(directory=_assets_dir), name="assets")
# 旧 static 目录仍挂载到 /static（兼容历史引用）
if os.path.isdir(_legacy_static):
    app.mount("/static", StaticFiles(directory=_legacy_static), name="static")


@app.get("/")
async def root():
    """返回首页"""
    index_path = os.path.join(static_dir, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {
        "message": f"Welcome to {config.app_name} API",
        "version": config.app_version,
        "docs": "/docs"
    }


# SPA 兜底：非 /api、/mcp、/static 的 GET 请求返回 index.html，支持前端路由
@app.get("/{full_path:path}")
async def spa_fallback(full_path: str):
    """前端单页应用路由兜底"""
    if full_path.startswith(("api/", "mcp", "static/", "docs", "assets/")):
        return {"message": "Not Found"}
    index_path = os.path.join(static_dir, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "Not Found"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=config.host,
        port=config.port,
        reload=config.debug,
        log_level="info"
    )
