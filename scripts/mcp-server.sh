#!/usr/bin/env bash
# Start the Pallium MCP server (stdio transport).
# This script encapsulates the Python runtime so callers don't need to know
# the implementation language or venv location.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# Use the project's venv if it exists, otherwise fall back to system python
if [ -f "$PROJECT_DIR/.venv/bin/python" ]; then
    PYTHON="$PROJECT_DIR/.venv/bin/python"
elif [ -f "$PROJECT_DIR/.venv-wsl/bin/python" ]; then
    PYTHON="$PROJECT_DIR/.venv-wsl/bin/python"
else
    PYTHON="python"
fi

cd "$PROJECT_DIR"
exec "$PYTHON" -m app.run mcp
