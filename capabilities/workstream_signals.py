"""Strong-signal extraction for workstream assignment (Phase 4A, design 014).

Per the v5 research note §4 the cascade may use only:

  - work_refs (exact normalized match)
  - file paths from tool I/O (regex; module/dir overlap)
  - symbol names (regex)
  - command/error tokens (regex)
  - explicit titles (memory ``payload.task`` / ``decision.decision`` /
    ``investigation_outcome.outcome``)
  - ``MemorySubjectAnchor`` (workstream/component/surface)

It MUST NOT use e5 cosine or plain-text token overlap as a primary signal —
those are listed as "weak, do not lean on" in §4 (R3).

This module is intentionally a self-contained reimplementation of the
specific helpers we need (``normalize_work_ref``, ``anchor_key``) — we do
NOT import the production semantic packages, because that would entangle
write-side mutation with the offline replay. The helpers below mirror the
production logic.

This module is the in-repo port of
``.local/research/_workstream_replay/signals.py`` — **kept verbatim**
including all stoplists, regex literals, and strong-signal acceptance
gates (R3-disciplined).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from core.text import tokenize_text  # ASCII-stable tokenizer

# ---------------------------------------------------------------------------
# work_ref normalization (mirrors semantic/llm_agent_memory.py:593)
# ---------------------------------------------------------------------------

_WORK_REF_SEPARATOR_RE = re.compile(r"[\s_\-]+")


def normalize_work_ref(raw: str) -> str | None:
    if not isinstance(raw, str):
        return None
    value = raw.strip().casefold()
    if not value or len(value) > 128:
        return None
    value = _WORK_REF_SEPARATOR_RE.sub("-", value).strip("-")
    return value if value else None


# ---------------------------------------------------------------------------
# Anchor key (mirrors semantic/agent_conversation_memory_anchors.py:_anchor_key)
# ---------------------------------------------------------------------------

# Subset of the noise-token sets used by ``_anchor_display_value``. Reproduced
# locally to avoid pulling in the full semantic package.
_LEADING_NOISE = {
    "a", "an", "and", "attempt", "authenticate", "by", "can", "cannot",
    "connect", "don", "for", "from", "in", "into", "log", "login", "no",
    "not", "of", "on", "only", "open", "opening", "or", "point", "sign",
    "t", "the", "to", "try", "trying", "use", "using", "with",
}
_TRAILING_NOISE = {"again", "here", "manually", "please", "there"}
_SINGULAR_MAP = {"mirrors": "mirror", "snapshots": "snapshot", "exports": "export"}

ALLOWED_ANCHOR_KINDS = ("workstream", "component", "surface")


def anchor_display_value(value: str) -> str:
    if not isinstance(value, str):
        return ""
    tokens = tokenize_text(value)
    while tokens and (tokens[0] in _LEADING_NOISE or (len(tokens[0]) == 1 and not tokens[0].isdigit())):
        tokens = tokens[1:]
    while tokens and tokens[-1] in _TRAILING_NOISE:
        tokens = tokens[:-1]
    tokens = [_SINGULAR_MAP.get(t, t) for t in tokens]
    return " ".join(tokens)


def anchor_key(kind: str, value: str) -> str | None:
    k = (kind or "").strip().lower()
    if k not in ALLOWED_ANCHOR_KINDS:
        return None
    norm = anchor_display_value(value)
    if not norm:
        return None
    return f"{k}:{norm}"


# ---------------------------------------------------------------------------
# File-path extraction
# ---------------------------------------------------------------------------

# Permissive raw matcher — we then filter aggressively in :func:`extract_file_paths`
# to ensure we only keep substrings that genuinely look like filesystem paths.
_PATH_RE = re.compile(
    r"""
    (?<![A-Za-z0-9])              # left boundary — not in the middle of a word
    (?:[A-Za-z]:[\\/])?           # optional Windows drive
    (?:[A-Za-z0-9_.\-]+[\\/])     # at least one segment with a separator
    (?:[A-Za-z0-9_.\-]+[\\/])*    # more segments, optional
    [A-Za-z0-9_.\-]+              # final segment
    """,
    re.VERBOSE,
)

# Common "looks like a path but is actually URL/email/etc" prefixes we want to
# discard before downstream matching.
_PATH_BLOCKLIST_PREFIXES = ("http://", "https://", "git://", "mailto:")

# Strong-signal acceptance gate (R3). At least one of these conditions must be
# true for a path-like substring to count as a real path. Matches the
# architect-review acceptance rubric.
FILE_EXTENSIONS = frozenset({
    ".py", ".ts", ".js", ".tsx", ".jsx", ".md", ".json", ".yaml", ".yml",
    ".toml", ".sh", ".ps1", ".cfg", ".ini", ".sql", ".rs", ".go", ".java",
    ".kt", ".rb", ".gradle", ".lock", ".txt", ".csv", ".jsonl", ".ipynb",
})

TOP_LEVEL_DIRS = frozenset({
    "core", "semantic", "evals", "tests", "docs", "tools", "roadmap",
    "storage", "retrieval", "capabilities", "integrations", "api", "app",
    "providers", "scripts", ".local", ".claude",
})

_WIN_DRIVE_RE = re.compile(r"^[a-z]:[\\/]")
_PATH_PREFIX_LITERALS = ("~/", "./", "../", "/c/sap-dev/", "c:/", "c:\\")

# Common English nouns/adjectives — when a path is exactly two segments and
# both sides are in this set, reject (catches `before/after`, `dark/light`,
# `hours/days`, etc.).
_PATH_ENGLISH_PAIRS = frozenset({
    "before", "after", "dark", "light", "hours", "days", "top", "bottom",
    "left", "right", "start", "end", "pre", "post", "old", "new", "good",
    "bad", "up", "down", "in", "out", "on", "off", "yes", "no",
    "functional", "minimal", "low", "high", "first", "last", "best", "worst",
    "less", "more", "same", "different",
})


def _path_is_strong_signal(norm: str, raw_lower: str) -> bool:
    """Return True iff ``norm`` (lowercased forward-slash path) qualifies as
    a strong file-path signal under the architect-review acceptance rubric.

    ``raw_lower`` is the original substring lowercased (preserves backslashes
    and a leading drive letter for the Windows-drive check).
    """
    # Extension check — final segment must end in a known extension.
    last_seg = norm.rsplit("/", 1)[-1]
    dot = last_seg.rfind(".")
    if dot >= 0:
        ext = last_seg[dot:]
        if ext in FILE_EXTENSIONS:
            return True
    # Top-level repo dir prefix.
    first_seg = norm.split("/", 1)[0]
    if first_seg in TOP_LEVEL_DIRS:
        return True
    # Recognized literal prefix on the lowercased raw substring.
    for p in _PATH_PREFIX_LITERALS:
        if raw_lower.startswith(p):
            return True
    # Windows drive letter on the raw substring.
    if _WIN_DRIVE_RE.match(raw_lower):
        return True
    return False


def extract_file_paths(text: str) -> list[str]:
    """Return distinct path-like substrings from a text blob, normalized.

    Normalization: forward slashes only, casefolded, leading/trailing
    separators stripped. Anything containing ``://`` is dropped.

    Strong-signal acceptance (per architect review of T1.1+T1.2+T1.3, R3):
    a candidate is kept only if it satisfies one of:
      - ends in a known file extension (see :data:`FILE_EXTENSIONS`)
      - starts with a recognized top-level repo dir (see :data:`TOP_LEVEL_DIRS`)
      - starts with a Windows drive letter
      - starts with ``~/``, ``./``, ``../``, ``/c/sap-dev/``, ``c:/``, or ``c:\\``

    The 2-segment minimum and numeric-only filter are retained. An additional
    English-noun-pair filter (``before/after``, ``dark/light`` etc.) rejects
    slash-separated English idioms that survived the gate.
    """
    if not text:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for m in _PATH_RE.finditer(text):
        raw = m.group(0)
        low = raw.lower()
        if any(low.startswith(p) for p in _PATH_BLOCKLIST_PREFIXES):
            continue
        if "://" in low:
            continue
        norm = raw.replace("\\", "/").strip("/").lower()
        # Keep only paths with at least 2 segments — single-segment "names"
        # are too noisy.
        if "/" not in norm:
            continue
        # Reject paths that are numeric-only segments (e.g. "12/34", "0/null"
        # via the next branch since 'null' isn't English-pair listed but the
        # numeric branch + English-pair branch together catch the family).
        segs = norm.split("/")
        if all(seg.replace(".", "").isdigit() for seg in segs):
            continue
        # Strong-signal acceptance gate.
        if not _path_is_strong_signal(norm, low):
            continue
        # English-pair rejection (after the gate, in case top-dir prefix snuck
        # one in).
        if len(segs) == 2 and segs[0] in _PATH_ENGLISH_PAIRS and segs[1] in _PATH_ENGLISH_PAIRS:
            continue
        if norm in seen:
            continue
        seen.add(norm)
        out.append(norm)
    return out


def file_path_directory(path: str, depth: int = 2) -> str:
    """Return the leading ``depth`` segments of a normalized path.

    Used by the cascade for "module/dir overlap": two paths overlap when
    their first ``depth`` segments agree.
    """
    parts = path.split("/")
    if len(parts) <= 1:
        return ""
    return "/".join(parts[: max(1, depth)])


# ---------------------------------------------------------------------------
# Symbol-name extraction
# ---------------------------------------------------------------------------

# Strong-signal acceptance (R3, per architect review):
#  * CamelCase identifiers must have at least TWO internal capital letters,
#    i.e. proper-CamelCase classes/types like ``WorkstreamRegistry``,
#    ``MemoryEnvelopeScope``, ``IndexEntry``, ``SemanticExtraction``.
#    Single-capital words like ``This``, ``Want``, ``Pallium``, ``Joule``,
#    ``Wallet`` are rejected outright.
#  * Snake-case callsites accepted only when ``name(`` has ≥1 underscore AND
#    length ≥6 — captures real function calls like
#    ``assign_workstream_for_item`` and ``_normalize_work_ref``, rejects
#    short builtins.
_CAMEL_RE = re.compile(r"\b[A-Z][a-z]+[A-Z][A-Za-z0-9_]{1,}\b")
_CALLSITE_RE = re.compile(r"\b([a-z][a-z0-9]*(?:_[a-z0-9]+)+)\s*\(")

# Identifier-shaped strings that show up casually in conversation and almost
# never indicate a workstream — observed in the T1.3 top-10s.
_SYMBOL_STOPLIST = {
    # Generic English nouns / English CamelCase verbs that show up everywhere
    "Memory", "Container", "Thread", "User", "Item", "Object", "Source",
    "Query", "Result", "Status", "Config", "Default", "True", "False",
    "None", "List", "Dict", "Set", "Tuple", "String", "Boolean",
    # System / brand names referenced casually in conversation about
    # systems — too generic to anchor a workstream cluster.
    "Pallium", "Claude", "Joule", "Wallet", "Kafka", "Service", "Event",
}


def extract_symbols(text: str) -> list[str]:
    """Return distinct strong-signal symbol identifiers from ``text``.

    Strong signals only: proper-CamelCase (≥2 internal capitals) and
    snake_case callsites (≥1 underscore, length ≥6). Sentence-initial
    English words and common system names are rejected.
    """
    if not text:
        return []
    out: set[str] = set()
    for m in _CAMEL_RE.finditer(text):
        sym = m.group(0)
        if sym in _SYMBOL_STOPLIST:
            continue
        out.add(sym)
    for m in _CALLSITE_RE.finditer(text):
        sym = m.group(1)
        if len(sym) < 6:
            continue
        if "_" not in sym:
            continue
        if sym in _SYMBOL_STOPLIST:
            continue
        out.add(sym)
    return sorted(out)


# ---------------------------------------------------------------------------
# Command / error tokens
# ---------------------------------------------------------------------------

_COMMAND_RE = re.compile(
    r"\b(?:python\s+-m\s+([A-Za-z0-9_.]+)"
    r"|pytest\s+([A-Za-z0-9_./\\\-]+)"
    r"|pip\s+install\s+([A-Za-z0-9_.\-]+)"
    r"|bash\s+([A-Za-z0-9_./\\\-]+)"
    r")\b"
)

_ERROR_TOKEN_RE = re.compile(r"\b([A-Z][a-zA-Z]*Error|[A-Z][a-zA-Z]*Exception)\b")


def extract_commands(text: str) -> list[str]:
    if not text:
        return []
    out: set[str] = set()
    for m in _COMMAND_RE.finditer(text):
        for g in m.groups():
            if g:
                out.add(g.lower())
    for m in _ERROR_TOKEN_RE.finditer(text):
        out.add(m.group(1))
    return sorted(out)


# ---------------------------------------------------------------------------
# Explicit titles from memory payloads
# ---------------------------------------------------------------------------

# Mapping of memory ``type`` to the payload field that we treat as an
# "explicit title". Anything else stays unrecognized.
_PAYLOAD_TITLE_FIELDS = {
    "task_checkpoint": ("task",),
    "decision": ("decision",),
    "investigation_outcome": ("outcome",),
    "note": ("title",),
    "thread_summary": ("summary",),  # accepted but down-weighted by length
}


def explicit_titles_from_payload(memory_type: str, payload: dict | None) -> list[str]:
    if not payload or not isinstance(payload, dict):
        return []
    fields = _PAYLOAD_TITLE_FIELDS.get(memory_type or "", ())
    titles: list[str] = []
    for f in fields:
        v = payload.get(f)
        if isinstance(v, str) and v.strip():
            titles.append(v.strip())
    return titles


_STOPWORDS_FOR_NGRAMS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with",
    "by", "is", "are", "was", "were", "be", "been", "being", "this", "that",
    "these", "those", "it", "as", "at", "from", "into", "out", "if", "then",
}


def title_ngrams(title: str, n: int = 3) -> set[tuple[str, ...]]:
    """Return distinct non-stopword n-grams of a title.

    Used by the cascade stage 4 (explicit-title match): two titles share a
    workstream signature if any non-stopword n-gram (default 3) overlaps.
    """
    toks = [t for t in tokenize_text(title) if t not in _STOPWORDS_FOR_NGRAMS]
    if len(toks) < n:
        if toks:
            return {tuple(toks)}
        return set()
    return {tuple(toks[i : i + n]) for i in range(len(toks) - n + 1)}


# ---------------------------------------------------------------------------
# Per-item signal extraction
# ---------------------------------------------------------------------------


@dataclass
class ItemSignals:
    """Strong signals extracted from one source item + its attached memories.

    A signal is "present" iff its set is non-empty. The cascade only
    operates on these strong signals; nothing else.
    """

    work_refs: set[str] = field(default_factory=set)
    file_paths: set[str] = field(default_factory=set)
    file_dirs: set[str] = field(default_factory=set)        # 2-segment prefixes
    symbols: set[str] = field(default_factory=set)
    commands: set[str] = field(default_factory=set)
    titles: set[str] = field(default_factory=set)           # raw titles (kept for display)
    title_ngrams: set[tuple[str, ...]] = field(default_factory=set)
    anchors: set[str] = field(default_factory=set)          # anchor_key strings, kind=workstream

    def has_any_strong(self) -> bool:
        return bool(
            self.work_refs
            or self.file_paths
            or self.symbols
            or self.commands
            or self.titles
            or self.anchors
        )

    def strong_signal_count(self) -> int:
        """Number of strong-signal *kinds* present (0..6)."""
        return sum(
            1
            for s in (
                self.work_refs,
                self.file_paths,
                self.symbols,
                self.commands,
                self.titles,
                self.anchors,
            )
            if s
        )


def signals_from_item(
    *,
    content_text: str,
    metadata_json: dict | None,
    memory_records: list[dict],
) -> ItemSignals:
    """Extract strong signals from one source item.

    - ``content_text`` is the raw ``source_items.content`` field.
    - ``metadata_json`` is the parsed ``source_items.metadata_json`` dict.
    - ``memory_records`` is a list of ``{type, payload, envelope}`` dicts for
      every memory whose evidence includes this source item. Each ``payload``
      and ``envelope`` is the parsed JSON; either may be empty.
    """
    sig = ItemSignals()
    metadata_json = metadata_json or {}

    # work_refs from metadata
    raw_work_refs = metadata_json.get("pallium_work_refs") if isinstance(metadata_json, dict) else None
    if isinstance(raw_work_refs, list):
        for r in raw_work_refs:
            n = normalize_work_ref(r) if isinstance(r, str) else None
            if n:
                sig.work_refs.add(n)

    # work_refs from each memory envelope
    for mem in memory_records:
        env = mem.get("envelope") or {}
        scope = env.get("scope") if isinstance(env, dict) else None
        if isinstance(scope, dict):
            for r in scope.get("work_refs") or []:
                n = normalize_work_ref(r) if isinstance(r, str) else None
                if n:
                    sig.work_refs.add(n)

    # file paths and symbols and commands from content_text
    if content_text:
        for p in extract_file_paths(content_text):
            sig.file_paths.add(p)
            d = file_path_directory(p, depth=2)
            if d:
                sig.file_dirs.add(d)
        for s in extract_symbols(content_text):
            sig.symbols.add(s)
        for c in extract_commands(content_text):
            sig.commands.add(c)

    # subject_hints from metadata → workstream-kind anchors only
    raw_hints = metadata_json.get("pallium_subject_hints") if isinstance(metadata_json, dict) else None
    if isinstance(raw_hints, list):
        for h in raw_hints:
            if not isinstance(h, dict):
                continue
            kind = str(h.get("kind") or "").strip().lower()
            value = str(h.get("value") or "").strip()
            if kind != "workstream":
                continue
            k = anchor_key(kind, value)
            if k:
                sig.anchors.add(k)

    # subjects from each memory envelope (workstream kind only)
    for mem in memory_records:
        env = mem.get("envelope") or {}
        subjects = env.get("subjects") if isinstance(env, dict) else None
        if isinstance(subjects, list):
            for sub in subjects:
                if not isinstance(sub, dict):
                    continue
                kind = str(sub.get("kind") or "").strip().lower()
                value = str(sub.get("value") or "").strip()
                if kind != "workstream":
                    continue
                k = anchor_key(kind, value)
                if k:
                    sig.anchors.add(k)

    # explicit titles from memory payloads
    for mem in memory_records:
        mtype = mem.get("type") or ""
        payload = mem.get("payload") or {}
        for t in explicit_titles_from_payload(mtype, payload):
            sig.titles.add(t)
            sig.title_ngrams |= title_ngrams(t, n=3)

    return sig


def parse_json_safe(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        v = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return v if isinstance(v, dict) else {}
