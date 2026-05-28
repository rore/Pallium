"""Offline subject enrichment for active Pallium memories (V1/V2/V3).

Generates a candidate subject for each active non-fact memory under three
variants and writes one JSONL row per memory to
``evals/subject_enrichment/output/subjects_2026-05-28.jsonl``.

Variants
--------
V1: payload_fallback           — current production behavior, the baseline.
                                  uses ``core.subject.subject_text_for_payload``.
V2: deterministic from envelope — picks subject_hints / topic / topic_label /
                                  retrieval_context / first noun phrase of the
                                  type-specific body field; falls back to V1
                                  when nothing extracts.
V3: LLM noun-phrase             — Claude Sonnet via local proxy. 5–10 word
                                  noun phrase that names what the memory is
                                  about. Cached on disk.

Read-only on the production DB at
``%USERPROFILE%/.pallium/data/pallium.db``. No production code changes.

Usage::
    python -m evals.subject_enrichment.enrich
    python -m evals.subject_enrichment.enrich --no-llm
    python -m evals.subject_enrichment.enrich --limit-llm 50
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from core.subject import subject_text_for_payload  # noqa: E402

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_DB = str(Path.home() / ".pallium" / "data" / "pallium.db")
DEFAULT_OUT = (
    _PROJECT_ROOT
    / "evals"
    / "subject_enrichment"
    / "output"
    / "subjects_2026-05-28.jsonl"
)
DEFAULT_RUN_LOG = _PROJECT_ROOT / ".local" / "research" / "_subject_enrichment_run.md"
DEFAULT_CACHE_DIR = _PROJECT_ROOT / ".local" / "llm-cache" / "subject_enrichment"

ACTIVE_TYPES = (
    "decision",
    "investigation_outcome",
    "constraint_memory",
    "thread_summary",
    "task_checkpoint",
    "note",
)
SINCE = "2026-05-18"

LLM_SYSTEM_PROMPT = (
    "You produce a topic label for a memory record. Read the body and any "
    "evidence and emit a 5-10 word noun phrase that names what this memory "
    "is about (the subject, not a sentence). Preserve the original "
    "language. Do not invent or generalize beyond what's in the text. "
    "Reply with only the noun phrase, no preamble, no quotes, no JSON."
)
LLM_USER_TEMPLATE = (
    "Memory type: {item_type}\n"
    "Body:\n{body}\n\n"
    "Evidence:\n{evidence}\n\n"
    "Topic label (5-10 word noun phrase, no preamble):"
)


# ---------------------------------------------------------------------------
# V2: deterministic extractor
# ---------------------------------------------------------------------------

# Light noun-phrase heuristic: take the leading content up to a sentence
# boundary, drop a leading filler verb if any, then truncate to a word cap.
_LEADING_VERBS = {
    "use", "used", "using", "implement", "implemented", "implementing",
    "add", "added", "adding", "remove", "removed", "removing",
    "fix", "fixed", "fixing", "investigate", "investigating",
    "ensure", "ensuring", "make", "making", "build", "building",
    "ship", "shipped", "shipping", "create", "created", "creating",
    "decided", "decide", "deciding", "determine", "determined",
    "switch", "switched", "switching", "consolidate", "consolidating",
    "the", "a", "an",
}
_SENTENCE_END = re.compile(r"[.!?\n]")


def _first_noun_phrase(text: str, max_words: int = 8) -> str:
    if not text:
        return ""
    head = _SENTENCE_END.split(text.strip(), maxsplit=1)[0]
    head = head.strip(" -:;,")
    if not head:
        return ""
    words = head.split()
    # Drop leading filler verbs to land on the noun.
    while words and words[0].lower().strip(",.;:") in _LEADING_VERBS:
        words = words[1:]
    if not words:
        words = head.split()
    return " ".join(words[:max_words]).strip(" -:;,")


def _from_enrichment(payload: dict[str, Any]) -> str:
    enr = payload.get("retrieval_enrichment")
    if isinstance(enr, dict):
        rc = enr.get("retrieval_context")
        if isinstance(rc, str) and rc.strip():
            return rc.strip()[:200]
    return ""


def _from_subject_hints(payload: dict[str, Any]) -> str:
    sh = payload.get("subject_hints")
    if isinstance(sh, list) and sh:
        # join the first 3 hints
        bits = [str(x).strip() for x in sh[:3] if str(x).strip()]
        if bits:
            return ", ".join(bits)[:200]
    if isinstance(sh, str) and sh.strip():
        return sh.strip()[:200]
    return ""


def _from_topic(payload: dict[str, Any]) -> str:
    for key in ("topic_label", "topic", "tags", "anchors"):
        v = payload.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()[:200]
        if isinstance(v, list) and v:
            bits = [str(x).strip() for x in v[:3] if str(x).strip()]
            if bits:
                return ", ".join(bits)[:200]
    return ""


def deterministic_subject(item_type: str, payload: dict[str, Any]) -> str:
    """V2: type-aware deterministic extraction.

    Lookup order (returns first non-empty):
      1. ``subject_hints``
      2. ``topic_label`` / ``topic`` / ``tags`` / ``anchors``
      3. ``retrieval_enrichment.retrieval_context`` (already a topic phrase
         emitted by the write_enrichment LLM step on thread_summary /
         task_checkpoint).
      4. Type-specific noun-phrase head:
         - decision           : first NP of ``decision``
         - investigation_outcome: first NP of ``investigation_outcome``
                                 / ``outcome_summary`` / ``findings``
         - task_checkpoint    : ``task`` truncated, else NP of ``summary``
         - thread_summary     : NP of ``summary``
         - constraint_memory  : ``constraint_text`` / ``constraint``
                                truncated to 8 words
         - note               : ``title`` / first NP of ``content``
      5. V1 fallback (so V2 is never strictly worse).
    """
    if not payload:
        return ""
    found = _from_subject_hints(payload) or _from_topic(payload) or _from_enrichment(payload)
    if found:
        return found

    if item_type == "decision":
        body = payload.get("decision") or payload.get("statement") or ""
        np = _first_noun_phrase(body, max_words=8)
        if np:
            return np
    elif item_type == "investigation_outcome":
        for k in ("investigation_outcome", "outcome_summary", "findings", "outcome", "summary"):
            v = payload.get(k)
            if isinstance(v, str) and v.strip():
                np = _first_noun_phrase(v, max_words=8)
                if np:
                    return np
    elif item_type == "task_checkpoint":
        v = payload.get("task")
        if isinstance(v, str) and v.strip():
            return _first_noun_phrase(v, max_words=10) or v.strip()[:120]
        v = payload.get("summary")
        if isinstance(v, str) and v.strip():
            np = _first_noun_phrase(v, max_words=8)
            if np:
                return np
    elif item_type == "thread_summary":
        for k in ("topic_label", "summary"):
            v = payload.get(k)
            if isinstance(v, str) and v.strip():
                np = _first_noun_phrase(v, max_words=8)
                if np:
                    return np
    elif item_type == "constraint_memory":
        for k in ("constraint_text", "constraint", "summary"):
            v = payload.get(k)
            if isinstance(v, str) and v.strip():
                # Constraints are often imperative ("don't ..."); keep first
                # 8 words.
                return " ".join(v.split()[:8]).strip(" -:;,")
    elif item_type == "note":
        v = payload.get("title")
        if isinstance(v, str) and v.strip():
            return v.strip()[:120]
        v = payload.get("content")
        if isinstance(v, str) and v.strip():
            np = _first_noun_phrase(v, max_words=10)
            if np:
                return np

    # Final fallback: V1.
    return subject_text_for_payload(item_type, payload)


# ---------------------------------------------------------------------------
# Body / evidence extraction for V3 prompt
# ---------------------------------------------------------------------------


def _body_text(item_type: str, payload: dict[str, Any]) -> str:
    """Best-effort body excerpt for the LLM prompt."""
    candidates = []
    if item_type == "decision":
        candidates = [payload.get("decision"), payload.get("decision_evidence_text"), payload.get("rationale")]
    elif item_type == "investigation_outcome":
        candidates = [
            payload.get("investigation_outcome"),
            payload.get("investigation_evidence_text"),
            payload.get("rationale"),
        ]
    elif item_type == "constraint_memory":
        candidates = [payload.get("constraint_text"), payload.get("summary"), payload.get("evidence_context")]
    elif item_type == "thread_summary":
        candidates = [payload.get("summary")]
    elif item_type == "task_checkpoint":
        candidates = [payload.get("task"), payload.get("summary"), payload.get("current_state")]
    elif item_type == "note":
        candidates = [payload.get("title"), payload.get("content")]
    parts = [str(x).strip() for x in candidates if isinstance(x, str) and x.strip()]
    body = " — ".join(parts)
    return body[:1200]


def _evidence_text(item_type: str, payload: dict[str, Any]) -> str:
    """Best-effort short evidence snippet for the LLM prompt."""
    if item_type == "task_checkpoint":
        ev = payload.get("evidence")
        if isinstance(ev, list) and ev:
            return " | ".join(str(x) for x in ev[:3])[:600]
    if item_type == "thread_summary":
        cn = payload.get("conclusions")
        if isinstance(cn, list) and cn:
            bits = []
            for c in cn[:3]:
                if isinstance(c, dict):
                    bits.append(str(c.get("text", ""))[:200])
            return " | ".join(bits)[:600]
    enr = payload.get("retrieval_enrichment")
    if isinstance(enr, dict):
        rc = enr.get("retrieval_context")
        if isinstance(rc, str):
            return rc.strip()[:600]
    return ""


# ---------------------------------------------------------------------------
# LLM cache
# ---------------------------------------------------------------------------


def _cache_path(cache_dir: Path, mid: str) -> Path:
    h = hashlib.sha1(mid.encode("utf-8")).hexdigest()[:16]
    return cache_dir / f"{h}.json"


def _read_cache(cache_dir: Path, mid: str) -> str | None:
    p = _cache_path(cache_dir, mid)
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            v = data.get("subject_v3_llm")
            if isinstance(v, str):
                return v
        except Exception:
            return None
    return None


def _write_cache(cache_dir: Path, mid: str, value: str, meta: dict[str, Any]) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    payload = {"memory_object_id": mid, "subject_v3_llm": value, **meta}
    _cache_path(cache_dir, mid).write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# LLM provider
# ---------------------------------------------------------------------------


def _build_provider():
    """Build the production-model LLM provider (Claude Sonnet via local proxy).

    Matches the pattern in evals/anchor_probe/counterfactual_better_subject.py.
    Returns (provider, error_message_or_None).
    """
    try:
        from app.config import AppConfig
        from app.dependencies import build_llm_provider

        config = AppConfig.from_env()
        provider = build_llm_provider(
            config,
            provider_name="hai_anthropic",
            model="anthropic--claude-sonnet-latest",
        )
        return provider, None
    except Exception as exc:  # pragma: no cover - infra issue
        return None, f"{type(exc).__name__}: {exc}"


def _llm_subject(provider, item_type: str, body: str, evidence: str) -> str:
    """One LLM call. Plain-text reply (we instruct no JSON).

    The proxy's generate_json wraps the response in JSON; if we coerce the
    plain phrase into a JSON-stringified field, we keep using generate_json
    to reuse retry/throttling. We ask for a JSON object with one field.
    """
    schema = '{"phrase":"string"}'
    system = (
        LLM_SYSTEM_PROMPT
        + "\n\nReturn JSON of the form {\"phrase\": \"...\"} where phrase is the "
        "5-10 word noun phrase. Nothing else."
    )
    user = LLM_USER_TEMPLATE.format(
        item_type=item_type,
        body=body or "(no body)",
        evidence=evidence or "(no evidence)",
    )
    resp = provider.generate_json(
        system_prompt=system,
        user_prompt=user,
        schema_description=schema,
    )
    phrase = ""
    try:
        phrase = str(resp.parsed_json.get("phrase", "")).strip()
    except Exception:
        phrase = ""
    return phrase[:200]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


@dataclass
class Row:
    memory_object_id: str
    type: str
    container_ref: str
    payload: dict[str, Any]


def _load_active(db: str) -> list[Row]:
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    placeholders = ",".join("?" * len(ACTIVE_TYPES))
    rows = con.execute(
        f"""
        SELECT id, type, container_ref, payload_json
        FROM memory_objects
        WHERE lifecycle != 'superseded'
          AND created_at >= ?
          AND type IN ({placeholders})
        ORDER BY created_at DESC
        """,
        (SINCE, *ACTIVE_TYPES),
    ).fetchall()
    con.close()
    out: list[Row] = []
    for r in rows:
        try:
            payload = json.loads(r["payload_json"]) if r["payload_json"] else {}
        except Exception:
            payload = {}
        out.append(
            Row(
                memory_object_id=r["id"],
                type=r["type"] or "",
                container_ref=r["container_ref"] or "",
                payload=payload,
            )
        )
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    ap.add_argument("--run-log", type=Path, default=DEFAULT_RUN_LOG)
    ap.add_argument("--no-llm", action="store_true",
                    help="Skip V3 (LLM). Useful when the proxy is unreachable.")
    ap.add_argument("--limit-llm", type=int, default=0,
                    help="Cap LLM calls (0 = no cap). Cached entries don't count.")
    args = ap.parse_args()

    log_lines: list[str] = []

    def log(msg: str) -> None:
        print(msg)
        log_lines.append(msg)

    log(f"# subject_enrichment.enrich run @ {time.strftime('%Y-%m-%d %H:%M:%S')}")
    log(f"db: {args.db}")
    log(f"out: {args.out}")
    log(f"cache: {args.cache_dir}")
    log("")

    rows = _load_active(args.db)
    log(f"loaded {len(rows)} active memories since {SINCE}")
    by_type: dict[str, int] = {}
    for r in rows:
        by_type[r.type] = by_type.get(r.type, 0) + 1
    for t, n in sorted(by_type.items()):
        log(f"  {t}: {n}")

    provider = None
    provider_err: str | None = None
    if not args.no_llm:
        provider, provider_err = _build_provider()
        if provider is None:
            log(f"[warn] LLM provider unavailable, V3 will fall back to V2: {provider_err}")
        else:
            log("LLM provider built ok (hai_anthropic / anthropic--claude-sonnet-latest)")
    else:
        log("--no-llm set — V3 will fall back to V2 for every row")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.cache_dir.mkdir(parents=True, exist_ok=True)

    # Track stats.
    stats = {
        "v1_empty": 0,
        "v2_falls_back_to_v1": 0,
        "v3_from_cache": 0,
        "v3_from_llm": 0,
        "v3_fallback_no_llm": 0,
        "v3_llm_error": 0,
        "errors": [],
    }
    llm_calls = 0
    started = time.time()

    with args.out.open("w", encoding="utf-8") as f:
        for i, r in enumerate(rows, 1):
            try:
                v1 = subject_text_for_payload(r.type, r.payload) or ""
                v2 = deterministic_subject(r.type, r.payload) or ""
                if v1 == "":
                    stats["v1_empty"] += 1
                if v2 == v1:
                    stats["v2_falls_back_to_v1"] += 1

                v3 = ""
                cached = _read_cache(args.cache_dir, r.memory_object_id)
                if cached is not None:
                    v3 = cached
                    stats["v3_from_cache"] += 1
                elif provider is None:
                    v3 = v2  # graceful fallback
                    stats["v3_fallback_no_llm"] += 1
                else:
                    if args.limit_llm and llm_calls >= args.limit_llm:
                        v3 = v2
                        stats["v3_fallback_no_llm"] += 1
                    else:
                        body = _body_text(r.type, r.payload)
                        evidence = _evidence_text(r.type, r.payload)
                        try:
                            phrase = _llm_subject(provider, r.type, body, evidence)
                            v3 = phrase or v2
                            llm_calls += 1
                            stats["v3_from_llm"] += 1
                            _write_cache(
                                args.cache_dir,
                                r.memory_object_id,
                                v3,
                                {"item_type": r.type, "model": "anthropic--claude-sonnet-latest"},
                            )
                            if llm_calls % 50 == 0:
                                elapsed = time.time() - started
                                log(f"  ... {llm_calls} LLM calls "
                                    f"({llm_calls / max(elapsed, 1e-6):.2f}/s)")
                        except Exception as exc:
                            stats["v3_llm_error"] += 1
                            stats["errors"].append(f"{r.memory_object_id}: {type(exc).__name__}: {exc}")
                            v3 = v2

                f.write(
                    json.dumps(
                        {
                            "memory_object_id": r.memory_object_id,
                            "type": r.type,
                            "container_ref": r.container_ref,
                            "subject_v1_fallback": v1,
                            "subject_v2_deterministic": v2,
                            "subject_v3_llm": v3,
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
            except Exception as exc:
                stats["errors"].append(
                    f"{r.memory_object_id}: row-level error: {type(exc).__name__}: {exc}"
                )

    elapsed = time.time() - started
    log("")
    log("## Summary")
    log(f"rows written: {len(rows)}")
    log(f"v1_empty (no fallback subject): {stats['v1_empty']}")
    log(f"v2_falls_back_to_v1: {stats['v2_falls_back_to_v1']}")
    log(f"v3_from_cache: {stats['v3_from_cache']}")
    log(f"v3_from_llm: {stats['v3_from_llm']}")
    log(f"v3_fallback_no_llm: {stats['v3_fallback_no_llm']}")
    log(f"v3_llm_error: {stats['v3_llm_error']}")
    log(f"elapsed: {elapsed:.1f}s")
    if stats["errors"]:
        log("")
        log("### Errors (first 20)")
        for e in stats["errors"][:20]:
            log(f"  - {e}")

    args.run_log.parent.mkdir(parents=True, exist_ok=True)
    # Append to run log so replay can add to it later.
    with args.run_log.open("a", encoding="utf-8") as f:
        f.write("\n".join(log_lines) + "\n\n")
    print(f"\nwrote {args.out}")
    print(f"appended run log to {args.run_log}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
