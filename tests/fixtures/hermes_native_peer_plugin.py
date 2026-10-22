"""Harmless enabled peer plugin for native coexistence qualification."""
import json
import hashlib
import os
import socket
import sys
from pathlib import Path


def register(ctx):
    audit = Path(__file__).with_name("audit.jsonl")
    witness = os.environ.get("PALLIUM_TUI_GUARD_WITNESS")
    if witness:
        import psutil

        guard = sys.modules.get("sitecustomize")
        path = Path(guard.__file__).resolve()
        with Path(witness).open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"pid": os.getpid(), "birthtime": psutil.Process().create_time(), "path": str(path),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "socket_guard_active": socket.socket.connect is guard._connect}) + "\n")

    def post_llm_call(session_id="", turn_id="", **_context):
        if isinstance(session_id, str) and session_id and isinstance(turn_id, str) and turn_id:
            with audit.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps({"session_id": session_id, "turn_id": turn_id}) + "\n")

    ctx.register_hook("post_llm_call", post_llm_call)
