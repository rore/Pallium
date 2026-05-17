"""SessionStart hook — injects orientation memory at session beginning."""

from __future__ import annotations

import importlib.util
import sys
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
pallium_request = _common.pallium_request
pin_container = _common.pin_container
read_hook_input = _common.read_hook_input


def main() -> None:
    try:
        payload = read_hook_input()
        source = payload.get("source", "")
        if source == "clear":
            sys.exit(0)

        cwd = payload.get("cwd", ".")
        session_id = payload.get("session_id")
        container_ref = derive_container_ref(cwd)
        pin_container(session_id, container_ref, source=source)
        actor_ref = derive_actor_ref()

        response = pallium_request("POST", "/query", {
            "text": "recent decisions, progress, and open tasks",
            "container_ref": container_ref,
            "actor_ref": actor_ref,
            "visibility": "private",
            "limit": 5,
        })

        blocks: list[dict] = []
        if response:
            blocks = response.get("injectable_blocks", [])

        # Scoped task_trace injection on session resume
        if source == "resume" and session_id:
            trace_response = pallium_request("POST", "/query", {
                "text": f"task_trace for thread {session_id}",
                "container_ref": container_ref,
                "actor_ref": actor_ref,
                "visibility": "private",
                "thread_ref": session_id,
                "limit": 1,
            }, quiet=True)
            if trace_response:
                trace_blocks = trace_response.get("injectable_blocks", [])
                for tb in trace_blocks:
                    if "task_trace" in tb.get("title", "").lower() or "task_trace" in tb.get("text", "").lower():
                        blocks.append(tb)
                        break

        output = format_injection(blocks, container_ref, budget_chars=1200)
        if output:
            emit_context(output, "SessionStart")

    except Exception as exc:
        print(f"pallium session_start hook error: {exc}", file=sys.stderr)

    sys.exit(0)


if __name__ == "__main__":
    main()
