#!/bin/bash
# Azure start: install deps (if needed) + MCP server (background) + web host (foreground)
set -e
export PYTHONPATH=src
export MCP_HOST=0.0.0.0
export MCP_PORT=8765
export MCP_URL="${MCP_URL:-http://127.0.0.1:8765/mcp}"
# Ensure Python dependencies are installed (Oryx build may skip this)
pip install -q -r requirements.txt
python -m marketpulse.server &
exec uvicorn web.app:app --host 0.0.0.0 --port "${PORT:-8766}"
