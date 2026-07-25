@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

echo ====================================
echo 启动 SuperBizAgent（本地模拟 CLS 数据）
echo ====================================
echo.

set PROJECT_ROOT=%CD%

REM 1. 检查包管理器
echo [1/6] 检查包管理器...
where uv >nul 2>&1
if errorlevel 1 (
    echo [信息] uv 未安装，将使用传统 pip 方式
    set USE_UV=0
) else (
    echo [成功] 检测到 uv 包管理器
    set USE_UV=1
)
echo.

REM 2. 配置 Python 版本
echo [2/6] 配置 Python 版本...
if exist .python-version (
    set /p PYTHON_VERSION=<.python-version
) else (
    echo 3.13> .python-version
    set PYTHON_VERSION=3.13
)
echo [信息] 当前配置版本: !PYTHON_VERSION!
echo.

REM 3. 创建/同步虚拟环境
echo [3/6] 创建/同步虚拟环境...
if not exist .venv\Scripts\python.exe (
    python -m venv .venv
)
if "%USE_UV%"=="1" (
    uv sync
) else (
    .venv\Scripts\python.exe -m pip install --upgrade pip -q
    .venv\Scripts\python.exe -m pip install -e . -q
)
echo [成功] 虚拟环境就绪
echo.

REM 4. 启动 Milvus
echo [4/6] 启动 Milvus 向量数据库...
docker ps --format "{{.Names}}" | findstr "milvus-standalone" >nul 2>&1
if errorlevel 1 (
    docker compose -f vector-database.yml up -d
    echo [信息] 等待 Milvus 启动（请稍等...）
    ping 127.0.0.1 -n 12 >nul
) else (
    echo [信息] Milvus 容器已在运行
)
echo.

REM 5. 启动 MCP 服务
echo [5/6] 启动 MCP 服务...

REM 启动本地模拟 CLS MCP（Python 模拟数据）
echo [信息] 启动本地模拟 CLS MCP ...
start "CLS MCP (Mock)" cmd /c "!PROJECT_ROOT!\.venv\Scripts\python.exe !PROJECT_ROOT!\mcp_servers\cls_server.py"
ping 127.0.0.1 -n 4 >nul

REM 启动 Monitor MCP
echo [信息] 启动 Monitor MCP ...
start "Monitor MCP" cmd /c "!PROJECT_ROOT!\.venv\Scripts\python.exe !PROJECT_ROOT!\mcp_servers\monitor_server.py"
ping 127.0.0.1 -n 4 >nul

echo [成功] MCP 服务已拉起

REM 6. 启动 FastAPI
echo [6/6] 启动 FastAPI 服务...
start "SuperBizAgent API" cmd /c "!PROJECT_ROOT!\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 9900"
echo [信息] 等待服务加载（20秒）...
ping 127.0.0.1 -n 22 >nul

REM 7. 检查与上传文档
echo.
echo [完成] 上传 aiops 文档...
set upload_count=0
for %%f in (aiops-docs\*.md) do (
    echo   上传: %%~nxf
    curl -s -X POST http://localhost:9900/api/upload -F "file=@%%f" >nul 2>&1
    if !errorlevel! equ 0 set /a upload_count+=1
)

echo.
echo ====================================
echo 服务启动完成！
echo ====================================
echo Web 界面: http://localhost:9900
echo CLS 模式: 本地模拟数据（端口 3000）
echo 上传了 !upload_count! 个文档。
echo.
echo 如果需要查看 FastAPI 启动错误：打开 logs\fastapi_startup.log
echo 如果需要手动停止，请关闭那三个黑窗口。
echo ====================================
pause