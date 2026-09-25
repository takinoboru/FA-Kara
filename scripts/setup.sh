#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

PYTHON_BIN="${PYTHON_BIN:-python3}"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "未找到 $PYTHON_BIN。请先安装 Python 3.11 或 3.12。" >&2
  exit 1
fi

"$PYTHON_BIN" -m venv .venv
VENV_PYTHON="$PROJECT_DIR/.venv/bin/python"
"$VENV_PYTHON" -m pip install --upgrade pip setuptools wheel

case "$(uname -s)" in
  Darwin)
    "$VENV_PYTHON" -m pip install torch torchaudio
    ;;
  Linux)
    "$VENV_PYTHON" -m pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu
    ;;
  *)
    echo "此脚本支持 macOS/Linux；Windows 请运行 scripts/setup.ps1。" >&2
    exit 1
    ;;
esac

"$VENV_PYTHON" -m pip install -r requirements-gui.txt
"$VENV_PYTHON" -c 'import nltk; nltk.download("cmudict", quiet=True)'

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "提示：未检测到 ffmpeg。音频转码和视频压制前请安装 ffmpeg。"
fi

echo "安装完成。运行 ./scripts/run_gui.sh 启动 FA-Kara Studio。"
