"""Harmless enabled peer plugin for native coexistence qualification."""
import json
import hashlib
import os
import socket
import sys
import time
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
            row = {"session_id": session_id, "turn_id": turn_id}
            try:
                cwd = ctx.session_cwd()
                if isinstance(cwd, str) and cwd:
                    row["native_session_cwd"] = cwd
            except Exception:
                # CWD journeys require the field; fixed-scope hosts may lack this public API.
                pass
            with audit.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(row) + "\n")

    ctx.register_hook("post_llm_call", post_llm_call)

    def on_session_finalize(session_id="", **_context):
        gate = os.environ.get("PALLIUM_TUI_FINALIZE_GATE")
        if not gate or not isinstance(session_id, str) or not session_id:
            return
        gate = Path(gate)
        if not gate.is_dir():
            return
        target = gate / "target"
        if not target.is_file() or target.read_text(encoding="utf-8") != session_id:
            return
        (gate / "entered").write_text(session_id, encoding="utf-8")
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            if (gate / "release").is_file():
                (gate / "completed").write_text(session_id, encoding="utf-8")
                return
            time.sleep(.02)
        (gate / "timed_out").write_text(session_id, encoding="utf-8")
        raise TimeoutError("exact native finalize gate expired without explicit release")

    if os.environ.get("PALLIUM_TUI_FINALIZE_GATE"):
        ctx.register_hook("on_session_finalize", on_session_finalize)
