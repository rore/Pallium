"""Stop hook — ingests the assistant's last response from the transcript.

Also implements the Phase 5b memory_usage_audit populator (same shape
as the Claude Code Stop hook). See
docs/specs/2026-06-27-injection-policy-abstention.md (Phase 5b).
"""

from __future__ import annotations

import importlib.util
import sys
import uuid
from pathlib import Path

_common_path = str(Path(__file__).resolve().parent / "common.py")
_spec = importlib.util.spec_from_file_location("codex_common", _common_path)
_common = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
sys.modules["codex_common"] = _common
_spec.loader.exec_module(_common)  # type: ignore[union-attr]

AGENT_REF = _common.AGENT_REF
SOURCE_TYPE = _common.SOURCE_TYPE
build_work_trace_metadata = _common.build_work_trace_metadata
derive_actor_ref = _common.derive_actor_ref
derive_container_ref = _common.derive_container_ref
pallium_request = _common.pallium_request
read_hook_input = _common.read_hook_input
read_turn = _common.read_turn
resolve_container_ref = _common.resolve_container_ref

# Phase 5b: load the matcher module (shared with Claude Code's stop hook).
# It lives under integrations/claude-code/hooks/ — load it via importlib to
# avoid duplicating the implementation. Codex and Claude Code share the
# same matcher contract.
_matcher_path = str(
    Path(__file__).resolve().parents[2]
    / "claude-code"
    / "hooks"
    / "usage_audit_matcher.py"
)
_matcher_spec = importlib.util.spec_from_file_location(
    "pallium_usage_audit_matcher", _matcher_path
)
_matcher = importlib.util.module_from_spec(_matcher_spec)  # type: ignore[arg-type]
sys.modules["pallium_usage_audit_matcher"] = _matcher
_matcher_spec.loader.exec_module(_matcher)  # type: ignore[union-attr]
classify_memory_reference = _matcher.classify_memory_reference

CONTENT_LENGTH_GATE = 20_000


def _populate_usage_audit_rows(session_id: str, assistant_text: str) -> None:
    """Phase 5b — see Claude Code's stop.py for the contract. Fail-silent
    per row; populator data is best-effort telemetry.
    """
    if not session_id or not assistant_text:
        return
    response = pallium_request(
        "GET",
        f"/memory-usage-audit?thread_ref={session_id}&limit=20",
        None,
        quiet=True,
    )
    if not response:
        return
    rows = response.get("rows") or []
    for row in rows:
        try:
            row_id = row.get("id")
            memory_object_id = row.get("memory_object_id") or ""
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
                quiet=True,
            )
        except Exception as exc:
            print(
                f"pallium codex stop hook: usage-audit populate failed for "
                f"row {row.get('id')!r}: {exc}",
                file=sys.stderr,
            )


def _fetch_memory_match_text(memory_object_id: str) -> str:
    """Fetch a memory's display-text for matching. Returns "" on failure."""
    if not memory_object_id:
        return ""
    expand = pallium_request(
        "GET",
        f"/memory/{memory_object_id}/expand",
        None,
        quiet=True,
    )
    if not expand or not isinstance(expand, dict):
        return ""
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
        session_id = payload.get("session_id", "unknown")
        cwd = payload.get("cwd", ".")
        transcript_path = payload.get("transcript_path", "")

        if not transcript_path:
            sys.exit(0)

        turn_data = read_turn(transcript_path)
        if not turn_data:
            sys.exit(0)
        if not turn_data.assistant_text and not turn_data.tool_calls:
            sys.exit(0)
        content = turn_data.assistant_text
        if len(content) > CONTENT_LENGTH_GATE:
            sys.exit(0)

        container_ref = resolve_container_ref(cwd, session_id)
        actor_ref = derive_actor_ref()

        metadata = {}
        work_trace_meta = build_work_trace_metadata(turn_data)
        if work_trace_meta:
            metadata["agent_work_trace_turn"] = work_trace_meta
            metadata["cwd"] = cwd

        item_payload = {
            "source_type": SOURCE_TYPE,
            "source_id": f"cdx-{uuid.uuid4().hex[:12]}",
            "content_type": "text/plain",
            "content": content,
            "role": "assistant",
            "agent_ref": AGENT_REF,
            "container_ref": container_ref,
            "thread_ref": session_id,
            "actor_ref": actor_ref,
            "visibility": "private",
            "artifact_kind": "message",
        }
        if metadata:
            item_payload["metadata"] = metadata

        pallium_request("POST", "/items", [item_payload], quiet=True)

        # Phase 5b: populate memory_usage_audit rows now that we've
        # observed the assistant's response.
        _populate_usage_audit_rows(session_id, content)

    except Exception as exc:
        print(f"pallium stop hook error: {exc}", file=sys.stderr)

    sys.exit(0)


if __name__ == "__main__":
    main()
