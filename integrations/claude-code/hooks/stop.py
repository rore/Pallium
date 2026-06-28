"""Stop hook — ingests the assistant's last response from the transcript.

Phase 5b contract (TODO; not yet implemented in this hook):
    After ingesting the assistant response, this hook will be the
    natural site for the `memory_usage_audit` populator:
      1. For each recent query_audit_log row from this thread within
         the last few turns, GET /memory-usage-audit?query_audit_log_id=...
      2. For each returned row with populated_at IS NULL, run the
         minimum-viable matcher against the assistant transcript:
           - id_quote: look for `ref:<memory_object_id>` mentions
           - verbatim_snippet: any snippet >= 40 chars from the memory
             block's text appears in the transcript
      3. POST /memory-usage-audit/<row_id> with the result. POST is
         idempotent — re-populating a row no-ops, so retrying safely
         after transient errors is fine.
    See docs/specs/2026-06-27-injection-policy-abstention.md (Phase 5b).
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (
    build_work_trace_metadata,
    derive_actor_ref,
    pallium_request,
    read_hook_input,
    read_turn,
    resolve_container_ref,
)

CONTENT_LENGTH_GATE = 20_000


def main() -> None:
    try:
        payload = read_hook_input()
        session_id = payload.get("session_id", "unknown")
        cwd = payload.get("cwd", ".")
        transcript_path = payload.get("transcript_path", "")

        if not transcript_path:
            return

        turn_data = read_turn(transcript_path)
        if not turn_data:
            return
        if not turn_data.assistant_text and not turn_data.tool_calls:
            return
        content = turn_data.assistant_text
        if len(content) > CONTENT_LENGTH_GATE:
            return

        container_ref = resolve_container_ref(cwd, session_id)
        actor_ref = derive_actor_ref()

        metadata = {}
        work_trace_meta = build_work_trace_metadata(turn_data)
        if work_trace_meta:
            metadata["agent_work_trace_turn"] = work_trace_meta
            metadata["cwd"] = cwd

        item_payload = {
            "source_type": "claude-code",
            "source_id": f"cc-{uuid.uuid4().hex[:12]}",
            "content_type": "text/plain",
            "content": content,
            "role": "assistant",
            "agent_ref": "claude-code",
            "container_ref": container_ref,
            "thread_ref": session_id,
            "actor_ref": actor_ref,
            "visibility": "private",
            "artifact_kind": "message",
        }
        if metadata:
            item_payload["metadata"] = metadata

        pallium_request("POST", "/items", [item_payload])

    except Exception as exc:
        print(f"pallium stop hook error: {exc}", file=sys.stderr)

    sys.exit(0)


if __name__ == "__main__":
    main()
