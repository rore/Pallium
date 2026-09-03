"""Stop hook — ingests the assistant's last response from the transcript.

Also implements the Phase 5b memory_usage_audit populator:
  1. After ingest, GET /memory-usage-audit?thread_ref=<session_id> to
     fetch usage-audit rows that are still pending (populated_at IS NULL).
  2. For each pending row, run the matcher (id_quote / verbatim_snippet)
     against the assistant transcript.
  3. POST /memory-usage-audit/<row_id> with the verdict. The POST is
     idempotent server-side, so retries are safe.
  4. Fire-and-forget per row; failures log to stderr and never block
     the hook from exiting 0.

See docs/specs/2026-06-27-injection-policy-abstention.md (Phase 5b).
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (
    acknowledge_relay,
    build_work_trace_metadata,
    derive_actor_ref,
    format_relay,
    pallium_request,
    read_hook_input,
    read_turn,
    register_claude_wake,
    relay_request,
    resolve_container_ref,
)
from usage_audit_matcher import classify_memory_reference

CONTENT_LENGTH_GATE = 20_000


def _emit_relay(text: str) -> None:
    if (sys.stderr.encoding or "").lower().replace("-", "") == "utf8":
        print(text, file=sys.stderr)
    else:
        sys.stderr.buffer.write((text + "\n").encode("utf-8"))


def _populate_usage_audit_rows(session_id: str, assistant_text: str) -> None:
    """Phase 5b: discover pending usage-audit rows for this thread and
    POST a verdict for each based on the assistant's just-finished
    response.

    Fails silently on any error — populator data is best-effort
    telemetry, not load-bearing for any user-visible behavior.
    """
    if not session_id or not assistant_text:
        return
    response = pallium_request(
        "GET",
        f"/memory-usage-audit?thread_ref={session_id}&limit=20",
        None,
    )
    if not response:
        return
    rows = response.get("rows") or []
    for row in rows:
        try:
            row_id = row.get("id")
            memory_object_id = row.get("memory_object_id") or ""
            # The list endpoint doesn't return the memory's text/title.
            # Fetch a one-block summary from the memory itself via the
            # expand endpoint to get matchable text.
            mem_text = _fetch_memory_match_text(memory_object_id)
            referenced, kind = classify_memory_reference(
                memory_object_id=memory_object_id,
                memory_text=mem_text,
                response_text=assistant_text,
            )
            pallium_request(
                "POST",
                f"/memory-usage-audit/{row_id}",
                {
                    "referenced_in_next_turn": referenced,
                    "reference_kind": kind,
                    "observation_window_turns": 1,
                },
            )
        except Exception as exc:
            print(
                f"pallium stop hook: usage-audit populate failed: {type(exc).__name__}",
                file=sys.stderr,
            )


def _fetch_memory_match_text(memory_object_id: str) -> str:
    """Fetch a memory's display-text for matching.

    Uses the existing memory-expand endpoint. Returns empty string on
    any failure — the matcher tolerates empty input by simply not
    matching. Bounded by the matcher's own MATCH_TEXT_MAX_CHARS.

    Prefers the server-side ``match_text`` field (Phase 5b, 2026-06-28)
    which uses the canonical per-type text builder shared with the
    embedding view. Falls back to the legacy hardcoded scalar-field
    coalesce for older Pallium servers that predate that field — keeps
    the hook self-contained and avoids hard-cutting compatibility on
    integration upgrades.
    """
    if not memory_object_id:
        return ""
    expand = pallium_request(
        "GET",
        f"/memory/{memory_object_id}/expand",
        None,
    )
    if not expand or not isinstance(expand, dict):
        return ""
    # Phase 5b preferred path: server-side per-type match text.
    match_text = expand.get("match_text")
    if isinstance(match_text, str) and match_text:
        return match_text
    # Fallback: legacy scalar-field coalesce. Older Pallium servers do
    # not return match_text. The narrow field list is known to undercount
    # for task_checkpoint / continuity_memory / thread_summary; once the
    # server is upgraded the preferred path above kicks in.
    payload = expand.get("payload") or {}
    parts: list[str] = []
    for key in (
        "summary", "decision", "investigation_outcome", "text",
        "constraint_text", "interest_text", "title",
    ):
        val = payload.get(key)
        if isinstance(val, str) and val:
            parts.append(val)
    return "\n".join(parts)


def main() -> None:
    try:
        payload = read_hook_input()
        session_id = payload.get("session_id")
        cwd = payload.get("cwd", ".")
        transcript_path = payload.get("transcript_path", "")
        container_ref = resolve_container_ref(cwd, session_id)
        actor_ref = derive_actor_ref()
        register_claude_wake(session_id, container_ref, actor_ref, idle=True)

        if payload.get("stop_hook_active") is not True and isinstance(session_id, str) and session_id:
            try:
                turn = relay_request(
                    "POST",
                    "/relay/turn",
                    {
                        "runtime": "claude-code",
                        "session_ref": session_id,
                        "container_ref": container_ref,
                        "actor_ref": actor_ref,
                        "max_chars": 2400,
                    },
                    timeout=0.75,
                ) or {}
                deliveries = turn.get("deliveries") if isinstance(turn, dict) else []
                _, claimed = format_relay(deliveries or [])
                acknowledged = acknowledge_relay(
                    claimed, container_ref=container_ref, actor_ref=actor_ref,
                )
                rendered, _ = format_relay(acknowledged)
                if rendered:
                    _emit_relay(rendered)
                    raise SystemExit(2)
            except Exception:
                pass
            register_claude_wake(session_id, container_ref, actor_ref, idle=True)
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

        # Phase 5b: populate memory_usage_audit rows now that we've
        # observed the assistant's response.
        _populate_usage_audit_rows(session_id, content)

    except Exception:
        print("pallium stop hook error", file=sys.stderr)

    sys.exit(0)


if __name__ == "__main__":
    main()
