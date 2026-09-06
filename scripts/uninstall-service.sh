#!/usr/bin/env bash
#
# Uninstall Pallium through the canonical service CLI.
#
# Usage:
#   ./uninstall-service.sh [--home PATH] [--python PATH] [--remove-data]
#

set -euo pipefail

PYTHON_PATH=""
HOME_PATH=""
REMOVE_DATA=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --home)
            HOME_PATH="$2"
            shift 2
            ;;
        --python)
            PYTHON_PATH="$2"
            shift 2
            ;;
        --remove-data)
            REMOVE_DATA=true
            shift
            ;;
        *)
            echo "Usage: $0 [--home PATH] [--python PATH] [--remove-data]"
            exit 1
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

ARGS=(service uninstall)
if [[ -n "$HOME_PATH" ]]; then
    ARGS+=(--home "$HOME_PATH")
fi
if [[ "$REMOVE_DATA" == true ]]; then
    ARGS+=(--remove-data)
fi
exec "$PYTHON_PATH" -m app.run "${ARGS[@]}"
