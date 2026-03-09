#!/usr/bin/env bash
set -euo pipefail

# A股量化选股系统 - 服务器部署脚本
# 用法: bash deploy.sh

SERVER="aliyun-prod"
REMOTE_DIR="/opt/a-share-quant"
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== A股量化选股系统 - 部署 ==="
echo "服务器: $SERVER"
echo "远程目录: $REMOTE_DIR"
echo ""

# 1. 服务器上创建目录
echo "[1/4] 创建远程目录..."
ssh "$SERVER" "mkdir -p $REMOTE_DIR"

# 2. 同步文件 (排除数据目录和临时文件)
echo "[2/4] 同步代码到服务器..."
rsync -avz --delete \
    --exclude '.git' \
    --exclude '__pycache__' \
    --exclude '*.pyc' \
    --exclude '.venv' \
    --exclude 'data/*.csv' \
    --exclude 'data/*.json' \
    --exclude 'data/*.db' \
    --exclude '.env' \
    "$PROJECT_DIR/" "$SERVER:$REMOTE_DIR/"

# 3. 安装 Docker (如果未安装)
echo "[3/4] 检查 Docker..."
ssh "$SERVER" "command -v docker >/dev/null 2>&1 || {
    echo '安装 Docker...'
    curl -fsSL https://get.docker.com | sh
    systemctl enable docker
    systemctl start docker
}"

# 4. 构建并启动
echo "[4/4] 构建并启动服务..."
ssh "$SERVER" "cd $REMOTE_DIR && docker compose down 2>/dev/null; docker compose up -d --build"

echo ""
echo "=== 部署完成 ==="
echo "访问地址: http://112.124.103.65:8080"
echo ""
echo "常用命令:"
echo "  ssh $SERVER 'cd $REMOTE_DIR && docker compose logs -f'   # 查看日志"
echo "  ssh $SERVER 'cd $REMOTE_DIR && docker compose restart'    # 重启"
echo "  ssh $SERVER 'cd $REMOTE_DIR && docker compose down'       # 停止"
