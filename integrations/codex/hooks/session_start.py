"""SessionStart hook — injects orientation memory at session beginning."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (
    derive_container_ref,
    emit_context,
    format_injection,
    pallium_request,
    read_hook_input,
)


def main() -> None:
    try:
        payload = read_hook_input()

        # Skip injection on fresh start (clear)
        source = payload.get("source", "")
        if source == "clear":
            sys.exit(0)

        cwd = payload.get("cwd", ".")
        container_ref = derive_container_ref(cwd)

        response = pallium_request("POST", "/query", {
            "text": "recent decisions, progress, and open tasks",
            "container_ref": container_ref,
            "visibility": "private",
            "limit": 5,
        })

        if not response:
            sys.exit(0)

        blocks = response.get("injectable_blocks", [])
        output = format_injection(blocks, container_ref, budget_chars=1200)
        if output:
            emit_context(output, "SessionStart")

    except Exception as exc:
        print(f"pallium session_start hook error: {exc}", file=sys.stderr)

    sys.exit(0)


if __name__ == "__main__":
    main()
