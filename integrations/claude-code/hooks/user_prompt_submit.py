"""UserPromptSubmit hook — delivers Relay, ingests the prompt, and injects memory."""

from __future__ import annotations

import re
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (
    acknowledge_relay,
    check_dedup,
    derive_actor_ref,
    format_injection,
    format_relay,
    get_pinned_container,
    pallium_request,
    read_hook_input,
    relay_request,
    resolve_container_ref,
)

_IDE_TAG_RE = re.compile(
    r"<ide_(?:opened_file|selection)>.*?</ide_(?:opened_file|selection)>",
    re.DOTALL,
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
        if session_id and check_dedup(prompt, session_id):
            return
        has_session = isinstance(session_id, str) and bool(session_id)
        previous_container = get_pinned_container(session_id if has_session else None)
        container_ref = resolve_container_ref(cwd, session_id if has_session else None, True)
        actor_ref = derive_actor_ref()
        if has_session and previous_container and previous_container != container_ref:
            relay_request(
                "POST",
                "/relay/sessions/close",
                {
                    "runtime": "claude-code",
                    "session_ref": session_id,
                    "container_ref": previous_container,
                    "actor_ref": actor_ref,
                },
                timeout=0.5,
            )
        content = _strip_ide_context(prompt)
        if not content:
            return

        deliveries = []
        rendered_deliveries = []
        relay_output = ""
        if has_session:
            relay_response = relay_request(
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
            )
            deliveries = (relay_response or {}).get("deliveries") or []
            relay_output, rendered_deliveries = format_relay(deliveries, budget_chars=2400)

        memory_output = ""
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
            })
            if response:
                separator = 2 if relay_output else 0
                memory_budget = min(2400, max(0, 4000 - len(relay_output) - separator))
                memory_output = format_injection(
                    response.get("injectable_blocks", []),
                    container_ref,
                    budget_chars=memory_budget,
                    thread_ref=session_id,
                    actor_ref=actor_ref,
                    agent_ref="claude-code",
                    visibility="private",
                    request_source_item_id=response.get("source_item_id"),
                )

        output = "\n\n".join(part for part in (relay_output, memory_output) if part)
        if output:
            print(output)
            if relay_output:
                acknowledge_relay(
                    rendered_deliveries, container_ref=container_ref, actor_ref=actor_ref
                )
    except Exception as exc:
        print(f"pallium user_prompt_submit hook error: {exc}", file=sys.stderr)

    sys.exit(0)


if __name__ == "__main__":
    main()
