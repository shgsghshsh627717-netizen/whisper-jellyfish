#!/bin/bash

# Whisper-Input-Next 启动脚本（已改造：无需 tmux，前台运行）

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "🚀 启动 Whisper-Input-Next 语音转录工具..."

# 检查.env文件
if [ ! -f ".env" ]; then
  echo "❌ 未找到 .env 配置文件"
  echo "请复制 env.example 到 .env 并配置"
  exit 1
fi

# 检查虚拟环境
if [ ! -d ".venv" ]; then
  echo "❌ 未找到 .venv 虚拟环境，请先运行: python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt mlx-whisper"
  exit 1
fi

source .venv/bin/activate

echo ""
echo "✅ 语音助手启动中..."
echo "📋 快捷键说明："
echo "   Ctrl+F: 按一次开始录音，再按一次停止并转录"
echo "   Ctrl+I: 同上（本地 mlx-whisper 转录）"
echo "   Ctrl+C: 退出程序"
echo ""

python main.py
