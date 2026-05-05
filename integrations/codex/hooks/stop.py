"""Stop hook — ingests the assistant's last response from the transcript."""

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

CONTENT_LENGTH_GATE = 20_000


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

        container_ref = derive_container_ref(cwd)
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

    except Exception as exc:
        print(f"pallium stop hook error: {exc}", file=sys.stderr)

    sys.exit(0)


if __name__ == "__main__":
    main()
