"""UserPromptSubmit hook — ingests user message and injects relevant memories."""

from __future__ import annotations

import importlib.util
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
SOURCE_TYPE = _common.SOURCE_TYPE
check_dedup = _common.check_dedup
derive_actor_ref = _common.derive_actor_ref
derive_container_ref = _common.derive_container_ref
emit_context = _common.emit_context
format_injection = _common.format_injection
pallium_request = _common.pallium_request
read_hook_input = _common.read_hook_input
resolve_container_ref = _common.resolve_container_ref

_IDE_TAG_RE = re.compile(
    r"<ide_(?:opened_file|selection)>.*?</ide_(?:opened_file|selection)>",
    re.DOTALL,
)


def _strip_ide_context(text: str) -> str:
    """Remove IDE context tags injected by the extension before ingestion."""
    return _IDE_TAG_RE.sub("", text).strip()


def main() -> None:
    try:
        payload = read_hook_input()
        session_id = payload.get("session_id", "unknown")
        cwd = payload.get("cwd", ".")
        prompt = payload.get("prompt", "")

        if len(prompt) < 20:
            sys.exit(0)
        if prompt.startswith("/"):
            sys.exit(0)
        if check_dedup(prompt, session_id):
            sys.exit(0)

        container_ref = resolve_container_ref(cwd, session_id)
        actor_ref = derive_actor_ref()

        content = _strip_ide_context(prompt)
        if not content:
            sys.exit(0)

        query_text = content[:500] if len(content) > 500 else content

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
            "query_text": query_text,
            "query_limit": 5,
            "query_actor_ref": actor_ref,
            # Phase 4 (2026-06-28): tag the proactive prompt-submit query.
            "query_trigger_origin": "user_prompt_submit",
        })

        if not response:
            sys.exit(0)

        blocks = response.get("injectable_blocks", [])
        output = format_injection(blocks, container_ref, budget_chars=2400)
        if output:
            emit_context(output, "UserPromptSubmit")

    except Exception as exc:
        print(f"pallium user_prompt_submit hook error: {exc}", file=sys.stderr)

    sys.exit(0)


if __name__ == "__main__":
    main()
