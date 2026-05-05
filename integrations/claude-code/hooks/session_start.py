"""SessionStart hook — injects orientation memory at session beginning."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (
    STATE_DIR,
    derive_actor_ref,
    derive_container_ref,
    format_injection,
    pallium_request,
    read_hook_input,
)


def _write_work_trace_state(session_id: str, trace_payload: dict) -> None:
    """Write injected task_trace payload to state file for offline measurement."""
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        state_file = STATE_DIR / f"{session_id}.work_trace_state.json"
        state_file.write_text(json.dumps(trace_payload), encoding="utf-8")
    except OSError:
        pass


def main() -> None:
    try:
        payload = read_hook_input()
        cwd = payload.get("cwd", ".")
        session_id = payload.get("session_id")
        source = payload.get("source", "")
        container_ref = derive_container_ref(cwd)
        actor_ref = derive_actor_ref()

        query_payload = {
            "text": "recent decisions, progress, and open tasks",
            "container_ref": container_ref,
            "actor_ref": actor_ref,
            "visibility": "private",
            "limit": 5,
        }
        if session_id:
            query_payload["thread_ref"] = session_id

        response = pallium_request("POST", "/query", query_payload)

        blocks: list[dict] = []
        if response:
            blocks = response.get("injectable_blocks", [])

        # Scoped task_trace injection on session resume
        if source in ("resume", "clear") and session_id:
            trace_response = pallium_request("POST", "/query", {
                "text": f"task_trace for thread {session_id}",
                "container_ref": container_ref,
                "actor_ref": actor_ref,
                "visibility": "private",
                "thread_ref": session_id,
                "limit": 1,
            })
            if trace_response:
                trace_blocks = trace_response.get("injectable_blocks", [])
                for tb in trace_blocks:
                    if "task_trace" in tb.get("title", "").lower() or "task_trace" in tb.get("text", "").lower():
                        blocks.append(tb)
                        _write_work_trace_state(session_id, tb)
                        break

        output = format_injection(blocks, container_ref, budget_chars=1200)
        if output:
            print(output)

    except Exception as exc:
        print(f"pallium session_start hook error: {exc}", file=sys.stderr)

    sys.exit(0)


if __name__ == "__main__":
    main()
