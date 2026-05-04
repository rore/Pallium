"""Shared utilities for Codex hook scripts.

Standalone — stdlib only, no imports from Pallium core.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

AGENT_REF = "codex"
SOURCE_TYPE = "codex"
PALLIUM_PORT = int(os.environ.get("PALLIUM_PORT", "19836"))
PALLIUM_BASE_URL = f"http://localhost:{PALLIUM_PORT}"
HTTP_TIMEOUT = 6
SUBPROCESS_TIMEOUT = 3
STATE_DIR = Path.home() / ".pallium" / "hooks" / "state"
DEDUP_EXPIRY_SECONDS = 300


def read_hook_input() -> dict:
    """Read JSON payload from stdin. Returns empty dict on any failure."""
    try:
        data = sys.stdin.read()
        if not data.strip():
            return {}
        return json.loads(data)
    except Exception:
        return {}


def emit_context(text: str, event_name: str) -> None:
    """Write hookSpecificOutput JSON to stdout for Codex context injection."""
    output = {
        "hookSpecificOutput": {
            "hookEventName": event_name,
            "additionalContext": text,
        }
    }
    print(json.dumps(output))


def derive_container_ref(cwd: str) -> str:
    """Derive container_ref from working directory.

    Priority:
    1. Git remote URL -> "git:<normalized>"
    2. Git repo, no remote -> "repo:<root-commit-hash-prefix>"
    3. Not a git repo -> "path:<hash-of-cwd>"
    """
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True, text=True, cwd=cwd, timeout=SUBPROCESS_TIMEOUT,
        )
        if result.returncode == 0 and result.stdout.strip():
            return "git:" + _normalize_remote_url(result.stdout.strip())
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return _path_container(cwd)

    try:
        result = subprocess.run(
            ["git", "rev-list", "--max-parents=0", "HEAD"],
            capture_output=True, text=True, cwd=cwd, timeout=SUBPROCESS_TIMEOUT,
        )
        if result.returncode == 0 and result.stdout.strip():
            root_hash = result.stdout.strip().splitlines()[0][:12]
            return f"repo:{root_hash}"
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass

    return _path_container(cwd)


def _normalize_remote_url(url: str) -> str:
    """Normalize a git remote URL to a canonical form.

    git@github.com:user/repo.git -> github.com/user/repo
    https://github.com/user/repo.git -> github.com/user/repo
    """
    url = url.strip().lower()
    if url.startswith("git@"):
        url = url[4:]
        url = url.replace(":", "/", 1)
    elif "://" in url:
        url = url.split("://", 1)[1]
    if url.endswith(".git"):
        url = url[:-4]
    url = url.rstrip("/")
    if "@" in url.split("/")[0]:
        url = url.split("@", 1)[1]
    return url


def _path_container(cwd: str) -> str:
    h = hashlib.sha256(cwd.encode()).hexdigest()[:12]
    return f"path:{h}"


def derive_actor_ref() -> str:
    """Get actor_ref from git config user.name, fallback to 'local'."""
    try:
        result = subprocess.run(
            ["git", "config", "user.name"],
            capture_output=True, text=True, timeout=SUBPROCESS_TIMEOUT,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass
    return "local"


def pallium_request(
    method: str, path: str, payload: Any | None = None, *, quiet: bool = False
) -> dict | None:
    """Make HTTP request to Pallium. Returns parsed JSON or None on failure."""
    url = f"{PALLIUM_BASE_URL}{path}"
    body = None
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")

    req = urllib.request.Request(
        url, data=body, method=method,
        headers={"Content-Type": "application/json"} if body else {},
    )
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        if not quiet:
            print(f"pallium hook: {method} {path} failed: {exc}", file=sys.stderr)
        return None


def format_injection(
    injectable_blocks: list[dict], container_ref: str, budget_chars: int
) -> str:
    """Format memory blocks for injection into Codex context.

    Returns empty string if no blocks or result is whitespace-only.
    """
    if not injectable_blocks:
        return ""

    header = f"[Pallium memory — container: {container_ref}]\n\n"
    footer = (
        "\n\n[If any memory above seems incorrect or outdated, use the pallium_flag_memory\n"
        "tool with the ref ID and a brief reason. Use pallium_expand if you need\n"
        "more context on how a memory was derived.]\n\n"
        "[End Pallium memory]"
    )

    overhead = len(header) + len(footer)
    available = budget_chars - overhead

    formatted_blocks: list[str] = []
    for block in injectable_blocks:
        title = block.get("title", "")
        memory_object_id = block.get("memory_object_id", "")
        text = block.get("text", "")
        line = f"[{title} | ref:{memory_object_id}] {text}"
        if block.get("expand_available"):
            line += " [+source]"
        formatted_blocks.append(line)

    total_len = sum(len(b) for b in formatted_blocks) + len(formatted_blocks) - 1
    while formatted_blocks and total_len > available:
        formatted_blocks.pop()
        total_len = sum(len(b) for b in formatted_blocks) + max(0, len(formatted_blocks) - 1)

    if not formatted_blocks:
        return ""

    body = "\n\n".join(formatted_blocks)
    output = header + body + footer

    if not output.strip():
        return ""

    return output


def read_last_assistant_turn(transcript_path: str) -> str | None:
    """Read the last assistant turn from a JSONL transcript file.

    Handles:
    - Wrapped format: {"message": {"role": "assistant", "content": ...}}
    - Flat format: {"role": "assistant", "content": ...}
    - Content as string or array of blocks
    - tool_result blocks truncated to 500 chars
    - Files >10MB: reads only last 2MB
    """
    try:
        file_size = os.path.getsize(transcript_path)
    except OSError:
        return None

    if file_size == 0:
        return None

    try:
        if file_size > 10 * 1024 * 1024:
            with open(transcript_path, "rb") as f:
                f.seek(-2 * 1024 * 1024, 2)
                raw = f.read().decode("utf-8", errors="replace")
            lines = raw.splitlines()
            if lines:
                lines = lines[1:]
        else:
            with open(transcript_path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.read().splitlines()
    except OSError:
        return None

    last_assistant_content = None
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue

        role = None
        content = None

        if entry.get("type") == "response_item" and isinstance(entry.get("payload"), dict):
            payload = entry["payload"]
            if payload.get("type") == "message":
                role = payload.get("role")
                content = payload.get("content")
        elif "message" in entry and isinstance(entry["message"], dict):
            role = entry["message"].get("role")
            content = entry["message"].get("content")
        elif "role" in entry:
            role = entry.get("role")
            content = entry.get("content")

        if role == "assistant" and content is not None:
            last_assistant_content = content

    if last_assistant_content is None:
        return None

    return _extract_text_from_content(last_assistant_content)


def _extract_text_from_content(content: Any) -> str | None:
    """Extract text from content (string or array of blocks)."""
    if isinstance(content, str):
        return content if content.strip() else None

    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if not isinstance(block, dict):
                continue
            block_type = block.get("type", "")
            if block_type in {"text", "output_text", "input_text"}:
                parts.append(block.get("text", ""))
            elif block_type == "tool_result":
                text = block.get("text", "") or block.get("content", "")
                if isinstance(text, str) and len(text) > 500:
                    text = text[:500] + "..."
                if text:
                    parts.append(f"[tool_result: {text}]")
            elif block_type == "tool_use":
                pass
        result = "\n".join(parts)
        return result if result.strip() else None

    return None


def check_dedup(prompt: str, session_id: str) -> bool:
    """Check if this prompt was already seen in this session within 5 minutes.

    Returns True if duplicate (should skip).
    """
    prompt_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16]
    now = time.time()

    state_file = STATE_DIR / f"{session_id}.json"

    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
    except OSError:
        return False

    state: dict[str, float] = {}
    try:
        if state_file.exists():
            raw = state_file.read_text(encoding="utf-8")
            state = json.loads(raw)
            if not isinstance(state, dict):
                state = {}
    except (json.JSONDecodeError, OSError):
        state = {}

    state = {k: v for k, v in state.items() if now - v < DEDUP_EXPIRY_SECONDS}

    if prompt_hash in state:
        return True

    state[prompt_hash] = now
    try:
        state_file.write_text(json.dumps(state), encoding="utf-8")
    except OSError:
        pass

    return False
