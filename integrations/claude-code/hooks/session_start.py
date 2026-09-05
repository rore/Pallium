"""SessionStart hook — issues an orientation /query at session start.

The query is built from STRUCTURAL signals available at the hook (current
git branch + recently changed/committed file paths), not a fixed English
string. A generic phrase like "recent decisions, progress, and open tasks"
shares no vocabulary with topical memory subjects, so its candidates score
lexical≈0 and are correctly filtered by the retrieval grounding gates
(BM25 floor, set-level and content-overlap gates) — session-start injection
was effectively always empty as a result.

Grounding the query on branch/file signals produces real lexical overlap
with memories about the same work, so relevant proactive memories
(decision, constraint_memory) clear the gates on merit. When there is no
signal (detached/clean tree on a generic branch), the query falls back to
the generic phrase and the container simply abstains — which is the correct
behaviour, not a gap. This deliberately does NOT bypass any grounding gate
or re-admit demoted types; see the injection-policy-abstention spec.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (
    RELAY_OUTPUT_BUDGET,
    RELAY_TURN_BUDGET,
    SUBPROCESS_TIMEOUT,
    derive_actor_ref,
    derive_container_ref,
    format_injection,
    pallium_request,
    pin_container,
    read_hook_input,
    redact_sensitive,
    register_claude_wake,
    relay_request,
    format_relay,
    acknowledge_relay,
)

# Fallback when no structural signal is available. Kept for graceful
# degradation only — it is not expected to inject much (by design).
RETRIEVAL_FALLBACK_QUERY = "recent decisions, progress, and open tasks"

# Bound the number of changed-file basenames folded into the query so it
# stays a focused signal, not a dump of the whole tree.
_MAX_CHANGED_FILES = 8

# Generic branch names carry no work signal — treat as "no branch signal".
_GENERIC_BRANCHES = frozenset({"main", "master", "develop", "trunk", "head"})


def _git(cwd: str, *args: str, strip: bool = True) -> str:
    """Run a git command, returning stdout or "" on any failure.

    `strip=True` trims surrounding whitespace (safe for single-value output
    like a branch name). Porcelain/line-oriented output must pass
    `strip=False` — `git status --porcelain` encodes state in a leading
    2-column prefix whose first column can be a space, and a global strip
    would corrupt the first line's path offset.
    """
    try:
        result = subprocess.run(
            ["git", *args],
            capture_output=True, text=True, cwd=cwd, timeout=SUBPROCESS_TIMEOUT,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout.strip() if strip else result.stdout


def _branch_tokens(cwd: str) -> list[str]:
    """Tokens from the current branch name, minus generic base branches."""
    branch = _git(cwd, "rev-parse", "--abbrev-ref", "HEAD")
    if not branch or branch.lower() in _GENERIC_BRANCHES:
        return []
    # Split on the usual branch separators; drop empties.
    raw = branch.replace("/", " ").replace("-", " ").replace("_", " ").split()
    return [t for t in raw if t]


def _changed_file_tokens(cwd: str) -> list[str]:
    """File-name stems from the working tree + recent commits.

    Combines `git status --porcelain` (uncommitted work) with the files
    touched in the last few commits, so a clean tree on an active branch
    still yields a signal. Returns de-duplicated basename stems.
    """
    paths: list[str] = []

    # strip=False: porcelain encodes state in the leading "XY " prefix; a
    # global strip would shift the first line and corrupt line[3:].
    status = _git(cwd, "status", "--porcelain", strip=False)
    for line in status.splitlines():
        # Porcelain format: "XY <path>" (path starts at column 3).
        path = line[3:].strip() if len(line) > 3 else ""
        if path:
            # Handle rename arrows "old -> new".
            path = path.split("->")[-1].strip()
            # Git C-quotes paths with special chars: "dir/odd name.py".
            path = path.strip('"')
            paths.append(path)

    recent = _git(cwd, "log", "-3", "--name-only", "--pretty=format:", strip=False)
    for line in recent.splitlines():
        line = line.strip()
        if line:
            paths.append(line)

    stems: list[str] = []
    seen: set[str] = set()
    for path in paths:
        stem = Path(path).stem  # basename without extension
        if stem and stem not in seen:
            seen.add(stem)
            stems.append(stem)
        if len(stems) >= _MAX_CHANGED_FILES:
            break
    return stems


def _derive_orientation_query(cwd: str) -> str:
    """Build a grounded orientation query from structural git signals.

    Falls back to the generic phrase when no branch/file signal exists.
    Redacted defensively in case a path or branch carries a secret.
    """
    tokens = _branch_tokens(cwd) + _changed_file_tokens(cwd)
    if not tokens:
        return RETRIEVAL_FALLBACK_QUERY
    query = " ".join(tokens)
    return redact_sensitive(query)


def _fetch_orientation(query_text: str, container_ref: str, actor_ref: str) -> list[dict]:
    response = pallium_request("POST", "/query", {
        "text": query_text,
        "container_ref": container_ref,
        "actor_ref": actor_ref,
        "visibility": "private",
        "limit": 5,
        # Tag the orientation query so it's distinguishable in audit-log
        # analysis (Phase 6 measurement) from per-message and Phase 4 triggers.
        "trigger_origin": "session_start_orientation",
    })
    if not response:
        return []
    return response.get("injectable_blocks", []) or []


def main() -> None:
    try:
        payload = read_hook_input()
        cwd = payload.get("cwd", ".")
        session_id = payload.get("session_id")
        source = payload.get("source", "")
        container_ref = derive_container_ref(cwd)
        pin_container(session_id, container_ref, source=source)
        actor_ref = derive_actor_ref()
        register_claude_wake(session_id, container_ref, actor_ref, idle=False)

        relay_scope = format_injection(
            [], container_ref, budget_chars=RELAY_OUTPUT_BUDGET,
            thread_ref=session_id, actor_ref=actor_ref,
            agent_ref="claude-code", visibility="private",
        )
        relay_response = (
            relay_request("POST", "/relay/turn", {
                "runtime": "claude-code", "session_ref": session_id,
                "container_ref": container_ref, "actor_ref": actor_ref,
                "max_chars": RELAY_TURN_BUDGET,
            }, timeout=0.75) or {}
        ) if relay_scope else {}
        relay_output, rendered = format_relay(
            relay_response.get("deliveries") or [],
            budget_chars=RELAY_OUTPUT_BUDGET,
            remaining_count=(
                relay_response.get("remaining_count")
                if relay_response.get("has_more") is True else 0
            ),
        )
        if rendered:
            print("\n\n".join((relay_output, relay_scope)))
            acknowledge_relay(rendered, container_ref=container_ref, actor_ref=actor_ref)
            sys.exit(0)

        query_text = _derive_orientation_query(cwd)
        blocks = _fetch_orientation(query_text, container_ref, actor_ref)

        output = format_injection(blocks, container_ref, budget_chars=1200, thread_ref=session_id, actor_ref=actor_ref, agent_ref="claude-code", visibility="private")
        if output:
            print(output)

    except Exception:
        print("pallium session_start hook error", file=sys.stderr)

    sys.exit(0)


if __name__ == "__main__":
    main()
