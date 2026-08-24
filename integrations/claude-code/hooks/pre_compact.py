"""PreCompact hook — re-injects key context before compaction."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (
    derive_actor_ref,
    format_injection,
    pallium_request,
    read_hook_input,
    resolve_container_ref,
)


def main() -> None:
    try:
        payload = read_hook_input()
        cwd = payload.get("cwd", ".")
        session_id = payload.get("session_id")
        container_ref = resolve_container_ref(cwd, session_id)
        actor_ref = derive_actor_ref()

        query_payload = {
            "text": "recent decisions, progress, and open tasks",
            "container_ref": container_ref,
            "actor_ref": actor_ref,
            "visibility": "private",
            "limit": 8,
            # Phase 4: tag for audit-log analysis.
            "trigger_origin": "pre_compact",
        }
        if session_id:
            query_payload["thread_ref"] = session_id

        response = pallium_request("POST", "/query", query_payload)

        blocks: list[dict] = []
        if response:
            blocks = response.get("injectable_blocks", [])

        # Inject current session's task_trace if one exists
        if session_id:
            trace_response = pallium_request("POST", "/query", {
                "text": f"task_trace for thread {session_id}",
                "container_ref": container_ref,
                "actor_ref": actor_ref,
                "visibility": "private",
                "thread_ref": session_id,
                "limit": 1,
                "trigger_origin": "pre_compact",
            })
            if trace_response:
                trace_blocks = trace_response.get("injectable_blocks", [])
                for tb in trace_blocks:
                    if "task_trace" in tb.get("title", "").lower() or "task_trace" in tb.get("text", "").lower():
                        blocks.append(tb)
                        break

        output = format_injection(blocks, container_ref, budget_chars=2400, thread_ref=session_id, actor_ref=actor_ref, agent_ref="claude-code", visibility="private")
        if output:
            print(output)

    except Exception as exc:
        print(f"pallium pre_compact hook error: {exc}", file=sys.stderr)

    sys.exit(0)


if __name__ == "__main__":
    main()
