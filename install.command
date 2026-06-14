#!/bin/bash
# 🪼 水母语音输入 whisper-jellyfish · 一键安装
# 双击本文件即可。它会自动建好环境、装好依赖、在桌面生成一个「水母语音输入」app。

set -e
cd "$(dirname "$0")"
PROJECT_DIR="$(pwd)"

echo ""
echo "🪼  水母语音输入 — 一键安装"
echo "===================================="
echo "项目位置：$PROJECT_DIR"
echo ""

# ---------- 1. 检查 Python 3 ----------
if ! command -v python3 >/dev/null 2>&1; then
  echo "❌ 没有找到 Python 3。"
  echo "   请先去 https://www.python.org/downloads/ 下载安装 Python（3.12 或更新版本），"
  echo "   装好后再双击本文件。"
  echo ""
  read -n 1 -s -r -p "按任意键关闭…"
  exit 1
fi
PYVER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo "✅ 找到 Python $PYVER"

# ---------- 2. 创建/校验虚拟环境 ----------
# 注意：项目放在 iCloud 里时，旧机器的 .venv 会被同步到新机器，但 venv 绑定机器、
# 不能跨机直接复用。这里实测当前机器能否真正用它，不行就重建——这样换一台 Mac
# 双击本文件即可，无需手动删 .venv。
NEED_BUILD=0
if [ ! -x ".venv/bin/python" ]; then
  NEED_BUILD=1
elif ! .venv/bin/python -c "import mlx_whisper, sounddevice" >/dev/null 2>&1; then
  echo "♻️  检测到 .venv 不适用于本机（可能来自另一台同步过来的 Mac），将重建…"
  NEED_BUILD=1
fi
if [ "$NEED_BUILD" = "1" ]; then
  echo "🐍 正在创建虚拟环境 .venv …"
  rm -rf .venv
  python3 -m venv .venv
fi
source .venv/bin/activate
python -m pip install --upgrade pip >/dev/null 2>&1 || true

# ---------- 3. 安装依赖 ----------
echo "📦 正在安装依赖（首次需要几分钟，请耐心等待）…"
pip install -r requirements.txt

# ---------- 4. 准备本地模式配置 ----------
if [ ! -f ".env" ]; then
  echo "⚙️  生成默认配置（纯本地模式，无需任何 API key）…"
  cat > .env <<'ENVEOF'
# 纯本地模式，使用 mlx-whisper，无需任何 API key
SERVICE_PLATFORM=local
MLX_WHISPER_MODEL=mlx-community/whisper-large-v3-turbo
TRANSCRIPTIONS_BUTTON=f
TRANSLATIONS_BUTTON=ctrl
SYSTEM_PLATFORM=mac
CONVERT_TO_SIMPLIFIED=false
ADD_SYMBOL=false
OPTIMIZE_RESULT=false
ENABLE_KIMI_POLISH=false
AUTO_RETRY_LIMIT=3
ENVEOF
fi

# ---------- 5. 在桌面生成「水母语音输入」app ----------
echo "🖥️  正在桌面生成「水母语音输入」启动图标…"
APP_PATH="$HOME/Desktop/水母语音输入.app"
TMP_SCPT="$(mktemp -t jellyfish).applescript"
cat > "$TMP_SCPT" <<OSAEOF
on run
	tell application "Terminal"
		activate
		do script "cd '$PROJECT_DIR' && source .venv/bin/activate && python main.py"
	end tell
end run
OSAEOF
rm -rf "$APP_PATH" 2>/dev/null || true
osacompile -o "$APP_PATH" "$TMP_SCPT" >/dev/null 2>&1
rm -f "$TMP_SCPT"
xattr -cr "$APP_PATH" 2>/dev/null || true

echo ""
echo "🎉  安装完成！"
echo "===================================="
echo ""
echo "接下来还需要给系统授权（只需做一次）："
echo ""
PYAPP="$(python -c 'import sys,os; p=os.path.join(sys.base_prefix,"Resources","Python.app"); print(p if os.path.exists(p) else sys.executable)')"
echo "  1) 打开 系统设置 → 隐私与安全性 → 辅助功能"
echo "     把 Terminal（终端）和 Python 都加进去并打开开关"
echo "     · 加 Python：点 +，按 Cmd+Shift+G，粘贴下面这行路径再回车，然后选「打开」："
echo "       $PYAPP"
echo "       （或者：首次启动后按一下 Ctrl+F，系统会弹授权提示，直接点允许也行）"
echo ""
echo "  2) 首次按 Ctrl+F 录音时，会弹出麦克风授权 → 点「允许」"
echo ""
echo "用法："
echo "  · 双击桌面「水母语音输入」启动（会弹出一个终端窗口，别关它）"
echo "  · 在任意输入框按 Ctrl+F 开始录音，再按一次停止，文字自动出现"
echo "  · 桌面上的小水母可以拖动，点一下它 = 按 Ctrl+F"
echo ""
read -n 1 -s -r -p "按任意键关闭本窗口…"
echo ""
