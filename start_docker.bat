@echo off
chcp 65001 >nul
setlocal

echo [信息] 正在检查 Docker 环境...
docker --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未检测到 Docker，请先安装 Docker Desktop 并启动。
    echo 下载地址: https://www.docker.com/products/docker-desktop
    pause
    exit /b
)

if not exist .env (
    echo [提示] 未找到 .env 配置文件，正在从 .env.example 创建...
    copy .env.example .env >nul
    echo [警告] 请务必编辑 .env 文件，填入你的 LLM API Key，否则无法生成剧情！
    echo 按任意键继续启动，或者关闭窗口先去编辑配置...
    pause
)

echo [信息] 正在构建并启动 Fate-LLM 服务...
docker-compose up -d --build

if %errorlevel% neq 0 (
    echo [错误] Docker 启动失败，请检查 Docker Desktop 是否正在运行。
    pause
    exit /b
)

echo.
echo ==========================================
echo [成功] Fate-LLM 服务已在后台启动！
echo 游戏入口: http://localhost:5000/game.html
echo 召唤页面: http://localhost:5000/summon.html
echo.
echo 如需停止服务，请运行: docker-compose down
echo ==========================================
echo.
pause