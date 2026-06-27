"""PostToolUse hook — deterministic on-demand triggers (Phase 4).

See: docs/specs/2026-06-27-injection-policy-abstention.md.

Fires after the agent finishes a tool call. Two triggers:

1. `post_tool_failure`: a failed Bash/test/build command produces an
   error signature; we issue a targeted query for
   `investigation_outcome` memories matching that signature.

2. `retry_threshold`: per (session, tool, normalized_target) we count
   how many times the agent has retried the same operation. At >=3 we
   issue a second targeted query — the assumption is the agent is
   stuck and would benefit from prior investigations of the same
   error class.

Both queries pass an opaque `trigger_origin` so Pallium's audit log can
distinguish trigger-driven calls from proactive ones (Phase 6
measurement).

Triggers are STRUCTURAL only (per the 2026-05-30 decision): no NL
phrase cues. Matching is by tool name, exit-code/failure-class, and
normalized target path.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (
    STATE_DIR,
    _classify_bash_failure,
    _infer_exit_code,
    derive_actor_ref,
    format_injection,
    pallium_request,
    read_hook_input,
    redact_sensitive,
    resolve_container_ref,
)


RETRY_THRESHOLD = 3
RETRY_COUNTERS_DIR = STATE_DIR / "retry_counters"


def _load_retry_counters(session_id: str) -> dict:
    if not session_id:
        return {}
    path = RETRY_COUNTERS_DIR / f"{session_id}.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_retry_counters(session_id: str, counters: dict) -> None:
    if not session_id:
        return
    try:
        RETRY_COUNTERS_DIR.mkdir(parents=True, exist_ok=True)
        path = RETRY_COUNTERS_DIR / f"{session_id}.json"
        path.write_text(json.dumps(counters), encoding="utf-8")
    except Exception:
        pass  # best-effort; retry-trigger is a nice-to-have


def _normalize_target(tool_name: str, tool_input: dict) -> str:
    """Identity key for a tool invocation; used to detect retries.

    Structural only — no NL parsing. Concrete fields per tool:
      - Bash: first 80 chars of the `command` string (post-redaction).
      - Read/Write/Edit/Glob/Grep: `file_path` or `path`.
      - Anything else: empty (will not de-dup).
    """
    if not isinstance(tool_input, dict):
        return ""
    if tool_name == "Bash":
        cmd = tool_input.get("command") or ""
        return redact_sensitive(str(cmd))[:80].strip()
    for key in ("file_path", "path", "pattern"):
        val = tool_input.get(key)
        if val:
            return str(val)[:200]
    return ""


def _error_signature(tool_name: str, output: str, exit_code: int) -> str:
    """Compact, redacted error signature for an investigation_outcome query."""
    failure_class = _classify_bash_failure(output, exit_code) if tool_name == "Bash" else "tool_error"
    tail = redact_sensitive(output)[-400:].strip() if output else ""
    # Keep query text short — Pallium's matching is structural, not
    # full-text. We want the failure_class + a representative chunk.
    if tail:
        return f"{failure_class}: {tail}"
    return failure_class


def _maybe_fire_failure_query(
    *,
    container_ref: str,
    actor_ref: str,
    session_id: str,
    error_signature: str,
) -> list[dict]:
    response = pallium_request("POST", "/query", {
        "text": error_signature,
        "container_ref": container_ref,
        "actor_ref": actor_ref,
        "visibility": "private",
        "limit": 3,
        "trigger_origin": "post_tool_failure",
    })
    if not response:
        return []
    return response.get("injectable_blocks", []) or []


def _maybe_fire_retry_query(
    *,
    container_ref: str,
    actor_ref: str,
    normalized_target: str,
    tool_name: str,
) -> list[dict]:
    text = f"{tool_name} {normalized_target}".strip()
    response = pallium_request("POST", "/query", {
        "text": text or "retried operation",
        "container_ref": container_ref,
        "actor_ref": actor_ref,
        "visibility": "private",
        "limit": 3,
        "trigger_origin": "retry_threshold",
    })
    if not response:
        return []
    return response.get("injectable_blocks", []) or []


def main() -> None:
    try:
        payload = read_hook_input()
        cwd = payload.get("cwd", ".")
        session_id = payload.get("session_id") or ""
        container_ref = resolve_container_ref(cwd, session_id)
        actor_ref = derive_actor_ref()

        tool_name = (payload.get("tool_name") or "").strip()
        tool_input = payload.get("tool_input") or {}
        tool_response = payload.get("tool_response") or {}
        # Claude Code emits tool_response as either dict or string; we
        # only need the text representation for failure inference.
        if isinstance(tool_response, dict):
            output = tool_response.get("output") or tool_response.get("error") or ""
        else:
            output = str(tool_response)

        normalized_target = _normalize_target(tool_name, tool_input)
        exit_code = _infer_exit_code(output)
        failed = exit_code != 0

        blocks: list[dict] = []

        # Trigger 1: failure → investigation_outcome lookup.
        if failed:
            sig = _error_signature(tool_name, output, exit_code)
            blocks.extend(_maybe_fire_failure_query(
                container_ref=container_ref,
                actor_ref=actor_ref,
                session_id=session_id,
                error_signature=sig,
            ))

        # Trigger 2: retry-threshold counter.
        counters = _load_retry_counters(session_id)
        key = f"{tool_name}::{normalized_target}"
        if normalized_target:
            count = counters.get(key, 0)
            # Only increment on failure — successful retries are not "stuck".
            if failed:
                count += 1
                counters[key] = count
            else:
                # Reset counter on success — agent unblocked.
                if key in counters:
                    counters.pop(key)
            _save_retry_counters(session_id, counters)

            if failed and count >= RETRY_THRESHOLD:
                blocks.extend(_maybe_fire_retry_query(
                    container_ref=container_ref,
                    actor_ref=actor_ref,
                    normalized_target=normalized_target,
                    tool_name=tool_name,
                ))

        output_text = format_injection(blocks, container_ref, budget_chars=1200)
        if output_text:
            print(output_text)

    except Exception as exc:
        print(f"pallium post_tool_use hook error: {exc}", file=sys.stderr)

    sys.exit(0)


if __name__ == "__main__":
    main()
