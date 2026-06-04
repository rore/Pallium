"""Miss-signal detection on parsed turns.

Three signals — each chosen because it's recoverable from transcript-only
data (i.e. data the production Pallium DB does not record):

  * ``recall_intent``   user prompt is a continuation / recall request
                        ("continue", "what did we decide", "summarize"...)
  * ``repeated_work``   the same file Read or Grep pattern appears in
                        2+ turns of the same session — the agent is
                        rediscovering context that earlier work had
                        already surfaced
  * ``future_oracle``   a vague continuation prompt is followed by
                        N≥2 discovery tool calls and zero productive
                        actions — the agent had no orientation and is
                        searching for ground truth

User-correction phrase mining is intentionally NOT in this module:
``evals/agent_correction_analysis.py`` already detects corrections from the
Pallium DB using an LLM classifier (``is_correction``) which is more
accurate than regex. The runner can opt-in to fold those labels in via
``audit_join``.
"""
from __future__ import annotations

import re
from typing import Any


# ---------------------------------------------------------------------------
# Phrase patterns
# ---------------------------------------------------------------------------

_RECALL_INTENT_PATTERNS: tuple[re.Pattern, ...] = tuple(re.compile(p) for p in [
    r"^continue\b",
    r"\b(let'?s )?continue (with|the|where)\b",
    r"\bwhat did (we|you) (decide|do|change|validate|agree|find)\b",
    r"\bwhat (was|were) the\b.*\b(decision|conclusion|next)\b",
    r"\bsummari[sz]e\b",
    r"\bnext (task|step|action)s?\b",
    r"\bpick up (where|the)\b",
    r"\bresume\b",
    r"\bwhere (did|were) we\b",
    r"\bremind me\b.*\b(what|where|how)\b",
    r"\bopen the (thing|spec|task|plan)\b",
    r"\bback to (the|our)\b",
    r"\bfollow ?up\b",
    r"\b(what|where) (is|was) (the|our) (current|active|last)\b",
])

_VAGUE_CONTINUATION_PATTERNS: tuple[re.Pattern, ...] = tuple(re.compile(p) for p in [
    r"^continue\b",
    r"^next\b",
    r"^ok\b",
    r"^go\b",
    r"^proceed\b",
    r"^keep going\b",
])


_BOILERPLATE_TAGS: tuple[re.Pattern, ...] = tuple(re.compile(p, re.DOTALL | re.IGNORECASE) for p in [
    r"<INSTRUCTIONS>.*?</INSTRUCTIONS>",
    r"<EXTREMELY[_-]IMPORTANT>.*?</EXTREMELY[_-]IMPORTANT>",
    r"<system-reminder>.*?</system-reminder>",
    r"<command-message>.*?</command-message>",
    r"<command-name>.*?</command-name>",
    r"<ide_[a-z_]+>.*?</ide_[a-z_]+>",
])


def is_boilerplate_only(text: str) -> bool:
    """True when the user line is essentially system-prompt glue (AGENTS.md
    headers, SessionStart skill listings, etc.) with no real prompt body.

    Filtering rule: strip known boilerplate tags, then require either
    enough remaining text (≥30 chars) OR no boilerplate markers in the
    original. The second branch protects very short *real* prompts like
    "continue" or "go" — they're tiny but they're the prompts we most
    want recall-intent / future-oracle to flag.
    """
    if not text:
        return True
    cleaned = text
    had_boilerplate = False
    for pat in _BOILERPLATE_TAGS:
        new = pat.sub(" ", cleaned)
        if new != cleaned:
            had_boilerplate = True
        cleaned = new
    cleaned = cleaned.strip()
    if not cleaned:
        return True
    if had_boilerplate and len(cleaned) < 30:
        return True
    return False


def _match_first(text: str, patterns: tuple[re.Pattern, ...]) -> str | None:
    if not text:
        return None
    lo = text.lower()
    for pat in patterns:
        m = pat.search(lo)
        if m:
            return m.group(0)
    return None


# ---------------------------------------------------------------------------
# Tool-call analysis on a turn
# ---------------------------------------------------------------------------

_DISCOVERY_TOOLS = frozenset({"Read", "Grep", "Glob"})
_PRODUCTIVE_TOOLS = frozenset({"Edit", "Write", "NotebookEdit", "apply_patch"})


def _shell_is_discovery(cmd: Any) -> bool:
    if isinstance(cmd, list):
        cmd = " ".join(str(x) for x in cmd)
    cmd = str(cmd or "").lower().strip()
    if not cmd:
        return False
    head = cmd.split()[0] if cmd.split() else ""
    return head in {"cat", "rg", "grep", "ls", "find", "head", "tail"} or any(
        f" {k} " in f" {cmd} " for k in ("cat", "rg", "grep", "ls", "find", "head", "tail")
    )


def discovery_calls(turn: dict) -> list[dict]:
    """Return tool_call events that look like discovery (Read/Grep/Glob/shell-cat-or-rg)."""
    out: list[dict] = []
    for ev in turn.get("events", []):
        if ev.get("kind") != "tool_call":
            continue
        name = ev.get("tool_name") or ""
        if name in _DISCOVERY_TOOLS:
            out.append(ev)
            continue
        if name == "shell":
            inp = ev.get("tool_input") or {}
            cmd = inp.get("command") or inp.get("input") or ""
            if _shell_is_discovery(cmd):
                out.append(ev)
    return out


def productive_calls(turn: dict) -> list[dict]:
    """Return tool_call events that mutated state (Edit/Write/apply_patch/...)."""
    out: list[dict] = []
    for ev in turn.get("events", []):
        if ev.get("kind") != "tool_call":
            continue
        if (ev.get("tool_name") or "") in _PRODUCTIVE_TOOLS:
            out.append(ev)
    return out


def turn_pallium_blocks(turn: dict) -> list[dict]:
    """All Pallium memory blocks attached to this turn (pre + post)."""
    blocks: list[dict] = []
    for ev in (turn.get("pre_inject") or []) + (turn.get("post_inject") or []):
        for b in (ev.get("pallium_blocks") or []):
            blocks.append(b)
    return blocks


# ---------------------------------------------------------------------------
# Per-turn detectors
# ---------------------------------------------------------------------------

def detect_recall_intent(turn: dict) -> str | None:
    """Return the matched phrase or None."""
    return _match_first(turn.get("user_text") or "", _RECALL_INTENT_PATTERNS)


def detect_future_oracle(turn: dict, min_discovery: int = 2) -> dict | None:
    """Detect the "vague prompt → discovery-only turn" pattern.

    Heuristic: prompt is vague (≤6 words OR matches a vague-continuation
    pattern), at least ``min_discovery`` discovery tool calls fire, and zero
    productive calls fire. Returns evidence on hit, None on miss.
    """
    u = (turn.get("user_text") or "").strip()
    if not u:
        return None
    is_vague = (
        len(u.split()) <= 6
        or _match_first(u, _VAGUE_CONTINUATION_PATTERNS) is not None
    )
    if not is_vague:
        return None
    disc = discovery_calls(turn)
    prod = productive_calls(turn)
    if len(disc) < min_discovery or prod:
        return None
    targets = []
    for e in disc[:6]:
        inp = e.get("tool_input") or {}
        target = (
            inp.get("file_path")
            or inp.get("pattern")
            or inp.get("command")
            or ""
        )
        if isinstance(target, list):
            target = " ".join(str(x) for x in target)
        targets.append((e.get("tool_name"), str(target)[:160]))
    return {
        "discovery_count": len(disc),
        "productive_count": len(prod),
        "discovery_targets": targets,
    }


# ---------------------------------------------------------------------------
# Session-level detector
# ---------------------------------------------------------------------------

def detect_repeated_work(turns: list[dict], min_repeats: int = 2) -> list[dict]:
    """Find Read file_paths and Grep patterns appearing in N≥``min_repeats`` turns.

    Returns one record per repeated key, each pointing at the first turn it
    appeared in. The runner emits one row per record.
    """
    file_turns: dict[str, list[int]] = {}
    grep_turns: dict[str, list[int]] = {}
    for ti, t in enumerate(turns):
        seen_file: set[str] = set()
        seen_grep: set[str] = set()
        for ev in t.get("events", []):
            if ev.get("kind") != "tool_call":
                continue
            name = ev.get("tool_name") or ""
            inp = ev.get("tool_input") or {}
            if name == "Read":
                fp = (inp.get("file_path") or "").lower()
                if fp and fp not in seen_file:
                    file_turns.setdefault(fp, []).append(ti)
                    seen_file.add(fp)
            elif name == "Grep":
                pat = (inp.get("pattern") or "").lower()
                if pat and pat not in seen_grep:
                    grep_turns.setdefault(pat, []).append(ti)
                    seen_grep.add(pat)
    hits: list[dict] = []
    for fp, tis in file_turns.items():
        if len(tis) >= min_repeats:
            hits.append({"kind": "repeated_read", "key": fp, "turn_indexes": tis})
    for pat, tis in grep_turns.items():
        if len(tis) >= min_repeats:
            hits.append({"kind": "repeated_grep", "key": pat, "turn_indexes": tis})
    return hits
