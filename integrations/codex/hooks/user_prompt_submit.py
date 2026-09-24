"""UserPromptSubmit hook — delivers Relay, ingests the prompt, and injects memory."""

from __future__ import annotations

import importlib.util
import json
import re
import sys
import time
import uuid
from pathlib import Path

_common_path = str(Path(__file__).resolve().parent / "common.py")
_spec = importlib.util.spec_from_file_location("codex_common", _common_path)
_common = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
sys.modules["codex_common"] = _common
_spec.loader.exec_module(_common)  # type: ignore[union-attr]

AGENT_REF = _common.AGENT_REF
RELAY_OUTPUT_BUDGET = _common.RELAY_OUTPUT_BUDGET
RELAY_TURN_BUDGET = _common.RELAY_TURN_BUDGET
SOURCE_TYPE = _common.SOURCE_TYPE
acknowledge_relay = _common.acknowledge_relay
check_dedup = _common.check_dedup
complete_relay_closes = _common.complete_relay_closes

derive_actor_ref = _common.derive_actor_ref
emit_context = _common.emit_context
emit_utf8 = _common.emit_utf8
format_injection = _common.format_injection
format_relay = _common.format_relay
get_pending_relay_close_batch = _common.get_pending_relay_close_batch

pallium_request = _common.pallium_request
read_hook_input = _common.read_hook_input
relay_request = _common.relay_request

relay_turn = _common.relay_turn
resolve_container_ref = _common.resolve_container_ref
build_work_refs_metadata = _common.build_work_refs_metadata
structural_work_refs_payload = _common.structural_work_refs_payload
confirmed_registry_work_refs = _common.confirmed_registry_work_refs
discover_work_refs = _common.discover_work_refs
injected_work_ref = _common.injected_work_ref
work_ref_warning = _common.work_ref_warning
start_hook_deadline = _common.start_hook_deadline
record_codex_hook_execution = _common.record_codex_hook_execution
record_codex_wake_event = _common.record_codex_wake_event

_IDE_TAG_RE = re.compile(
    r"<ide_(?:opened_file|selection)>.*?</ide_(?:opened_file|selection)>",
    re.DOTALL,
)

RELAY_WAKE_PROMPT = (
    "Pallium Relay wake: a persisted delivery may be pending. "
    "The installed UserPromptSubmit hook will claim and inject it for this turn."
)
_RELAY_WAKE_RE = re.compile(
    r"^Pallium Relay wake for (?P<delivery_id>relay-delivery-[0-9a-f]{32})\. "
    r"If no \[Pallium Relay message \.\.\.\] block accompanies this turn, "
    r"do not conclude the inbox is empty and do not call pallium_relay_receive "
    r"or resend\. Inspect this exact delivery with pallium_relay_trace by "
    r"passing it as message_id\.$"
)

def _strip_ide_context(text: str) -> str:
    return _IDE_TAG_RE.sub("", text).strip()

def main() -> None:
    wake_delivery_id = None
    wake_failure_recorded = False
    try:
        start_hook_deadline(8, host_reserve=1)
        record_codex_hook_execution(script=__file__)
        payload = read_hook_input()
        session_id = payload.get("session_id")
        cwd = payload.get("cwd", ".")
        prompt = payload.get("prompt", "")

        if not isinstance(prompt, str) or not prompt or prompt.startswith("/"):
            return
        has_session = isinstance(session_id, str) and bool(session_id)
        container_ref = resolve_container_ref(cwd, session_id if has_session else None, True, False)
        actor_ref = derive_actor_ref(cwd, session_id)
        content = _strip_ide_context(prompt)
        if not content:
            return
        wake_match = _RELAY_WAKE_RE.fullmatch(prompt)
        wake_delivery_id = (
            wake_match.group("delivery_id") if wake_match is not None else None
        )
        internal_wake = prompt == RELAY_WAKE_PROMPT or wake_match is not None
        if wake_delivery_id is not None:
            record_codex_wake_event(
                script=__file__,
                delivery_id=wake_delivery_id,
                stage="hook_started",
            )

        discovery = discover_work_refs(cwd)
        current_work_ref = injected_work_ref(discovery)
        deliveries = []
        rendered_deliveries = []
        relay_output = ""
        relay_response = None
        confirmed_refs = []
        work_refs_status = None
        relay_outcome = "invalid_scope"
        relay_scope = format_injection(
            [], container_ref, budget_chars=RELAY_OUTPUT_BUDGET,
            thread_ref=session_id, actor_ref=actor_ref,
            agent_ref=AGENT_REF, visibility="private", work_ref=current_work_ref,
        ) if has_session else ""
        if relay_scope:
            work_refs_status = "unavailable"
            relay_outcome = "unavailable"

            def measured_relay_request(method, path, body, *, timeout):
                started = time.monotonic()
                response = None
                try:
                    request_timeout = (
                        min(2.0, max(0.0, _common.remaining_safe_time() - 1.0))
                        if wake_delivery_id is not None
                        and body.get("wake_delivery_id") == wake_delivery_id
                        else timeout
                    )
                    response = relay_request(method, path, body, timeout=request_timeout)
                    return response
                finally:
                    if (
                        wake_delivery_id is not None
                        and body.get("wake_delivery_id") == wake_delivery_id
                    ):
                        record_codex_wake_event(
                            script=__file__,
                            delivery_id=wake_delivery_id,
                            stage="relay_request_completed",
                            outcome=(
                                "response" if isinstance(response, dict)
                                else "unavailable"
                            ),
                            elapsed_ms=int((time.monotonic() - started) * 1000),
                        )

            try:
                relay_response = relay_turn(
                    "codex", session_id, container_ref,
                    max_chars=RELAY_TURN_BUDGET,
                    structural_work_refs=structural_work_refs_payload(
                        container_ref, discovery, cwd
                    ),
                    wake_delivery_id=(
                        wake_match.group("delivery_id")
                        if wake_match is not None else None
                    ),
                    timeout=0.75,
                    request=measured_relay_request if wake_delivery_id else relay_request,
                )
                if isinstance(relay_response, dict):
                    confirmed_refs = confirmed_registry_work_refs(relay_response)
                    candidate_status = relay_response.get(
                        "structural_work_refs_status"
                    )
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
                    relay_outcome = "delivered" if rendered_deliveries else (
                        "empty" if (
                            relay_response.get("deliveries", object()) == []
                            and relay_response.get("has_more") is False
                            and type(relay_response.get("remaining_count")) is int
                            and relay_response["remaining_count"] == 0
                        ) else "malformed"
                    )
                elif relay_response is not None:
                    relay_outcome = "malformed"
            except Exception:
                relay_response = None
                confirmed_refs = []
                work_refs_status = "unavailable"
                relay_outcome = "unavailable"
        if rendered_deliveries:
            exact_rendered = (
                wake_delivery_id is None
                or any(
                    delivery.get("delivery_id") == wake_delivery_id
                    for delivery in rendered_deliveries
                    if isinstance(delivery, dict)
                )
            )
            try:
                emit_context(
                    "\n\n".join((relay_output, relay_scope)),
                    "UserPromptSubmit",
                )
            except Exception:
                if wake_delivery_id is not None:
                    record_codex_wake_event(
                        script=__file__,
                        delivery_id=wake_delivery_id,
                        stage="hook_failed",
                        reason="emit_failed",
                    )
                    wake_failure_recorded = True
                raise
            if wake_delivery_id is not None and exact_rendered:
                record_codex_wake_event(
                    script=__file__,
                    delivery_id=wake_delivery_id,
                    stage="payload_emitted",
                )
            try:
                acknowledged = acknowledge_relay(
                    rendered_deliveries,
                    container_ref=container_ref,
                )
            except Exception:
                acknowledged = []
            if wake_delivery_id is not None:
                exact_acknowledged = exact_rendered and isinstance(
                    acknowledged, list
                ) and any(
                    delivery.get("delivery_id") == wake_delivery_id
                    for delivery in acknowledged
                    if isinstance(delivery, dict)
                )
                record_codex_wake_event(
                    script=__file__,
                    delivery_id=wake_delivery_id,
                    stage=(
                        "delivery_acked"
                        if exact_acknowledged
                        else "hook_failed"
                    ),
                    reason=(
                        None
                        if exact_acknowledged
                        else (
                            "ack_failed"
                            if exact_rendered
                            else "malformed_response"
                        )
                    ),
                )
                wake_failure_recorded = not exact_acknowledged
            sys.exit(0)

        if internal_wake:
            if wake_delivery_id is not None:
                record_codex_wake_event(
                    script=__file__,
                    delivery_id=wake_delivery_id,
                    stage="hook_failed",
                    reason={
                        "invalid_scope": "invalid_scope",
                        "unavailable": "relay_unavailable",
                        "malformed": "malformed_response",
                        "empty": "empty",
                    }[relay_outcome],
                )
                wake_failure_recorded = True
            if relay_outcome != "empty":
                print(f"pallium relay wake: outcome={relay_outcome}", file=sys.stderr)
            emit_utf8(json.dumps({
                "decision": "block",
                "reason": "Pallium Relay wake suppressed: no verified pending delivery.",
            }, separators=(",", ":")))
            sys.exit(0)

        if has_session and check_dedup(prompt, session_id):
            return

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
            agent_ref=AGENT_REF, visibility="private", work_ref=current_work_ref,
        ) if has_session else ""
        if len(content) >= 20:
            response = pallium_request("POST", "/item-and-query", {
                "source_type": SOURCE_TYPE,
                "source_id": f"cdx-{uuid.uuid4().hex[:12]}",
                "content_type": "text/plain",
                "content": content,
                "role": "user",
                "agent_ref": AGENT_REF,
                "container_ref": container_ref,
                "thread_ref": session_id,
                "actor_ref": actor_ref,
                "visibility": "private",
                "artifact_kind": "message",
                "query_text": content[:500],
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
                    agent_ref=AGENT_REF,
                    visibility="private",
                    work_ref=current_work_ref,
                    request_source_item_id=response.get("source_item_id"),
                )

        output = "\n\n".join(part for part in (relay_output, memory_output, warning) if part)
        if output:
            emit_context(output, "UserPromptSubmit")
            if relay_output:
                acknowledge_relay(
                    rendered_deliveries, container_ref=container_ref
                )
    except Exception as exc:
        if wake_delivery_id is not None and not wake_failure_recorded:
            record_codex_wake_event(
                script=__file__,
                delivery_id=wake_delivery_id,
                stage="hook_failed",
                reason="unexpected_error",
            )
        print(f"pallium user_prompt_submit hook error: {exc}", file=sys.stderr)

    sys.exit(0)

if __name__ == "__main__":
    main()
