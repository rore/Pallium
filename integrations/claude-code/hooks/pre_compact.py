"""PreCompact hook — re-injects key context before compaction."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (
    derive_container_ref,
    format_injection,
    pallium_request,
    read_hook_input,
)


def main() -> None:
    try:
        payload = read_hook_input()
        cwd = payload.get("cwd", ".")
        container_ref = derive_container_ref(cwd)

        response = pallium_request("POST", "/query", {
            "text": "recent decisions, progress, and open tasks",
            "container_ref": container_ref,
            "visibility": "private",
            "limit": 8,
        })

        if not response:
            return

        blocks = response.get("injectable_blocks", [])
        output = format_injection(blocks, container_ref, budget_chars=2400)
        if output:
            print(output)

    except Exception as exc:
        print(f"pallium pre_compact hook error: {exc}", file=sys.stderr)

    sys.exit(0)


if __name__ == "__main__":
    main()
