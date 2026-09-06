"""UserPromptSubmit hook — delivers Relay, ingests the prompt, and injects memory."""

from __future__ import annotations

import importlib.util
import json
import re
import sys
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
derive_actor_ref = _common.derive_actor_ref
emit_context = _common.emit_context
format_injection = _common.format_injection
format_relay = _common.format_relay
get_pending_relay_closes = _common.get_pending_relay_closes
pin_container = _common.pin_container
pallium_request = _common.pallium_request
read_hook_input = _common.read_hook_input
relay_request = _common.relay_request
resolve_container_ref = _common.resolve_container_ref
build_work_refs_metadata = _common.build_work_refs_metadata
discover_work_refs = _common.discover_work_refs
injected_work_ref = _common.injected_work_ref

_IDE_TAG_RE = re.compile(
    r"<ide_(?:opened_file|selection)>.*?</ide_(?:opened_file|selection)>",
    re.DOTALL,
)

RELAY_WAKE_PROMPT = (
    "Pallium Relay wake: a persisted delivery may be pending. "
    "The installed UserPromptSubmit hook will claim and inject it for this turn."
)

def _strip_ide_context(text: str) -> str:
    return _IDE_TAG_RE.sub("", text).strip()

def main() -> None:
    try:
        payload = read_hook_input()
        session_id = payload.get("session_id")
        cwd = payload.get("cwd", ".")
        prompt = payload.get("prompt", "")

        if not isinstance(prompt, str) or not prompt or prompt.startswith("/"):
            return
        has_session = isinstance(session_id, str) and bool(session_id)
        container_ref = resolve_container_ref(cwd, session_id if has_session else None, True)
        actor_ref = derive_actor_ref()
        pending_closes = get_pending_relay_closes(session_id if has_session else None)
        if pending_closes:
            remaining = []
            for previous_container in pending_closes:
                closed = relay_request(
                    "POST",
                    "/relay/sessions/close",
                    {
                        "runtime": "codex",
                        "session_ref": session_id,
                        "container_ref": previous_container,
                        "actor_ref": actor_ref,
                    },
                    timeout=0.5,
                )
                if closed is None:
                    remaining.append(previous_container)
            pin_container(session_id, container_ref, pending_relay_closes=remaining)
        content = _strip_ide_context(prompt)
        if not content:
            return
        internal_wake = prompt == RELAY_WAKE_PROMPT

        discovery = discover_work_refs(cwd)
        current_work_ref = injected_work_ref(discovery)
        deliveries = []
        rendered_deliveries = []
        relay_output = ""
        relay_response = None
        relay_scope = format_injection(
            [], container_ref, budget_chars=RELAY_OUTPUT_BUDGET,
            thread_ref=session_id, actor_ref=actor_ref,
            agent_ref=AGENT_REF, visibility="private", work_ref=current_work_ref,
        ) if has_session else ""
        if relay_scope:
            try:
                relay_response = relay_request(
                    "POST", "/relay/turn",
                    {"runtime": "codex", "session_ref": session_id,
                     "container_ref": container_ref, "actor_ref": actor_ref,
                     "max_chars": RELAY_TURN_BUDGET},
                    timeout=0.75,
                )
                if isinstance(relay_response, dict):
                    deliveries = relay_response.get("deliveries") or []
                    relay_output, rendered_deliveries = format_relay(
                        deliveries, budget_chars=RELAY_OUTPUT_BUDGET,
                        remaining_count=(
                            relay_response.get("remaining_count")
                            if relay_response.get("has_more") is True else 0
                        ),
                    )
            except Exception:
                relay_response = None
        if rendered_deliveries:
            emit_context("\n\n".join((relay_output, relay_scope)), "UserPromptSubmit")
            acknowledge_relay(rendered_deliveries, container_ref=container_ref, actor_ref=actor_ref)
            sys.exit(0)

        if internal_wake:
            print(json.dumps({
                "decision": "block",
                "reason": "Pallium Relay wake superseded: no pending delivery.",
            }, separators=(",", ":")))
            sys.exit(0)

        if has_session and check_dedup(prompt, session_id):
            return

        separator = 2 if relay_output else 0
        memory_budget = min(2400, max(0, 4000 - len(relay_output) - separator))
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
                "metadata": build_work_refs_metadata(cwd, payload.get("pallium_work_refs"), discovery),
            })
            if response:
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

        output = "\n\n".join(part for part in (relay_output, memory_output) if part)
        if output:
            emit_context(output, "UserPromptSubmit")
            if relay_output:
                acknowledge_relay(
                    rendered_deliveries, container_ref=container_ref, actor_ref=actor_ref
                )
    except Exception as exc:
        print(f"pallium user_prompt_submit hook error: {exc}", file=sys.stderr)

    sys.exit(0)

if __name__ == "__main__":
    main()
