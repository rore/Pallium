"""SessionStart hook — issues a /query for recent decisions, progress, and open tasks at session start."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (
    derive_actor_ref,
    derive_container_ref,
    format_injection,
    pallium_request,
    pin_container,
    read_hook_input,
)

RETRIEVAL_FALLBACK_QUERY = "recent decisions, progress, and open tasks"


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
        cwd = payload.get("cwd", ".")
        session_id = payload.get("session_id")
        source = payload.get("source", "")
        container_ref = derive_container_ref(cwd)
        pin_container(session_id, container_ref, source=source)
        actor_ref = derive_actor_ref()

        blocks = _fetch_retrieval_fallback(container_ref, actor_ref)

        output = format_injection(blocks, container_ref, budget_chars=1200)
        if output:
            print(output)

    except Exception as exc:
        print(f"pallium session_start hook error: {exc}", file=sys.stderr)

    sys.exit(0)


if __name__ == "__main__":
    main()
