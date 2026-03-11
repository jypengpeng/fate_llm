#!/usr/bin/env bash
set -euo pipefail

echo "[INFO] 检查 Docker 环境..."
if ! command -v docker >/dev/null 2>&1; then
  echo "[ERROR] 未检测到 docker，请先安装 Docker Engine / Docker Desktop。"
  exit 1
fi

# 兼容 docker compose (v2) 与 docker-compose (v1)
if docker compose version >/dev/null 2>&1; then
  COMPOSE_CMD="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE_CMD="docker-compose"
else
  echo "[ERROR] 未检测到 docker compose，请安装 Docker Compose。"
  exit 1
fi

if [ ! -f .env ]; then
  echo "[WARN] 未找到 .env，正在从 .env.example 创建..."
  cp .env.example .env
  echo "[WARN] 请先编辑 .env，填入可用的 LLM_API_KEY 后再使用。"
fi

echo "[INFO] 使用命令: ${COMPOSE_CMD}"
echo "[INFO] 构建并后台启动服务..."
${COMPOSE_CMD} up -d --build

echo
echo "=========================================="
echo "[OK] Fate-LLM 已后台启动"
echo "召唤页面: http://<你的服务器IP或域名>:5000/summon.html"
echo "健康检查: http://<你的服务器IP或域名>:5000/api/health"
echo
echo "查看日志: ${COMPOSE_CMD} logs -f"
echo "停止服务: ${COMPOSE_CMD} down"
echo "=========================================="

