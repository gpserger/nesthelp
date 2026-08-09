#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

if command -v uv >/dev/null 2>&1; then
  exec uv run main.py "$@"
fi

if [ ! -d .venv ]; then
  echo "uv not found; falling back to venv + pip..."
  python3 -m venv .venv
  .venv/bin/pip install -q -r requirements.txt
fi
exec .venv/bin/python main.py "$@"
