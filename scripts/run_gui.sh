#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_PYTHON="$PROJECT_DIR/.venv/bin/python"

if [[ ! -x "$VENV_PYTHON" ]]; then
  echo "尚未安装环境，请先运行 ./scripts/setup.sh。" >&2
  exit 1
fi

cd "$PROJECT_DIR"
exec "$VENV_PYTHON" -m streamlit run kara_gui.py
