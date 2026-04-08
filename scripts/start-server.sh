#!/bin/bash
# OfferBot 主服务启动脚本
# 确保使用项目 venv（包含 fork 版 chainlit）
set -e

cd "$(dirname "$0")/../boss-agent"

VENV="../.venv/bin/activate"
if [ ! -f "$VENV" ]; then
    echo "❌ 找不到 .venv，请先创建虚拟环境"
    exit 1
fi

source "$VENV"

echo "✅ Python: $(which python)"
echo "✅ Chainlit: $(python -c 'import chainlit; print(chainlit.__file__)')"

exec python -m uvicorn web.app:app --host 0.0.0.0 --port "${PORT:-7860}" --reload
