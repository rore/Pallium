"""Parse Claude Code and Codex session JSONL transcripts into a normalized
event stream and turn-grouped view.

Format detection is automatic: the first non-empty line is decoded and
inspected for the Codex envelope shape ``{timestamp, type, payload}``;
otherwise the file is treated as Claude Code.

Normalized event shape:

    {
      "ts":              ISO timestamp (best effort, may be None),
      "kind":            "user_msg" | "assistant_msg" | "tool_call"
                       | "tool_result" | "system_inject" | "session_meta"
                       | "compacted" | "tool_result_carrier" | "other",
      "role":            "user" | "assistant" | "tool" | "developer" | None,
      "tool_name":       str | None,
      "tool_id":         str | None,    # tool_use_id / call_id
      "tool_input":      Any,           # for tool_call only
      "tool_output":     str | None,    # for tool_result only
      "text":            str | None,    # for messages / system_inject
      "raw_index":       int,           # source line index
      "source_format":   "claude" | "codex",
      "session_id":      str | None,
      "cwd":             str | None,
      "pallium_blocks":  list[dict] | None,  # parsed [Pallium memory] blocks
    }

Turn grouping starts at every ``user_msg`` (real prompts; pure tool_result
carriers are dropped). ``system_inject`` events that appear adjacent to a
turn are recorded as ``pre_inject`` (before) or ``post_inject`` (after) on
the surrounding turn so a caller can ask: "was Pallium injected for THIS
turn?".
"""
from __future__ import annotations

import json
import re
from typing import Any, Iterator


_PAL_BLOCK_RE = re.compile(
    r"\[Pallium memory[^\]]*\]\s*(.+?)\s*\[End Pallium memory\]",
    re.DOTALL,
)
_PAL_REF_RE = re.compile(
    r"\[(?P<title>[^|\]]+)\s*\|\s*ref:(?P<ref>[A-Za-z0-9_:.-]+)\]\s*"
    r"(?P<text>.+?)(?=\n\n\[|\Z)",
    re.DOTALL,
)


def _extract_pallium_blocks(s: str) -> list[dict] | None:
    """Extract ``[Title | ref:<id>] body`` blocks from a Pallium injection.

    Returns None when the input does not look like a Pallium injection at
    all. Returns an empty list only if the markers are present but no
    ref-shaped lines could be parsed (defensive — observed shape is stable).
    """
    if "Pallium memory" not in s:
        return None
    m = _PAL_BLOCK_RE.search(s)
    if not m:
        return None
    body = m.group(1)
    blocks: list[dict] = []
    for bm in _PAL_REF_RE.finditer(body):
        blocks.append({
            "title": bm.group("title").strip(),
            "ref": bm.group("ref").strip(),
            "text": bm.group("text").strip(),
        })
    if not blocks:
        # Fallback: scan for any ref:<id> tokens. Loses titles/text but
        # preserves the count of injected memories.
        for ref in re.findall(r"ref:([A-Za-z0-9_:.-]+)", body):
            blocks.append({"title": "", "ref": ref, "text": ""})
    return blocks or None


def _content_to_text(content: Any) -> str:
    """Flatten a message content value into plain text.

    Handles three shapes seen in transcripts:
      * string content (Claude Code user prompts)
      * list of typed blocks (text / input_text / output_text / tool_result)
      * Codex ``tool_result`` whose ``content`` is itself a list of typed blocks
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for b in content:
            if not isinstance(b, dict):
                continue
            t = b.get("type", "")
            if t in ("text", "input_text", "output_text"):
                parts.append(b.get("text", ""))
            elif t == "tool_result":
                txt = b.get("content") or b.get("text") or ""
                if isinstance(txt, list):
                    txt = "\n".join(
                        x.get("text", "") for x in txt
                        if isinstance(x, dict)
                    )
                parts.append(str(txt))
        return "\n".join(parts)
    return ""


# ---------------------------------------------------------------------------
# Claude Code parser
# ---------------------------------------------------------------------------

def parse_claude(path: str) -> Iterator[dict]:
    """Yield normalized events from a Claude Code JSONL transcript.

    Claude Code shapes consumed:
      * ``message`` lines with role user/assistant and string-or-block content
      * ``attachment`` lines with hookEvent SessionStart / UserPromptSubmit;
        the Pallium injection text appears in either ``stdout`` (JSON-wrapped
        ``additionalContext``) or ``content`` (string OR list of strings on
        ``hook_additional_context``).
    """
    sid: str | None = None
    cwd: str | None = None
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for i, raw in enumerate(f):
            raw = raw.strip()
            if not raw:
                continue
            try:
                e = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                continue

            etype = e.get("type", "")
            if "sessionId" in e and not sid:
                sid = e.get("sessionId")
            ts = e.get("timestamp")
            cwd = e.get("cwd") or cwd

            if etype == "attachment":
                att = e.get("attachment") or {}
                hook_event = att.get("hookEvent")
                blobs: list[str] = []
                stdout = att.get("stdout")
                if isinstance(stdout, str) and stdout:
                    blobs.append(stdout)
                content = att.get("content")
                if isinstance(content, str) and content:
                    blobs.append(content)
                elif isinstance(content, list):
                    for c in content:
                        if isinstance(c, str):
                            blobs.append(c)
                joined = "\n".join(blobs)
                pal = _extract_pallium_blocks(joined) if "Pallium memory" in joined else None
                if pal or hook_event in ("UserPromptSubmit", "SessionStart"):
                    yield {
                        "ts": ts, "kind": "system_inject", "role": None,
                        "tool_name": hook_event, "tool_id": None,
                        "tool_input": None, "tool_output": None,
                        "text": joined, "raw_index": i,
                        "source_format": "claude",
                        "session_id": sid, "cwd": cwd,
                        "pallium_blocks": pal,
                    }
                continue

            msg = e.get("message")
            if not isinstance(msg, dict):
                continue

            role = msg.get("role")
            content = msg.get("content")

            text_parts: list[str] = []
            if isinstance(content, str):
                text_parts.append(content)
            elif isinstance(content, list):
                for b in content:
                    if not isinstance(b, dict):
                        continue
                    bt = b.get("type", "")
                    if bt == "text":
                        text_parts.append(b.get("text", ""))
                    elif bt == "tool_use":
                        yield {
                            "ts": ts, "kind": "tool_call", "role": role,
                            "tool_name": b.get("name", ""),
                            "tool_id": b.get("id", ""),
                            "tool_input": b.get("input"),
                            "tool_output": None,
                            "text": None, "raw_index": i,
                            "source_format": "claude",
                            "session_id": sid, "cwd": cwd,
                            "pallium_blocks": None,
                        }
                    elif bt == "tool_result":
                        out_raw = b.get("content") or b.get("text") or ""
                        if isinstance(out_raw, list):
                            out = "\n".join(
                                x.get("text", "") for x in out_raw
                                if isinstance(x, dict)
                            )
                        else:
                            out = str(out_raw)
                        yield {
                            "ts": ts, "kind": "tool_result", "role": role,
                            "tool_name": None,
                            "tool_id": b.get("tool_use_id", ""),
                            "tool_input": None, "tool_output": out,
                            "text": None, "raw_index": i,
                            "source_format": "claude",
                            "session_id": sid, "cwd": cwd,
                            "pallium_blocks": None,
                        }
                    elif bt == "image":
                        text_parts.append("[image]")

            real_user_prompt = True
            if role == "user" and isinstance(content, list):
                if not content or all(
                    isinstance(b, dict) and b.get("type") == "tool_result"
                    for b in content
                ):
                    real_user_prompt = False

            text = "\n".join(p for p in text_parts if p)
            pal = (
                _extract_pallium_blocks(text)
                if text and "Pallium memory" in text
                else None
            )

            if not text and not role:
                continue

            if role == "user":
                kind = "user_msg" if real_user_prompt else "tool_result_carrier"
            elif role == "assistant":
                kind = "assistant_msg"
            else:
                kind = "other"

            # Promote user lines that carry a Pallium injection (legacy
            # shape) into the system_inject lane so signal-mining and
            # turn-injection accounting stay consistent.
            if pal and role == "user":
                kind = "system_inject"

            yield {
                "ts": ts, "kind": kind, "role": role,
                "tool_name": None, "tool_id": None,
                "tool_input": None, "tool_output": None,
                "text": text, "raw_index": i,
                "source_format": "claude",
                "session_id": sid, "cwd": cwd,
                "pallium_blocks": pal,
            }


# ---------------------------------------------------------------------------
# Codex parser
# ---------------------------------------------------------------------------

def parse_codex(path: str) -> Iterator[dict]:
    """Yield normalized events from a Codex rollout JSONL transcript.

    Codex envelope: each line is ``{timestamp, type, payload}``. Tool calls
    appear as ``response_item`` payloads with type function_call /
    function_call_output; ``call_id`` pairs them. Pallium injections appear
    inside developer / user / system messages whose flattened text contains
    a ``[Pallium memory ...]`` block.
    """
    sid: str | None = None
    cwd: str | None = None
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for i, raw in enumerate(f):
            raw = raw.strip()
            if not raw:
                continue
            try:
                e = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                continue
            ts = e.get("timestamp")
            t = e.get("type")
            p = e.get("payload") or {}

            if t == "session_meta":
                sid = p.get("id") or sid
                cwd = p.get("cwd") or cwd
                yield {
                    "ts": ts, "kind": "session_meta", "role": None,
                    "tool_name": None, "tool_id": None,
                    "tool_input": None, "tool_output": None,
                    "text": json.dumps(p)[:400], "raw_index": i,
                    "source_format": "codex",
                    "session_id": sid, "cwd": cwd,
                    "pallium_blocks": None,
                }
                continue
            if t == "turn_context":
                cwd = p.get("cwd") or cwd
                continue
            if t == "compacted":
                yield {
                    "ts": ts, "kind": "compacted", "role": None,
                    "tool_name": None, "tool_id": None,
                    "tool_input": None, "tool_output": None,
                    "text": (p.get("message") or "")[:400],
                    "raw_index": i, "source_format": "codex",
                    "session_id": sid, "cwd": cwd,
                    "pallium_blocks": None,
                }
                continue
            if t != "response_item":
                continue

            ptype = p.get("type")
            if ptype == "message":
                role = p.get("role")
                text = _content_to_text(p.get("content"))
                pal = (
                    _extract_pallium_blocks(text)
                    if text and "Pallium memory" in text
                    else None
                )
                kind_map = {
                    "user": "user_msg",
                    "assistant": "assistant_msg",
                    "developer": "system_inject",
                    "system": "system_inject",
                }
                kind = kind_map.get(role, "other")
                if pal:
                    kind = "system_inject"
                yield {
                    "ts": ts, "kind": kind, "role": role,
                    "tool_name": None, "tool_id": None,
                    "tool_input": None, "tool_output": None,
                    "text": text, "raw_index": i,
                    "source_format": "codex",
                    "session_id": sid, "cwd": cwd,
                    "pallium_blocks": pal,
                }
            elif ptype == "function_call":
                name = p.get("name", "")
                args_raw = p.get("arguments", "")
                try:
                    args = json.loads(args_raw) if isinstance(args_raw, str) else args_raw
                except (json.JSONDecodeError, ValueError):
                    args = {"_raw": args_raw}
                yield {
                    "ts": ts, "kind": "tool_call", "role": "assistant",
                    "tool_name": name, "tool_id": p.get("call_id", ""),
                    "tool_input": args, "tool_output": None,
                    "text": None, "raw_index": i,
                    "source_format": "codex",
                    "session_id": sid, "cwd": cwd,
                    "pallium_blocks": None,
                }
            elif ptype == "function_call_output":
                out = p.get("output", "")
                if isinstance(out, dict):
                    out = out.get("content") or json.dumps(out)
                yield {
                    "ts": ts, "kind": "tool_result", "role": "tool",
                    "tool_name": None, "tool_id": p.get("call_id", ""),
                    "tool_input": None, "tool_output": str(out),
                    "text": None, "raw_index": i,
                    "source_format": "codex",
                    "session_id": sid, "cwd": cwd,
                    "pallium_blocks": None,
                }
            elif ptype == "reasoning":
                # Reasoning blocks are not user-visible and not useful for
                # miss mining — drop.
                continue
            elif ptype in ("custom_tool_call", "tool_search_call"):
                yield {
                    "ts": ts, "kind": "tool_call", "role": "assistant",
                    "tool_name": p.get("name", ptype),
                    "tool_id": p.get("call_id", ""),
                    "tool_input": p.get("input") or p.get("arguments"),
                    "tool_output": None,
                    "text": None, "raw_index": i,
                    "source_format": "codex",
                    "session_id": sid, "cwd": cwd,
                    "pallium_blocks": None,
                }
            elif ptype in ("custom_tool_call_output", "tool_search_output"):
                yield {
                    "ts": ts, "kind": "tool_result", "role": "tool",
                    "tool_name": None, "tool_id": p.get("call_id", ""),
                    "tool_input": None,
                    "tool_output": str(p.get("output") or p.get("content") or ""),
                    "text": None, "raw_index": i,
                    "source_format": "codex",
                    "session_id": sid, "cwd": cwd,
                    "pallium_blocks": None,
                }


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------

_CODEX_TOP_TYPES = frozenset({
    "session_meta", "response_item", "event_msg", "turn_context", "compacted",
})


def parse(path: str) -> list[dict]:
    """Auto-detect the transcript format and return all normalized events."""
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        first = f.readline().strip()
    try:
        head = json.loads(first) if first else {}
    except (json.JSONDecodeError, ValueError):
        return []
    if isinstance(head, dict) and head.get("type") in _CODEX_TOP_TYPES:
        return list(parse_codex(path))
    return list(parse_claude(path))


def turns(events: list[dict]) -> list[dict]:
    """Group events into turns keyed by user_msg lines.

    A ``system_inject`` event is attached to the surrounding turn:

      * if it appears before the first user_msg encountered after it →
        ``pre_inject`` of that turn
      * if it appears within an existing turn's tail (Pallium UserPromptSubmit
        fires after the prompt is logged in some transcripts) → ``post_inject``

    Returned turns also expose a flat ``events`` list for everything between
    user prompts (assistant messages, tool calls, tool results).
    """
    out: list[dict] = []
    cur: dict | None = None
    pending_injects: list[dict] = []
    for ev in events:
        if ev["kind"] == "user_msg":
            if cur is not None:
                out.append(cur)
            cur = {
                "turn_index": len(out),
                "user_text": ev.get("text") or "",
                "user_ev": ev,
                "pre_inject": pending_injects,
                "post_inject": [],
                "events": [],
            }
            pending_injects = []
        elif ev["kind"] == "system_inject":
            if cur is None:
                pending_injects.append(ev)
            else:
                cur["post_inject"].append(ev)
        else:
            if cur is None:
                continue
            cur["events"].append(ev)
    if cur is not None:
        out.append(cur)
    return out
