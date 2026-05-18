"""SessionStart hook — injects orientation memory at session beginning.

Strategy:
1. Try recency-first: GET /memory-objects/recent for task_checkpoint/task_trace.
   This bypasses retrieval ranking — pure recency on a typed predicate, immune to
   lexical attractors on boilerplate orientation queries.
2. Fall back to /query if no recent typed memories exist.

Behavioral note: Codex skips orientation injection on source=clear (preserves
prior contract). Claude Code does inject on clear; this divergence is intentional
to avoid broadcasting on user-initiated clear in Codex.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from urllib.parse import urlencode

_common_path = str(Path(__file__).resolve().parent / "common.py")
_spec = importlib.util.spec_from_file_location("codex_common", _common_path)
_common = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
sys.modules["codex_common"] = _common
_spec.loader.exec_module(_common)  # type: ignore[union-attr]

derive_actor_ref = _common.derive_actor_ref
derive_container_ref = _common.derive_container_ref
emit_context = _common.emit_context
format_injection = _common.format_injection
pallium_request = _common.pallium_request
pin_container = _common.pin_container
read_hook_input = _common.read_hook_input

ORIENTATION_TYPES = ("task_checkpoint", "task_trace")
ORIENTATION_SINCE_DAYS = 14
ORIENTATION_LIMIT = 1
RETRIEVAL_FALLBACK_QUERY = "recent decisions, progress, and open tasks"


def _fetch_recent_orientation(container_ref: str, actor_ref: str | None) -> list[dict]:
    params: list[tuple[str, str]] = [
        ("container_ref", container_ref),
        ("limit", str(ORIENTATION_LIMIT)),
        ("since_days", str(ORIENTATION_SINCE_DAYS)),
        ("visibility", "private"),
    ]
    for t in ORIENTATION_TYPES:
        params.append(("types", t))
    if actor_ref:
        params.append(("actor_ref", actor_ref))
    qs = urlencode(params)
    response = pallium_request("GET", f"/memory-objects/recent?{qs}", quiet=True)
    if not response:
        return []
    return response.get("blocks", []) or []


def _fetch_retrieval_fallback(container_ref: str, actor_ref: str) -> list[dict]:
    response = pallium_request("POST", "/query", {
        "text": RETRIEVAL_FALLBACK_QUERY,
        "container_ref": container_ref,
        "actor_ref": actor_ref,
        "visibility": "private",
        "limit": 5,
    })
    if not response:
        return []
    return response.get("injectable_blocks", []) or []


def main() -> None:
    try:
        payload = read_hook_input()
        source = payload.get("source", "")
        if source == "clear":
            sys.exit(0)

        cwd = payload.get("cwd", ".")
        session_id = payload.get("session_id")
        container_ref = derive_container_ref(cwd)
        pin_container(session_id, container_ref, source=source)
        actor_ref = derive_actor_ref()

        blocks = _fetch_recent_orientation(container_ref, actor_ref)
        if not blocks:
            blocks = _fetch_retrieval_fallback(container_ref, actor_ref)

        output = format_injection(blocks, container_ref, budget_chars=1200)
        if output:
            emit_context(output, "SessionStart")

    except Exception as exc:
        print(f"pallium session_start hook error: {exc}", file=sys.stderr)

    sys.exit(0)


if __name__ == "__main__":
    main()
