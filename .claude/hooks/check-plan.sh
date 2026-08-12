#!/usr/bin/env bash
# agent-workflow PreToolUse(ExitPlanMode) hook — "gate" (shim).
# Delegates plan inspection to check-plan.py (robust JSON parsing). Denies via
# exit 2 + stderr (portable; no stdout-JSON dependency). FAIL OPEN on any error,
# including python being unavailable — a missing interpreter must never block.
set +e
DIR="$(cd "$(dirname "$0")" 2>/dev/null && pwd)"
PY="${PYTHON:-}"
[ -z "$PY" ] && command -v python  >/dev/null 2>&1 && PY="python"
[ -z "$PY" ] && command -v python3 >/dev/null 2>&1 && PY="python3"
[ -z "$PY" ] && exit 0                      # no interpreter -> allow
[ -f "$DIR/check-plan.py" ] || exit 0       # no logic file -> allow
"$PY" "$DIR/check-plan.py"                  # inherits stdin; prints reason to stderr; exits 0/2
rc=$?
[ "$rc" = "2" ] && exit 2
exit 0                                       # any non-2 (incl. python error) -> allow
