#!/bin/bash
set -e

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

# 检查 .env 文件
if [ ! -f ".env" ]; then
  echo "⚠️  未找到 .env 文件，请先复制并填写 API Key："
  echo "   cp .env.example .env"
  echo "   vim .env"
  exit 1
fi

# 激活虚拟环境
if [ -d ".venv" ]; then
  source .venv/bin/activate
fi

# 确保依赖已安装
echo "📦 检查依赖..."
pip install -e "." -q

# 创建 projects 目录
mkdir -p projects

echo "🚀 启动 AI 软件工厂服务..."
echo "   访问地址：http://localhost:8000"
echo ""
uvicorn software_factory.api.main:app --host 0.0.0.0 --port 8000 --reload
