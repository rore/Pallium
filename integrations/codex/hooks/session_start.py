"""SessionStart hook — issues a /query for recent decisions, progress, and open tasks at session start.

Behavioral note: Codex skips injection on source=clear (preserves prior contract).
Claude Code does inject on clear; this divergence is intentional to avoid
broadcasting on user-initiated clear in Codex.
"""

from __future__ import annotations

import importlib.util
import sys
import time
from pathlib import Path

_common_path = str(Path(__file__).resolve().parent / "common.py")
_spec = importlib.util.spec_from_file_location("codex_common", _common_path)
_common = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
sys.modules["codex_common"] = _common
_spec.loader.exec_module(_common)  # type: ignore[union-attr]

derive_actor_ref = _common.derive_actor_ref
derive_container_ref = _common.derive_container_ref
emit_context = _common.emit_context
format_injection = _common.format_injection
format_relay = _common.format_relay
acknowledge_relay = _common.acknowledge_relay
pallium_request = _common.pallium_request
pin_container = _common.pin_container
read_hook_input = _common.read_hook_input
relay_request = _common.relay_request
relay_turn = _common.relay_turn
start_hook_deadline = _common.start_hook_deadline

RETRIEVAL_FALLBACK_QUERY = "recent decisions, progress, and open tasks"


def _fetch_retrieval_fallback(container_ref: str, actor_ref: str) -> list[dict]:
    response = pallium_request("POST", "/query", {
        "text": RETRIEVAL_FALLBACK_QUERY,
        "container_ref": container_ref,
        "actor_ref": actor_ref,
        "visibility": "private",
        "limit": 5,
        # Phase 4 (2026-06-28): tag the orientation query for audit-log analysis.
        "trigger_origin": "session_start_orientation",
    })
    if not response:
        return []
    return response.get("injectable_blocks", []) or []


def main() -> None:
    try:
        start_hook_deadline(8, host_reserve=1)
        payload = read_hook_input()
        source = payload.get("source", "")
        if source == "clear":
            sys.exit(0)

        cwd = payload.get("cwd", ".")
        session_id = payload.get("session_id")
        container_ref = derive_container_ref(cwd)
        pin_container(session_id, container_ref, source=source)
        actor_ref = derive_actor_ref(cwd, session_id)

        relay_scope = format_injection(
            [], container_ref, budget_chars=_common.RELAY_OUTPUT_BUDGET,
            thread_ref=session_id, actor_ref=actor_ref,
            agent_ref=_common.AGENT_REF, visibility="private",
        )
        request_timeout = max(0.0, _common.remaining_safe_time() - 1.0)
        relay_response = relay_turn(
            "codex", session_id, container_ref,
            max_chars=_common.RELAY_TURN_BUDGET,
            timeout=request_timeout,
            deadline=_common.HookDeadline(time.monotonic() + request_timeout),
            request=relay_request,
        ) if relay_scope and request_timeout > 0 else None
        if isinstance(relay_response, dict):
            relay_output, rendered = format_relay(
                relay_response.get("deliveries") or [],
                budget_chars=_common.RELAY_OUTPUT_BUDGET,
                remaining_count=(
                    relay_response.get("remaining_count")
                    if relay_response.get("has_more") is True else 0
                ),
            )
            if rendered:
                emit_context("\n\n".join((relay_output, relay_scope)), "SessionStart")
                acknowledge_relay(rendered, container_ref=container_ref)
                sys.exit(0)

        blocks = _fetch_retrieval_fallback(container_ref, actor_ref)

        output = format_injection(blocks, container_ref, budget_chars=1200, thread_ref=session_id, actor_ref=actor_ref, agent_ref=_common.AGENT_REF, visibility="private")
        if output:
            emit_context(output, "SessionStart")

    except Exception as exc:
        print(f"pallium session_start hook error: {exc}", file=sys.stderr)

    sys.exit(0)


if __name__ == "__main__":
    main()
