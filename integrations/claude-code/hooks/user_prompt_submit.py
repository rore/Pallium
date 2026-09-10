"""UserPromptSubmit hook — delivers Relay, ingests the prompt, and injects memory."""

from __future__ import annotations

import re
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (
    RELAY_OUTPUT_BUDGET,
    RELAY_TURN_BUDGET,
    acknowledge_relay,
    check_dedup,
    close_claude_wake,
    complete_relay_closes,
    derive_actor_ref,
    emit_utf8,
    format_injection,
    format_relay,
    get_pending_relay_close_batch,
    pallium_request,
    read_hook_input,
    relay_request,
    resolve_container_ref,
    build_work_refs_metadata,
    structural_work_refs_payload,
    confirmed_registry_work_refs,
    discover_work_refs,
    injected_work_ref,
    work_ref_warning,
    register_claude_wake,
    start_hook_deadline,
)

_IDE_TAG_RE = re.compile(
    r"<ide_(?:opened_file|selection)>.*?</ide_(?:opened_file|selection)>",
    re.DOTALL,
)

def _strip_ide_context(text: str) -> str:
    return _IDE_TAG_RE.sub("", text).strip()

def main() -> None:
    try:
        start_hook_deadline(8, host_reserve=1)
        payload = read_hook_input()
        session_id = payload.get("session_id")
        cwd = payload.get("cwd", ".")
        prompt = payload.get("prompt", "")
        has_session = isinstance(session_id, str) and bool(session_id)
        container_ref = resolve_container_ref(cwd, session_id if has_session else None, True)
        actor_ref = derive_actor_ref(cwd, session_id)
        if has_session:
            register_claude_wake(session_id, container_ref, idle=False)
        pending_closes, close_generation = get_pending_relay_close_batch(
            session_id if has_session else None
        )

        if not isinstance(prompt, str) or not prompt or prompt.startswith("/"):
            return
        if session_id and check_dedup(prompt, session_id):
            return
        if pending_closes:
            completed = []
            for previous_container in pending_closes:
                wake_closed = close_claude_wake(session_id, previous_container)
                closed = relay_request(
                    "POST",
                    "/relay/sessions/close",
                    {
                        "runtime": "claude-code",
                        "session_ref": session_id,
                        "container_ref": previous_container,
                    },
                    timeout=0.5,
                )
                if wake_closed and closed is not None:
                    completed.append(previous_container)
            complete_relay_closes(session_id, completed, close_generation)
        content = _strip_ide_context(prompt)
        if not content:
            return

        discovery = discover_work_refs(cwd)
        current_work_ref = injected_work_ref(discovery)
        deliveries = []
        rendered_deliveries = []
        relay_output = ""
        confirmed_refs = []
        work_refs_status = None
        relay_scope = format_injection(
            [], container_ref, budget_chars=RELAY_OUTPUT_BUDGET,
            thread_ref=session_id, actor_ref=actor_ref,
            agent_ref="claude-code", visibility="private", work_ref=current_work_ref,
        ) if has_session else ""
        if relay_scope:
            work_refs_status = "unavailable"
            relay_response = relay_request(
                "POST",
                "/relay/turn",
                {
                    "runtime": "claude-code",
                    "session_ref": session_id,
                    "container_ref": container_ref,
                    "max_chars": RELAY_TURN_BUDGET,
                    "structural_work_refs": structural_work_refs_payload(container_ref, discovery, cwd),
                },
                timeout=0.75,
            )
            relay_response = relay_response or {}
            confirmed_refs = confirmed_registry_work_refs(relay_response)
            candidate_status = relay_response.get("structural_work_refs_status")
            if candidate_status in {"complete", "unavailable"}:
                work_refs_status = candidate_status
            deliveries = relay_response.get("deliveries") or []
            relay_output, rendered_deliveries = format_relay(
                deliveries,
                budget_chars=RELAY_OUTPUT_BUDGET,
                remaining_count=(
                    relay_response.get("remaining_count")
                    if relay_response.get("has_more") is True else 0
                ),
            )
            if rendered_deliveries:
                if not emit_utf8("\n\n".join((relay_output, relay_scope))):
                    return
                acknowledge_relay(rendered_deliveries, container_ref=container_ref)
                sys.exit(0)

        work_refs_metadata = build_work_refs_metadata(
            cwd, payload.get("pallium_work_refs"), discovery,
            confirmed_refs, work_refs_status,
        )
        warning = work_ref_warning(work_refs_metadata)
        separator = 2 if relay_output else 0
        memory_budget = min(
            2400, max(0, 4000 - len(relay_output) - len(warning) - separator)
        )
        memory_output = format_injection(
            [], container_ref, budget_chars=memory_budget,
            thread_ref=session_id, actor_ref=actor_ref,
            agent_ref="claude-code", visibility="private", work_ref=current_work_ref,
        ) if has_session else ""
        if len(content) >= 20:
            query_text = content[:500]
            response = pallium_request("POST", "/item-and-query", {
                "source_type": "claude-code",
                "source_id": f"cc-{uuid.uuid4().hex[:12]}",
                "content_type": "text/plain",
                "content": content,
                "role": "user",
                "agent_ref": "claude-code",
                "container_ref": container_ref,
                "thread_ref": session_id,
                "actor_ref": actor_ref,
                "visibility": "private",
                "artifact_kind": "message",
                "query_text": query_text,
                "query_limit": 5,
                "query_actor_ref": actor_ref,
                "query_trigger_origin": "user_prompt_submit",
                "metadata": work_refs_metadata,
            })
            if response:
                if isinstance(response.get("work_ref_metadata"), dict):
                    warning = work_ref_warning(response["work_ref_metadata"])
                    memory_budget = min(
                        2400,
                        max(
                            0,
                            4000
                            - len(relay_output)
                            - len(warning)
                            - separator,
                        ),
                    )
                memory_output = format_injection(
                    response.get("injectable_blocks", []),
                    container_ref,
                    budget_chars=memory_budget,
                    thread_ref=session_id,
                    actor_ref=actor_ref,
                    agent_ref="claude-code",
                    visibility="private",
                    work_ref=current_work_ref,
                    request_source_item_id=response.get("source_item_id"),
                )

        output = "\n\n".join(part for part in (relay_output, memory_output, warning) if part)
        if output and emit_utf8(output):
            if relay_output:
                acknowledge_relay(
                    rendered_deliveries, container_ref=container_ref
                )
    except Exception as exc:
        print(f"pallium user_prompt_submit hook error: {exc}", file=sys.stderr)

    sys.exit(0)

if __name__ == "__main__":
    main()
