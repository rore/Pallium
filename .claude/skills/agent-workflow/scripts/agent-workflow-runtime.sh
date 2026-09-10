#!/usr/bin/env bash
# Resolve the repository and an available project Python, then run the shared adapter.
set +e
RUNTIME="${1:-claude}"
ACTION="${2:-guard}"
ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || exit 0
SCRIPT="$ROOT/scripts/agent-workflow-runtime.py"
[[ -f "$SCRIPT" ]] || { echo "[agent-workflow] DEGRADED: runtime script missing; final CI remains authoritative" >&2; exit 0; }
if [[ -n "${PYTHON:-}" ]]; then PY="$PYTHON"
elif [[ -x "$ROOT/.venv/bin/python" ]]; then PY="$ROOT/.venv/bin/python"
elif [[ -x "$ROOT/.venv/Scripts/python.exe" ]]; then PY="$ROOT/.venv/Scripts/python.exe"
elif command -v python3 >/dev/null 2>&1; then PY=python3
elif command -v python >/dev/null 2>&1; then PY=python
else echo "[agent-workflow] DEGRADED: Python unavailable; final CI remains authoritative" >&2; exit 0
fi
if command -v wslpath >/dev/null 2>&1 && [[ "$PY" == *.exe ]]; then
  SCRIPT="$(wslpath -w "$SCRIPT")"
fi
if [[ "$ACTION" == "seed" ]]; then
  exec "$PY" "$SCRIPT" --runtime "$RUNTIME" --seed
fi
"$PY" "$SCRIPT" --runtime "$RUNTIME"
STATUS=$?
if [[ $STATUS -eq 0 || $STATUS -eq 2 ]]; then exit $STATUS; fi
echo "[agent-workflow] DENY: runtime adapter failed with exit $STATUS" >&2
exit 2