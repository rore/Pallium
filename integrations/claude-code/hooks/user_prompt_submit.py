"""UserPromptSubmit hook — ingests user message and injects relevant memories."""

from __future__ import annotations

import re
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (
    check_dedup,
    derive_actor_ref,
    derive_container_ref,
    format_injection,
    pallium_request,
    read_hook_input,
)

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
            return
        if prompt.startswith("/"):
            return
        if check_dedup(prompt, session_id):
            return

        container_ref = derive_container_ref(cwd)
        actor_ref = derive_actor_ref()

        content = _strip_ide_context(prompt)
        if not content:
            return

        query_text = content[:500] if len(content) > 500 else content

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
        })

        if not response:
            return

        blocks = response.get("injectable_blocks", [])
        output = format_injection(blocks, container_ref, budget_chars=2400)
        if output:
            print(output)

    except Exception as exc:
        print(f"pallium user_prompt_submit hook error: {exc}", file=sys.stderr)

    sys.exit(0)


if __name__ == "__main__":
    main()
