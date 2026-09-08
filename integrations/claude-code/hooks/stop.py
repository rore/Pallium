"""Stop hook — delivers Relay and durably ingests the last assistant turn."""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (
    RELAY_OUTPUT_BUDGET,
    RELAY_TURN_BUDGET,
    acknowledge_relay,
    build_work_trace_metadata,
    build_work_refs_metadata,
    derive_actor_ref,
    emit_utf8,
    format_injection,
    format_relay,
    pallium_request,
    read_hook_input,
    read_turn,
    register_claude_wake,
    relay_request,
    resolve_container_ref,
    start_hook_deadline,
)
CONTENT_LENGTH_GATE = 20_000


def _emit_relay(text: str) -> None:
    if not emit_utf8(text, stream=sys.stderr):
        raise OSError("hook output unavailable")


def main() -> None:
    try:
        start_hook_deadline(15, host_reserve=1)
        payload = read_hook_input()
        session_id = payload.get("session_id")
        cwd = payload.get("cwd", ".")
        transcript_path = payload.get("transcript_path", "")
        container_ref = resolve_container_ref(cwd, session_id)
        actor_ref = derive_actor_ref(cwd, session_id)
        register_claude_wake(session_id, container_ref, idle=True)

        if payload.get("stop_hook_active") is not True and isinstance(session_id, str) and session_id:
            try:
                relay_scope = format_injection(
                    [], container_ref, budget_chars=RELAY_OUTPUT_BUDGET,
                    thread_ref=session_id, actor_ref=actor_ref,
                    agent_ref="claude-code", visibility="private",
                )
                turn = (
                    relay_request(
                        "POST",
                        "/relay/turn",
                        {
                            "runtime": "claude-code",
                            "session_ref": session_id,
                            "container_ref": container_ref,
                            "max_chars": RELAY_TURN_BUDGET,
                        },
                        timeout=0.75,
                    ) or {}
                ) if relay_scope else {}
                deliveries = turn.get("deliveries") if isinstance(turn, dict) else []
                remaining_count = (
                    turn.get("remaining_count") if turn.get("has_more") is True else 0
                )
                rendered, claimed = format_relay(
                    deliveries or [], budget_chars=RELAY_OUTPUT_BUDGET, remaining_count=remaining_count,
                )
                if rendered:
                    _emit_relay("\n\n".join((rendered, relay_scope)))
                    acknowledge_relay(
                        claimed, container_ref=container_ref,
                    )
                    raise SystemExit(2)
            except Exception:
                pass
            register_claude_wake(session_id, container_ref, idle=True)
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

        metadata = build_work_refs_metadata(cwd, payload.get("pallium_work_refs"))
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

    except Exception:
        print("pallium stop hook error", file=sys.stderr)

    sys.exit(0)


if __name__ == "__main__":
    main()
