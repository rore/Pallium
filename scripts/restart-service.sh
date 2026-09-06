#!/usr/bin/env bash
#
# Restart Pallium through the canonical service CLI.
#
# Usage:
#   ./restart-service.sh [--home PATH] [--python PATH]
#

set -euo pipefail

PYTHON_PATH=""
HOME_PATH=""

usage() {
    echo "Usage: $0 [--home PATH] [--python PATH]" >&2
    exit 1
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --home)
            [[ $# -ge 2 ]] || usage
            HOME_PATH="$2"
            shift 2
            ;;
        --python)
            [[ $# -ge 2 ]] || usage
            PYTHON_PATH="$2"
            shift 2
            ;;
        *)
            usage
            ;;
    esac
done

if [[ -z "$PYTHON_PATH" ]]; then
    PYTHON_PATH=$(command -v python3 2>/dev/null || command -v python 2>/dev/null || true)
fi
if [[ -z "$PYTHON_PATH" ]]; then
    echo "Error: Python not found. Specify --python or ensure Python is on PATH."
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$REPO_ROOT"

ARGS=(service restart)
if [[ -n "$HOME_PATH" ]]; then
    ARGS+=(--home "$HOME_PATH")
fi
exec "$PYTHON_PATH" -m app.run "${ARGS[@]}"
