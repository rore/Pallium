"""Shared utilities for Claude Code hook scripts.

Standalone — stdlib only, no imports from Pallium core.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

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


def derive_container_ref(cwd: str) -> str:
    """Derive container_ref from working directory.

    Priority:
    1. Git remote URL -> "git:<normalized>"
    2. Git repo, no remote -> "repo:<root-commit-hash-prefix>"
    3. Not a git repo -> "path:<sanitized-dirname>:<hash-of-cwd>" (or "path:<hash>" if dirname is empty)
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
    label = _sanitize_path_label(Path(cwd).name)
    if label:
        return f"path:{label}:{h}"
    return f"path:{h}"


def _sanitize_path_label(name: str) -> str:
    """Lowercase, collapse non-[a-z0-9._-] to '_', trim, cap at 32 chars."""
    name = name.strip().lower()
    name = re.sub(r"[^a-z0-9._-]+", "_", name)
    name = name.strip("._-")
    return name[:32]


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
    method: str, path: str, payload: Any | None = None
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
        print(f"pallium hook: {method} {path} failed: {exc}", file=sys.stderr)
        return None


def format_injection(
    injectable_blocks: list[dict], container_ref: str, budget_chars: int
) -> str:
    """Format memory blocks for injection into Claude Code context.

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
            line += " [+expand]"
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

        if "message" in entry and isinstance(entry["message"], dict):
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
            if block_type == "text":
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


# --- Redaction ---

REDACTION_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"Bearer\s+\S+", re.IGNORECASE), "Bearer [REDACTED]"),
    (re.compile(r"(PASSWORD|SECRET|TOKEN|KEY|AUTH)\s*=\s*\S+", re.IGNORECASE), r"\1=[REDACTED]"),
    (re.compile(r"-----BEGIN [A-Z ]+KEY-----.*?-----END[^\n]*", re.IGNORECASE | re.DOTALL), "[REDACTED KEY BLOCK]"),
    (re.compile(r"(mongodb|postgres|mysql|redis)://\S+", re.IGNORECASE), r"\1://[REDACTED]"),
    (re.compile(r"(Authorization|Cookie):\s*.+", re.IGNORECASE), r"\1: [REDACTED]"),
]


def redact_sensitive(text: str) -> str:
    """Apply redaction patterns to strip secrets from text."""
    for pattern, replacement in REDACTION_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


# --- Turn extraction ---


@dataclass
class TurnData:
    assistant_text: str
    tool_calls: list[dict]
    has_productive_action: bool
    files_modified: list[str] = field(default_factory=list)


DISCOVERY_TOOLS = frozenset({"Read", "Bash", "Grep", "Glob"})
PRODUCTIVE_TOOLS = frozenset({"Edit", "Write", "NotebookEdit"})
EXCLUDED_TOOLS = frozenset({"Edit", "Write", "NotebookEdit", "TodoWrite", "Agent", "TaskOutput", "TaskStop"})
BASH_OUTPUT_LIMIT = 600
GREP_MATCH_LIMIT = 20
GLOB_PATH_LIMIT = 50


def _classify_bash_failure(output: str, exit_code: int) -> str:
    if exit_code == 0:
        return "success"
    lower = output.lower()
    if any(m in lower for m in ("pytest", "jest", "mocha")) and any(m in lower for m in ("failed", "failures", "error")):
        return "test_failure"
    if any(m in lower for m in ("compile error", "build failed", "syntax error", "compilation")):
        return "build_error"
    return "command_error"


def _infer_exit_code(tool_output: str) -> int:
    """Best-effort exit code inference from tool_result content."""
    if not tool_output:
        return 0
    m = re.search(r"exit code:\s*(\d+)", tool_output, re.IGNORECASE)
    if m:
        return int(m.group(1))
    lower = tool_output.lower()
    strong_failure_markers = (
        "command failed", "traceback (most recent call last)",
        "fatal:", "panic:", "exited with", "non-zero exit",
    )
    if any(marker in lower for marker in strong_failure_markers):
        return 1
    return 0


def _extract_tool_call(name: str, tool_input: dict, tool_output: str) -> dict | None:
    """Extract a normalized tool call record. Returns None if tool is excluded."""
    if name in EXCLUDED_TOOLS:
        return None

    if name == "Read":
        file_path = tool_input.get("file_path", "")
        return {"tool": "Read", "file_path": redact_sensitive(file_path)}

    if name == "Bash":
        command = redact_sensitive(tool_input.get("command", ""))
        raw_tail = tool_output[-BASH_OUTPUT_LIMIT:] if tool_output else ""
        exit_code = _infer_exit_code(tool_output)
        failure_class = _classify_bash_failure(raw_tail, exit_code)
        output_tail = redact_sensitive(raw_tail)
        return {
            "tool": "Bash",
            "command": command,
            "exit_code": exit_code,
            "output_tail": output_tail,
            "failure_class": failure_class,
        }

    if name == "Grep":
        pattern = redact_sensitive(tool_input.get("pattern", ""))
        path = redact_sensitive(tool_input.get("path", ""))
        matches = [redact_sensitive(m) for m in tool_output.strip().splitlines()[:GREP_MATCH_LIMIT]] if tool_output else []
        return {"tool": "Grep", "pattern": pattern, "path": path, "matches": matches}

    if name == "Glob":
        pattern = redact_sensitive(tool_input.get("pattern", ""))
        paths = [redact_sensitive(p) for p in tool_output.strip().splitlines()[:GLOB_PATH_LIMIT]] if tool_output else []
        return {"tool": "Glob", "pattern": pattern, "paths": paths}

    return None


def read_turn(transcript_path: str) -> TurnData | None:
    """Read the last assistant turn, extracting text and tool calls.

    Single-pass replacement for read_last_assistant_turn(). Returns TurnData
    with assistant response text, filtered/redacted tool calls, and
    has_productive_action flag.
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

        if "message" in entry and isinstance(entry["message"], dict):
            role = entry["message"].get("role")
            content = entry["message"].get("content")
        elif "role" in entry:
            role = entry.get("role")
            content = entry.get("content")

        if role == "assistant" and content is not None:
            last_assistant_content = content

    if last_assistant_content is None:
        return None

    text_parts: list[str] = []
    tool_calls: list[dict] = []
    has_productive = False
    files_modified: list[str] = []

    if isinstance(last_assistant_content, str):
        text_parts.append(last_assistant_content)
    elif isinstance(last_assistant_content, list):
        tool_uses: dict[str, dict] = {}
        for block in last_assistant_content:
            if not isinstance(block, dict):
                continue
            block_type = block.get("type", "")
            if block_type == "text":
                text_parts.append(block.get("text", ""))
            elif block_type == "tool_use":
                tool_name = block.get("name", "")
                tool_id = block.get("id", "")
                tool_input = block.get("input", {})
                tool_uses[tool_id] = {"name": tool_name, "input": tool_input}
                if tool_name in PRODUCTIVE_TOOLS:
                    has_productive = True
                    fp: str | None = None
                    if tool_name in ("Edit", "Write"):
                        fp = tool_input.get("file_path", "")
                    elif tool_name == "NotebookEdit":
                        fp = tool_input.get("notebook_path", "")
                    if fp:
                        fp = redact_sensitive(fp)
                        if fp not in files_modified:
                            files_modified.append(fp)
            elif block_type == "tool_result":
                tool_use_id = block.get("tool_use_id", "")
                tool_output_raw = block.get("content", "") or block.get("text", "")
                if isinstance(tool_output_raw, list):
                    tool_output = "\n".join(
                        b.get("text", "") for b in tool_output_raw
                        if isinstance(b, dict) and b.get("type") == "text"
                    )
                else:
                    tool_output = str(tool_output_raw) if tool_output_raw else ""
                if tool_use_id in tool_uses:
                    use = tool_uses[tool_use_id]
                    extracted = _extract_tool_call(use["name"], use["input"], tool_output)
                    if extracted is not None:
                        tool_calls.append(extracted)

    assistant_text = "\n".join(text_parts)
    if not assistant_text.strip() and not tool_calls:
        return None

    return TurnData(
        assistant_text=assistant_text if assistant_text.strip() else "",
        tool_calls=tool_calls,
        has_productive_action=has_productive,
        files_modified=files_modified,
    )


def build_work_trace_metadata(turn_data: TurnData) -> dict | None:
    """Build agent_work_trace_turn metadata from extracted turn data.

    Returns None if no discovery tool calls are present.
    """
    files_read: list[str] = []
    commands: list[dict] = []
    grep_patterns: list[str] = []

    for call in turn_data.tool_calls:
        tool = call.get("tool")
        if tool == "Read":
            fp = call.get("file_path", "")
            if fp and fp not in files_read:
                files_read.append(fp)
        elif tool == "Bash":
            commands.append({
                "cmd": call["command"],
                "exit_code": call["exit_code"],
                "output_tail": call["output_tail"],
                "failure_class": call["failure_class"],
            })
        elif tool == "Grep":
            pattern = call.get("pattern", "")
            if pattern and pattern not in grep_patterns:
                grep_patterns.append(pattern)

    if not files_read and not commands and not grep_patterns and not turn_data.files_modified:
        return None

    result: dict = {
        "files_read": files_read,
        "commands": commands,
        "grep_patterns": grep_patterns,
        "has_productive_action": turn_data.has_productive_action,
    }
    if turn_data.files_modified:
        result["files_modified"] = turn_data.files_modified
    return result
