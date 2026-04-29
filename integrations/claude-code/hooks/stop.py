"""Stop hook — ingests the assistant's last response from the transcript."""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (
    derive_actor_ref,
    derive_container_ref,
    pallium_request,
    read_hook_input,
    read_last_assistant_turn,
)

CONTENT_LENGTH_GATE = 20_000


def main() -> None:
    try:
        payload = read_hook_input()
        session_id = payload.get("session_id", "unknown")
        cwd = payload.get("cwd", ".")
        transcript_path = payload.get("transcript_path", "")

        if not transcript_path:
            return

        content = read_last_assistant_turn(transcript_path)
        if not content:
            return
        if len(content) > CONTENT_LENGTH_GATE:
            return

        container_ref = derive_container_ref(cwd)
        actor_ref = derive_actor_ref()

        pallium_request("POST", "/items", [{
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
        }])

    except Exception as exc:
        print(f"pallium stop hook error: {exc}", file=sys.stderr)

    sys.exit(0)


if __name__ == "__main__":
    main()
