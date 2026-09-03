"""SessionEnd hook — closes the trusted-local Claude wake capability."""
from __future__ import annotations

from common import close_claude_wake, derive_actor_ref, read_hook_input, resolve_container_ref


def main() -> None:
    try:
        payload = read_hook_input()
        session_id = payload.get("session_id")
        if not isinstance(session_id, str) or not session_id:
            return
        container_ref = resolve_container_ref(payload.get("cwd", "."), session_id)
        close_claude_wake(session_id, container_ref, derive_actor_ref())
    except Exception:
        return


if __name__ == "__main__":
    main()