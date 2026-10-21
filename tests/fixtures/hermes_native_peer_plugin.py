"""Harmless enabled peer plugin for native coexistence qualification."""
import json
from pathlib import Path


def register(ctx):
    audit = Path(__file__).with_name("audit.jsonl")

    def post_llm_call(session_id="", turn_id="", **_context):
        if isinstance(session_id, str) and session_id and isinstance(turn_id, str) and turn_id:
            with audit.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps({"session_id": session_id, "turn_id": turn_id}) + "\n")

    ctx.register_hook("post_llm_call", post_llm_call)
