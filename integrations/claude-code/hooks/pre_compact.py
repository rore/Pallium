"""PreCompact hook — re-injects key context before compaction."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (
    derive_actor_ref,
    derive_container_ref,
    format_injection,
    pallium_request,
    read_hook_input,
)


def main() -> None:
    try:
        payload = read_hook_input()
        cwd = payload.get("cwd", ".")
        session_id = payload.get("session_id")
        container_ref = derive_container_ref(cwd)
        actor_ref = derive_actor_ref()

        query_payload = {
            "text": "recent decisions, progress, and open tasks",
            "container_ref": container_ref,
            "actor_ref": actor_ref,
            "visibility": "private",
            "limit": 8,
        }
        if session_id:
            query_payload["thread_ref"] = session_id

        response = pallium_request("POST", "/query", query_payload)

        if not response:
            return

        blocks = response.get("injectable_blocks", [])
        output = format_injection(blocks, container_ref, budget_chars=2400)
        if output:
            print(output)

    except Exception as exc:
        print(f"pallium pre_compact hook error: {exc}", file=sys.stderr)

    sys.exit(0)


if __name__ == "__main__":
    main()
