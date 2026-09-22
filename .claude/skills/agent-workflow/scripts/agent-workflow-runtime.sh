#!/usr/bin/env bash
# Resolve the repository and an available project Python, then run the shared adapter.
set +e
RUNTIME="${1:-claude}"
ACTION="${2:-guard}"
[[ $# -gt 0 ]] && shift
[[ $# -gt 0 ]] && shift

unavailable() {
  if [[ "$ACTION" == "check" ]]; then
    echo "[agent-workflow] ERROR: $1" >&2
    exit 2
  fi
  echo "[agent-workflow] DEGRADED: $1; final CI remains authoritative" >&2
  exit 0
}

ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || unavailable "git repository unavailable"
if [[ "$ACTION" == "check" ]]; then SCRIPT="$ROOT/scripts/agent-workflow-check.py"
else SCRIPT="$ROOT/scripts/agent-workflow-runtime.py"
fi
[[ -f "$SCRIPT" ]] || unavailable "$(basename "$SCRIPT") missing"
if [[ -n "${PYTHON:-}" ]]; then PY="$PYTHON"
elif [[ -x "$ROOT/.venv/bin/python" ]]; then PY="$ROOT/.venv/bin/python"
elif [[ -x "$ROOT/.venv/Scripts/python.exe" ]]; then PY="$ROOT/.venv/Scripts/python.exe"
elif command -v python3 >/dev/null 2>&1; then PY=python3
elif command -v python >/dev/null 2>&1; then PY=python
else unavailable "Python 3.11+ unavailable; install or select it, or set PYTHON to one executable path"
fi
if command -v wslpath >/dev/null 2>&1 && [[ "$PY" == *.exe ]]; then
  SCRIPT="$(wslpath -w "$SCRIPT")"
fi
if [[ "$ACTION" == "seed" ]]; then
  exec "$PY" "$SCRIPT" --runtime "$RUNTIME" --seed
fi
if [[ "$ACTION" == "check" ]]; then
  PROBE="$("$PY" -c 'import sys; assert sys.version_info >= (3, 11); print("agent-workflow-python-3.11")' 2>/dev/null)"
  [[ $? -eq 0 && "$PROBE" == "agent-workflow-python-3.11" ]] || unavailable "selected Python unavailable or older than 3.11: $PY; install or select Python 3.11+, or set PYTHON to one executable path"
  "$PY" "$SCRIPT" "$@"
  STATUS=$?
  if [[ $STATUS -eq 0 || $STATUS -eq 1 || $STATUS -eq 2 ]]; then exit $STATUS; fi
  if [[ $STATUS -eq 126 || $STATUS -eq 127 ]]; then
    echo "[agent-workflow] ERROR: Python unavailable: $PY; install or select Python 3.11+, or set PYTHON to one executable path" >&2
    exit 2
  fi
  echo "[agent-workflow] ERROR: checker failed with exit $STATUS" >&2
  exit 2
fi
"$PY" "$SCRIPT" --runtime "$RUNTIME"
STATUS=$?
if [[ $STATUS -eq 0 || $STATUS -eq 2 ]]; then exit $STATUS; fi
echo "[agent-workflow] DENY: runtime adapter failed with exit $STATUS" >&2
exit 2