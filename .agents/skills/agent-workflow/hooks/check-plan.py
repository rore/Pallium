#!/usr/bin/env python3
"""agent-workflow PreToolUse(ExitPlanMode) gate — decision logic.

Reads the hook payload on stdin. If the presented plan changes code under a
*guarded path* but omits the agent-workflow / Work Record step, exit 2 and
print the revision reason to stderr (Claude Code surfaces stderr as the deny
reason, so the model revises the plan and re-presents). Otherwise exit 0
(allow).

Guarded paths are repo-configurable so the gate works regardless of code
layout (not every repo puts code under ``src/``). The installer resolves
``hooks.guardedPaths`` from the repo's ``agent-workflow.yaml`` into a sidecar
JSON file next to this script (``guarded-paths.json``). This hook reads that
sidecar with the standard library only (no yaml dependency at hook time). When
the sidecar is absent or unreadable the gate falls back to ``["src/"]`` — the
historical default — so behaviour is backward compatible.

DEFENSIVE / FAIL OPEN: any error, missing field, or unparseable input results
in exit 0. A gate that cannot read the plan must never block the user.
"""
import json
import os
import re
import sys

DEFAULT_GUARDED_PATHS = ["src/"]
_SIDECAR_NAME = "guarded-paths.json"


def _log(cwd, msg):
    """Best-effort decision log; never raises."""
    try:
        d = os.path.join(cwd or ".", ".agent-workflow")
        if os.path.isdir(d):
            with open(os.path.join(d, ".hooks.log"), "a", encoding="utf-8") as fh:
                fh.write(msg + "\n")
    except Exception:
        pass


def _load_guarded_paths():
    """Read guarded path prefixes from the sidecar next to this script.

    Returns the historical default (``["src/"]``) on any problem — missing
    file, bad JSON, wrong shape, empty list — so the gate never silently
    turns into a no-op *and* never blocks on a malformed config.
    """
    try:
        here = os.path.dirname(os.path.abspath(__file__))
        sidecar = os.path.join(here, _SIDECAR_NAME)
        with open(sidecar, encoding="utf-8") as fh:
            data = json.load(fh)
        raw = data.get("guardedPaths") if isinstance(data, dict) else None
        if not isinstance(raw, list):
            return DEFAULT_GUARDED_PATHS
        paths = [p for p in raw if isinstance(p, str) and p.strip()]
        return paths or DEFAULT_GUARDED_PATHS
    except Exception:
        return DEFAULT_GUARDED_PATHS


def _matches_any(low_plan, prefixes):
    """True if the lowercased plan references any guarded prefix on a path
    boundary. Boundary-anchored so a prefix like ``core/`` does not trip on
    ``score/``; case-insensitive (both sides already lowercased)."""
    for prefix in prefixes:
        p = prefix.lower().strip()
        if not p:
            continue
        # Preceded by start-of-string or a non-path-word character. The input
        # (low_plan) and prefix are already lowercased by the caller, so the
        # exclusion set need only cover lowercase; excluding [a-z0-9_.-] means
        # 'score/' does not match a 'core/' prefix, while 'in core/', '`core/`',
        # '(core/' etc. do.
        pattern = r"(?:^|[^0-9a-z_.\-])" + re.escape(p)
        if re.search(pattern, low_plan):
            return True
    return False


def main():
    try:
        raw = sys.stdin.read()
    except Exception:
        return 0
    if not raw or not raw.strip():
        return 0
    try:
        payload = json.loads(raw)
    except Exception:
        return 0  # unparseable envelope -> allow

    if not isinstance(payload, dict):
        return 0
    cwd = payload.get("cwd") or "."
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return 0
    plan = tool_input.get("plan")
    if not isinstance(plan, str) or not plan.strip():
        return 0  # no plan text -> nothing to gate

    guarded = _load_guarded_paths()
    low = plan.lower()
    touches_guarded = _matches_any(low, guarded)
    has_step = ("agent-workflow" in low) or ("work record" in low)

    if touches_guarded and not has_step:
        shown = ", ".join(guarded)
        _log(cwd, "gate: DENY (plan touches guarded path [%s], no Work Record step)" % shown)
        sys.stderr.write(
            "[agent-workflow] Revise the plan before presenting it.\n"
            "This plan changes code under a guarded path (%s), so its FIRST "
            "implementation step must be:\n"
            "\"Invoke the /agent-workflow skill to create the Work Record and classify risk "
            "(before any code edit).\"\n"
            "Add that step to the plan, then call ExitPlanMode again.\n" % shown
        )
        return 2

    _log(cwd, "gate: ALLOW (touches_guarded=%s has_step=%s)" % (touches_guarded, has_step))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)  # last-resort fail-open
