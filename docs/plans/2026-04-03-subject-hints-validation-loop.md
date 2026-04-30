# Subject Hints Prompt Validation Loop — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a targeted eval loop that scores subject_hint extraction quality against a ground-truth fixture, iterate on the prompt until recall ≥ 0.85 with zero spurious hits, then run the gate-pass regressions to promote the winning variant to default.

**Architecture:** New fixture (`subject_hints_items.jsonl`) with per-item expected/forbidden hint sets feeds a new thin runner (`subject_hints_runner.py`) that scores each extraction against those sets. Prompt variants are registered in `PROMPT_VARIANTS` in `semantic/llm_agent_memory.py` and iterated until acceptance criteria are met. Gate pass runs the existing semantic, routing, and resumption benchmarks with the winning variant.

**Tech stack:** Python 3.12+, `ThreadPoolExecutor` for concurrency, `AppConfig` + `build_semantic_plugins` for plugin initialization (same as `evals/semantic_runner.py`), `_anchor_display_value` from `semantic.agent_conversation_memory_anchors` for hint normalization.

**Spec:** `docs/specs/2026-04-03-subject-hints-prompt-validation-loop-design.md`

---

## File Map

| Action | Path | Purpose |
|---|---|---|
| Create | `evals/semantic/input/subject_hints_items.jsonl` | Ground-truth fixture — 15 items, 7 pattern classes |
| Create | `tests/test_subject_hints_runner.py` | Unit tests for scoring and normalization logic |
| Create | `evals/subject_hints_runner.py` | Thin eval runner with CLI, scoring, output |
| Modify | `semantic/llm_agent_memory.py` | Register `strict_typed_memory_v7_claude_structured_v2` (and further vN) in `PROMPT_VARIANTS` |

---

## Task 1: Create the ground-truth fixture

**File:**
- Create: `evals/semantic/input/subject_hints_items.jsonl`

All items use the library/catalog domain (public-safe). Each item's `metadata` carries `expected_subject_hints` (must all appear) and `forbidden_subject_hints` (none must appear).

- [ ] **Step 1: Write the fixture file**

```jsonl
{"source_type":"chat_message","source_id":"sh-001","content_type":"text/plain","role":"user","content":"recent importer work has been slow, I think there is a bottleneck in the batch processor.","container_ref":"workspace:library-alpha","thread_ref":"thread-1","occurred_at":"2026-04-03T10:00:00Z","metadata":{"expected_subject_hints":[{"kind":"component","value":"importer"}],"forbidden_subject_hints":[]}}
{"source_type":"chat_message","source_id":"sh-002","content_type":"text/plain","role":"user","content":"spent this morning on reservation service work, the timeout logic needs rethinking.","container_ref":"workspace:library-alpha","thread_ref":"thread-1","occurred_at":"2026-04-03T10:01:00Z","metadata":{"expected_subject_hints":[{"kind":"component","value":"reservation service"}],"forbidden_subject_hints":[]}}
{"source_type":"chat_message","source_id":"sh-003","content_type":"text/plain","role":"user","content":"been working on the catalog importer for the past two days.","container_ref":"workspace:library-alpha","thread_ref":"thread-1","occurred_at":"2026-04-03T10:02:00Z","metadata":{"expected_subject_hints":[{"kind":"component","value":"catalog importer"}],"forbidden_subject_hints":[]}}
{"source_type":"chat_message","source_id":"sh-004","content_type":"text/plain","role":"user","content":"working on title search filtering all afternoon, almost done.","container_ref":"workspace:library-alpha","thread_ref":"thread-1","occurred_at":"2026-04-03T10:03:00Z","metadata":{"expected_subject_hints":[{"kind":"component","value":"title search filtering"}],"forbidden_subject_hints":[]}}
{"source_type":"chat_message","source_id":"sh-005","content_type":"text/plain","role":"user","content":"fixed a bug in the reservation service that was causing duplicate holds.","container_ref":"workspace:library-alpha","thread_ref":"thread-1","occurred_at":"2026-04-03T10:04:00Z","metadata":{"expected_subject_hints":[{"kind":"component","value":"reservation service"}],"forbidden_subject_hints":[]}}
{"source_type":"chat_message","source_id":"sh-006","content_type":"text/plain","role":"user","content":"there is a memory leak in the catalog importer when processing large batches.","container_ref":"workspace:library-alpha","thread_ref":"thread-1","occurred_at":"2026-04-03T10:05:00Z","metadata":{"expected_subject_hints":[{"kind":"component","value":"catalog importer"}],"forbidden_subject_hints":[]}}
{"source_type":"chat_message","source_id":"sh-007","content_type":"text/plain","role":"user","content":"catalog sync's delay has been increasing since Tuesday's deploy.","container_ref":"workspace:library-alpha","thread_ref":"thread-1","occurred_at":"2026-04-03T10:06:00Z","metadata":{"expected_subject_hints":[{"kind":"component","value":"catalog sync"}],"forbidden_subject_hints":[]}}
{"source_type":"chat_message","source_id":"sh-008","content_type":"text/plain","role":"user","content":"the importer's queue is backing up again during peak hours.","container_ref":"workspace:library-alpha","thread_ref":"thread-1","occurred_at":"2026-04-03T10:07:00Z","metadata":{"expected_subject_hints":[{"kind":"component","value":"importer"}],"forbidden_subject_hints":[]}}
{"source_type":"chat_message","source_id":"sh-009","content_type":"text/plain","role":"user","content":"nothing new on the importer side, still waiting for the vendor response.","container_ref":"workspace:library-alpha","thread_ref":"thread-1","occurred_at":"2026-04-03T10:08:00Z","metadata":{"expected_subject_hints":[],"forbidden_subject_hints":[{"kind":"component","value":"importer"}]}}
{"source_type":"chat_message","source_id":"sh-010","content_type":"text/plain","role":"user","content":"not sure about the catalog sync situation, might look into it later.","container_ref":"workspace:library-alpha","thread_ref":"thread-1","occurred_at":"2026-04-03T10:09:00Z","metadata":{"expected_subject_hints":[],"forbidden_subject_hints":[{"kind":"component","value":"catalog sync"}]}}
{"source_type":"chat_message","source_id":"sh-011","content_type":"text/plain","role":"user","content":"I haven't really looked at the reservation service side of things recently.","container_ref":"workspace:library-alpha","thread_ref":"thread-1","occurred_at":"2026-04-03T10:10:00Z","metadata":{"expected_subject_hints":[],"forbidden_subject_hints":[{"kind":"component","value":"reservation service"}]}}
{"source_type":"chat_message","source_id":"sh-012","content_type":"text/plain","role":"user","content":"recent LIB-4521 title search filtering work has been in patron portal, almost wrapped up.","container_ref":"workspace:library-alpha","thread_ref":"thread-1","occurred_at":"2026-04-03T10:11:00Z","metadata":{"expected_subject_hints":[{"kind":"workstream","value":"LIB-4521"},{"kind":"component","value":"title search filtering"},{"kind":"surface","value":"patron portal"}],"forbidden_subject_hints":[]}}
{"source_type":"chat_message","source_id":"sh-013","content_type":"text/plain","role":"user","content":"LIB-4521 is about catalog sync in the patron portal, still in progress.","container_ref":"workspace:library-alpha","thread_ref":"thread-1","occurred_at":"2026-04-03T10:12:00Z","metadata":{"expected_subject_hints":[{"kind":"workstream","value":"LIB-4521"},{"kind":"component","value":"catalog sync"},{"kind":"surface","value":"patron portal"}],"forbidden_subject_hints":[]}}
{"source_type":"chat_message","source_id":"sh-014","content_type":"text/plain","role":"user","content":"catalog sync started failing this morning after the config push.","container_ref":"workspace:library-alpha","thread_ref":"thread-1","occurred_at":"2026-04-03T10:13:00Z","metadata":{"expected_subject_hints":[{"kind":"component","value":"catalog sync"}],"forbidden_subject_hints":[]}}
{"source_type":"chat_message","source_id":"sh-015","content_type":"text/plain","role":"user","content":"the catalog importer is throwing connection errors on every third batch.","container_ref":"workspace:library-alpha","thread_ref":"thread-1","occurred_at":"2026-04-03T10:14:00Z","metadata":{"expected_subject_hints":[{"kind":"component","value":"catalog importer"}],"forbidden_subject_hints":[]}}
```

- [ ] **Step 2: Verify the file has exactly 15 lines**

```bash
wc -l evals/semantic/input/subject_hints_items.jsonl
```
Expected: `15 evals/semantic/input/subject_hints_items.jsonl`

- [ ] **Step 3: Verify each line parses as valid JSON**

```bash
python -c "
import json, pathlib
lines = pathlib.Path('evals/semantic/input/subject_hints_items.jsonl').read_text().splitlines()
for i, line in enumerate(lines, 1):
    obj = json.loads(line)
    meta = obj['metadata']
    assert 'expected_subject_hints' in meta, f'line {i} missing expected_subject_hints'
    assert 'forbidden_subject_hints' in meta, f'line {i} missing forbidden_subject_hints'
print(f'All {len(lines)} items valid')
"
```
Expected: `All 15 items valid`

- [ ] **Step 4: Commit**

```bash
git add evals/semantic/input/subject_hints_items.jsonl
git commit -m "eval: add subject_hints ground-truth fixture (15 items, 7 pattern classes)"
```

---

## Task 2: Write scoring unit tests

**Files:**
- Create: `tests/test_subject_hints_runner.py`

These tests exercise the scoring and normalization logic before the runner exists. Run them first — they must fail, then pass once Task 3 is complete.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_subject_hints_runner.py
from __future__ import annotations

import pytest
from core.models import MemorySubjectAnchor


# ---------------------------------------------------------------------------
# _normalize_hint
# ---------------------------------------------------------------------------

def test_normalize_hint_lowercases():
    from evals.subject_hints_runner import _normalize_hint
    kind, value = _normalize_hint("Component", "Catalog Sync")
    assert kind == "component"
    assert value == "catalog sync"


def test_normalize_hint_strips_leading_noise():
    from evals.subject_hints_runner import _normalize_hint
    # "the importer" -> noise token "the" stripped -> "importer"
    _, value = _normalize_hint("component", "the importer")
    assert value == "importer"


def test_normalize_hint_strips_trailing_noise():
    from evals.subject_hints_runner import _normalize_hint
    # "importer here" -> trailing "here" stripped -> "importer"
    _, value = _normalize_hint("component", "importer here")
    assert value == "importer"


# ---------------------------------------------------------------------------
# _score_item
# ---------------------------------------------------------------------------

def _make_anchor(kind: str, value: str) -> MemorySubjectAnchor:
    return MemorySubjectAnchor(kind=kind, value=value)


def test_score_item_all_hits():
    from evals.subject_hints_runner import _score_item
    extracted = [_make_anchor("component", "catalog sync")]
    expected = [{"kind": "component", "value": "catalog sync"}]
    hits, misses, spurious = _score_item(extracted, expected, [])
    assert len(hits) == 1
    assert len(misses) == 0
    assert len(spurious) == 0


def test_score_item_miss():
    from evals.subject_hints_runner import _score_item
    extracted = []
    expected = [{"kind": "component", "value": "importer"}]
    hits, misses, spurious = _score_item(extracted, expected, [])
    assert len(hits) == 0
    assert len(misses) == 1
    assert len(spurious) == 0


def test_score_item_spurious():
    from evals.subject_hints_runner import _score_item
    extracted = [_make_anchor("component", "importer")]
    expected = []
    forbidden = [{"kind": "component", "value": "importer"}]
    hits, misses, spurious = _score_item(extracted, expected, forbidden)
    assert len(hits) == 0
    assert len(misses) == 0
    assert len(spurious) == 1


def test_score_item_case_insensitive_match():
    from evals.subject_hints_runner import _score_item
    extracted = [_make_anchor("component", "Catalog Sync")]
    expected = [{"kind": "component", "value": "catalog sync"}]
    hits, misses, spurious = _score_item(extracted, expected, [])
    assert len(hits) == 1
    assert len(misses) == 0


def test_score_item_multi_anchor():
    from evals.subject_hints_runner import _score_item
    extracted = [
        _make_anchor("workstream", "LIB-4521"),
        _make_anchor("component", "title search filtering"),
        _make_anchor("surface", "patron portal"),
    ]
    expected = [
        {"kind": "workstream", "value": "LIB-4521"},
        {"kind": "component", "value": "title search filtering"},
        {"kind": "surface", "value": "patron portal"},
    ]
    hits, misses, spurious = _score_item(extracted, expected, [])
    assert len(hits) == 3
    assert len(misses) == 0
    assert len(spurious) == 0


def test_score_item_spurious_does_not_double_count_hit():
    from evals.subject_hints_runner import _score_item
    # an expected hint that is also in forbidden should be in hits (correct extraction)
    # and not spurious — forbidden is only checked against extracted, not against expected
    extracted = [_make_anchor("component", "importer")]
    expected = [{"kind": "component", "value": "importer"}]
    forbidden = [{"kind": "component", "value": "importer"}]
    hits, misses, spurious = _score_item(extracted, expected, forbidden)
    # hits: importer is in required ∩ extracted
    assert len(hits) == 1
    # spurious: importer is in extracted ∩ forbidden — the spec definition includes this
    assert len(spurious) == 1


# ---------------------------------------------------------------------------
# _aggregate_variant
# ---------------------------------------------------------------------------

def test_aggregate_variant_recall():
    from evals.subject_hints_runner import _aggregate_variant
    item_results = [
        {"hits_count": 2, "required_count": 2, "spurious_count": 0},
        {"hits_count": 1, "required_count": 2, "spurious_count": 0},
    ]
    summary = _aggregate_variant(item_results)
    assert summary["recall"] == pytest.approx(3 / 4)
    assert summary["spurious_count"] == 0
    assert summary["perfect_items"] == 1
    assert summary["items_total"] == 2


def test_aggregate_variant_all_perfect():
    from evals.subject_hints_runner import _aggregate_variant
    item_results = [
        {"hits_count": 1, "required_count": 1, "spurious_count": 0},
        {"hits_count": 3, "required_count": 3, "spurious_count": 0},
    ]
    summary = _aggregate_variant(item_results)
    assert summary["recall"] == 1.0
    assert summary["perfect_items"] == 2


def test_aggregate_variant_zero_required_no_division_error():
    from evals.subject_hints_runner import _aggregate_variant
    item_results = [
        {"hits_count": 0, "required_count": 0, "spurious_count": 0},
    ]
    summary = _aggregate_variant(item_results)
    assert summary["recall"] == 0.0
```

- [ ] **Step 2: Run tests to confirm they fail with ImportError**

```bash
python -m pytest tests/test_subject_hints_runner.py -x -q 2>&1 | head -20
```
Expected: all tests fail with `ImportError: cannot import name '_normalize_hint' from 'evals.subject_hints_runner'` (or `ModuleNotFoundError`).

---

## Task 3: Write the runner

**Files:**
- Create: `evals/subject_hints_runner.py`

Closely mirrors `evals/semantic_runner.py`. Does not modify it.

- [ ] **Step 1: Write the runner**

```python
# evals/subject_hints_runner.py
from __future__ import annotations

import argparse
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import AppConfig
from app.dependencies import build_semantic_plugins
from core.contracts import build_source_item
from core.models import MemorySubjectAnchor
from semantic.agent_conversation_memory_anchors import _anchor_display_value
from semantic.llm_agent_memory import LLMAgentMemoryPlugin

DEFAULT_INPUT_FILE = Path("evals/semantic/input/subject_hints_items.jsonl")
DEFAULT_OUTPUT_DIR = Path("evals/subject_hints/output")
SANITIZE_PATTERN = re.compile(r"[^a-z0-9]+")


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

def _normalize_hint(kind: str, value: str) -> tuple[str, str]:
    """Return (kind, display_value) normalized for comparison.

    Uses _anchor_display_value semantics: lowercase via normalize_for_index,
    leading/trailing noise tokens stripped, singular map applied.
    """
    return kind.strip().lower(), _anchor_display_value(value)


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def _score_item(
    extracted: list[MemorySubjectAnchor],
    expected: list[dict[str, str]],
    forbidden: list[dict[str, str]],
) -> tuple[set[tuple[str, str]], set[tuple[str, str]], set[tuple[str, str]]]:
    """Return (hits, misses, spurious) as normalized (kind, value) sets.

    hits     = required ∩ extracted   (correctly extracted)
    misses   = required − extracted   (under-extraction)
    spurious = extracted ∩ forbidden  (over-extraction)
    """
    extracted_norm = {_normalize_hint(h.kind, h.value) for h in extracted}
    required_norm = {_normalize_hint(e["kind"], e["value"]) for e in expected}
    forbidden_norm = {_normalize_hint(f["kind"], f["value"]) for f in forbidden}
    hits = required_norm & extracted_norm
    misses = required_norm - extracted_norm
    spurious = extracted_norm & forbidden_norm
    return hits, misses, spurious


def _aggregate_variant(item_results: list[dict[str, Any]]) -> dict[str, Any]:
    """Roll up per-item scores into a per-variant summary."""
    total_required = 0
    total_hits = 0
    total_spurious = 0
    perfect = 0
    for r in item_results:
        total_hits += r["hits_count"]
        total_required += r["required_count"]
        total_spurious += r["spurious_count"]
        if r["hits_count"] == r["required_count"] and r["spurious_count"] == 0:
            perfect += 1
    return {
        "recall": total_hits / total_required if total_required > 0 else 0.0,
        "spurious_count": total_spurious,
        "perfect_items": perfect,
        "items_total": len(item_results),
        "total_hits": total_hits,
        "total_required": total_required,
    }


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------

def _evaluate_one(
    *,
    source_item: Any,
    variant: str,
    plugin: LLMAgentMemoryPlugin,
) -> dict[str, Any]:
    variant_plugin = plugin.with_prompt_variant(variant)
    expected = list(source_item.metadata.get("expected_subject_hints") or [])
    forbidden = list(source_item.metadata.get("forbidden_subject_hints") or [])
    payload: dict[str, Any] = {
        "source_id": source_item.source_id,
        "prompt_variant": variant,
        "status": "ok",
        "expected_subject_hints": expected,
        "forbidden_subject_hints": forbidden,
    }
    try:
        trace = variant_plugin.analyze_item(source_item)
        extracted: list[MemorySubjectAnchor] = list(trace.extraction.subject_hints or [])
        hits, misses, spurious = _score_item(extracted, expected, forbidden)
        payload["extracted_subject_hints"] = [{"kind": h.kind, "value": h.value} for h in extracted]
        payload["hits"] = [list(h) for h in hits]
        payload["misses"] = [list(m) for m in misses]
        payload["spurious"] = [list(s) for s in spurious]
        payload["hits_count"] = len(hits)
        payload["misses_count"] = len(misses)
        payload["required_count"] = len(expected)
        payload["spurious_count"] = len(spurious)
    except Exception as exc:
        payload["status"] = "error"
        payload["error"] = {"type": type(exc).__name__, "message": str(exc)}
        payload["hits_count"] = 0
        payload["misses_count"] = 0
        payload["required_count"] = len(expected)
        payload["spurious_count"] = 0
    return payload


def _run(
    *,
    input_file: Path,
    output_root: Path,
    plugin: LLMAgentMemoryPlugin,
    prompt_variants: list[str],
    workers: int,
    run_name: str | None,
) -> Path:
    if not input_file.exists():
        raise FileNotFoundError(f"Input file not found: {input_file}")

    # Validate all variant names before any LLM calls.
    for variant in prompt_variants:
        plugin.with_prompt_variant(variant)  # raises ValueError for unknown names

    raw_records = [
        json.loads(line)
        for line in input_file.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    items = [
        build_source_item(
            source_type=r["source_type"],
            source_id=r["source_id"],
            content_type=r["content_type"],
            content=r["content"],
            metadata=r.get("metadata"),
            occurred_at=_parse_dt(r.get("occurred_at")),
            role=r.get("role"),
            container_ref=r.get("container_ref"),
            thread_ref=r.get("thread_ref"),
        )
        for r in raw_records
    ]

    run_id = run_name or _build_run_id()
    run_dir = output_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    tasks = [(item, variant) for item in items for variant in prompt_variants]

    if workers == 1:
        results = [_evaluate_one(source_item=item, variant=v, plugin=plugin) for item, v in tasks]
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(_evaluate_one, source_item=item, variant=v, plugin=plugin) for item, v in tasks]
            results = [f.result() for f in as_completed(futures)]

    results.sort(key=lambda r: (r["source_id"], prompt_variants.index(r["prompt_variant"])))

    (run_dir / "results.jsonl").write_text(
        "\n".join(json.dumps(r) for r in results) + "\n",
        encoding="utf-8",
    )

    per_variant: dict[str, list[dict[str, Any]]] = {v: [] for v in prompt_variants}
    for r in results:
        if r["status"] == "ok":
            per_variant[r["prompt_variant"]].append(r)

    summaries = {v: _aggregate_variant(per_variant[v]) for v in prompt_variants}

    summary = {
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "input_file": str(input_file),
        "prompt_variants": prompt_variants,
        "per_variant": summaries,
    }
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    # Print console summary — one row per variant.
    print(f"\n{'variant':<55} {'recall':>6} {'spurious':>9} {'perfect':>8}")
    print("-" * 80)
    for variant in prompt_variants:
        s = summaries[variant]
        print(f"{variant:<55} {s['recall']:>6.2f} {s['spurious_count']:>9} {s['perfect_items']:>8}/{s['items_total']}")
    print(f"\nFull results: {run_dir / 'results.jsonl'}")

    return run_dir


def _build_run_id() -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"subject-hints__{ts}"


def _parse_dt(value: Any):
    if value is None:
        return None
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _slugify(value: str) -> str:
    return SANITIZE_PATTERN.sub("-", value.strip().lower()).strip("-") or "unknown"


def main() -> int:
    parser = argparse.ArgumentParser(description="Score subject_hint extraction against a ground-truth fixture.")
    parser.add_argument("--prompt-variants", default=None, help="Comma-separated variant names. Defaults to the plugin default.")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--cache-dir", default=None, help="LLM response cache directory.")
    parser.add_argument("--run-name", default=None)
    parser.add_argument("--input-file", type=Path, default=DEFAULT_INPUT_FILE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()

    config = AppConfig.from_env()
    if args.cache_dir:
        # If the provider supports a cache dir, it is passed via env or config.
        # This flag is a no-op for providers that don't support caching — kept for
        # CLI parity with semantic_runner.
        import os
        os.environ.setdefault("PALLIUM_LLM_CACHE_DIR", args.cache_dir)

    plugins = build_semantic_plugins(config)
    plugin = plugins.get("llm_agent_memory")
    if not isinstance(plugin, LLMAgentMemoryPlugin):
        raise ValueError("llm_agent_memory plugin not found or wrong type")

    prompt_variants = (
        [v.strip() for v in args.prompt_variants.split(",") if v.strip()]
        if args.prompt_variants
        else [plugin.prompt_variant]
    )

    _run(
        input_file=args.input_file,
        output_root=args.output_dir,
        plugin=plugin,
        prompt_variants=prompt_variants,
        workers=args.workers,
        run_name=args.run_name,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Run the unit tests — they should now pass**

```bash
python -m pytest tests/test_subject_hints_runner.py -x -q
```
Expected: all tests pass.

- [ ] **Step 3: Smoke-test the runner CLI (dry import)**

```bash
python -c "from evals.subject_hints_runner import _normalize_hint, _score_item, _aggregate_variant; print('import ok')"
```
Expected: `import ok`

- [ ] **Step 4: Commit**

```bash
git add tests/test_subject_hints_runner.py evals/subject_hints_runner.py
git commit -m "eval: add subject_hints runner with scoring logic and unit tests"
```

---

## Task 4: Register the initial candidate variant

**Files:**
- Modify: `semantic/llm_agent_memory.py` — add new entry to `PROMPT_VARIANTS` dict

The active variant is `strict_typed_memory_v7_claude_structured`. Its subject_hints rule (line ~106) reads:

```
- subject_hints: explicit workstream|component|surface only. Return [] if not safely explicit.
```

The candidate v2 expands the undefined word "explicit" to cover the four syntactic patterns that are currently under-extracted. The conservative return-[] default is preserved for hedged, peripheral, and negated references.

- [ ] **Step 1: Add `strict_typed_memory_v7_claude_structured_v2` to PROMPT_VARIANTS**

In `semantic/llm_agent_memory.py`, locate the `PROMPT_VARIANTS` dict. Add this entry **after** `strict_typed_memory_v7_claude_structured` (the entry ends at approximately line 114 with the closing `""",`). The new entry differs only in the `subject_hints` rule and adds one worked example.

The new `subject_hints` rule replaces:
```
- subject_hints: explicit workstream|component|surface only. Return [] if not safely explicit.
```
with:
```
- subject_hints: extract named workstream|component|surface when the source names it as the subject of work. A name is explicit when: it appears as a noun modifier ("recent importer work" → component=importer), the source uses "work on X" / "working on X" phrasing, it identifies a location or locus in a prepositional phrase ("bug in the reservation service" → component=reservation service), or it appears as a possessive subject ("catalog sync's delay" → component=catalog sync). Return [] for negated or peripheral references ("nothing new on the X side", "not sure about X") and for casual mentions with no work content. Worked example: "recent importer work has been slow" → [{kind: "component", value: "importer"}].
```

Full new entry to add after the closing `""",` of `strict_typed_memory_v7_claude_structured`:

```python
    "strict_typed_memory_v7_claude_structured_v2": """You extract reusable typed memory and work-state signals from one technical source item. Return exactly one JSON object and no extra prose.

## Typed Memory Classification

Only promote to typed memory when the source contains an explicit proof phrase:
- decision: requires committed-choice language ("Decision:", "we decided", "we chose", "chosen approach", "we will use").
- investigation_outcome: requires resolved-finding language ("Root cause:", "Investigation found", "Analysis found", "Findings:", "Outcome:", "We found that", "Verdict:", "Conclusion:", "Investigation concluded", "The conclusion is").
- interest: the user (not the assistant) identifies a specific named subject as worth future attention but does not commit to a concrete action or timeline. Fill interest_text with the subject. No proof phrase needed. Do NOT classify as interest: assistant responses, follow-up questions without a named subject, backward-looking recall, or restatements of prior content.
- otherwise candidate_type = null.
- A non-null type requires the exact proof phrase quoted in the matching evidence field.
- Fill only decision fields for decision, only investigation fields for investigation_outcome.

REJECT as null: needs, proposals, preferences, recommendations, symptoms, risks, monitoring notes, status updates, and unresolved discussion.

## Work-State Signals

Populate only when the source explicitly states them:
- next_step_text: a concrete future action. Clarifying questions are NOT next steps.
- blocker_text: active impediment or failed attempt.
- progress_text: substantive completed or partial work for later resumption. Not boilerplate completion language.
- key_finding_text: durable conclusion or verdict. Not monitoring chatter.
- constraint_text: a definitive operational constraint — the speaker commits to a requirement, prohibition, or hard rule. Hedged or tentative language ("I think", "maybe", "probably", "leaning towards", "not sure") is not a constraint.
- is_low_value_meta: true only for non-durable orchestration chatter: no-op completion/status messages, greeting/pleasantry chatter ("hello", "thanks", "good morning"), heartbeat/monitoring noise ("still alive", "healthcheck"), and generic capability boilerplate ("I can help with...", "capabilities:"). When true, all signal fields must be null/[].
- subject_hints: extract named workstream|component|surface when the source names it as the subject of work. A name is explicit when: it appears as a noun modifier ("recent importer work" → component=importer), the source uses "work on X" / "working on X" phrasing, it identifies a location or locus in a prepositional phrase ("bug in the reservation service" → component=reservation service), or it appears as a possessive subject ("catalog sync's delay" → component=catalog sync). Return [] for negated or peripheral references ("nothing new on the X side", "not sure about X") and for casual mentions with no work content. Worked example: "recent importer work has been slow" → [{kind: "component", value: "importer"}].

Prefer null or [] over weak, speculative, or inferred values.

## Examples
- "Verdict: transaction-transformer had the most significant recent changes." -> investigation_outcome, key_finding_text set.
- "Task complete. No message needed." -> null, is_low_value_meta true, all signals null.
- "Hello, good morning!" -> null, is_low_value_meta true, all signals null.
- "I can lower concurrency or bump memory, but I need to confirm which worker first." -> null, all signals null (clarifying question, not actionable state).""",
```

- [ ] **Step 2: Verify the new variant is registered**

```bash
python -c "
from semantic.llm_agent_memory import PROMPT_VARIANTS
assert 'strict_typed_memory_v7_claude_structured_v2' in PROMPT_VARIANTS, 'v2 not found'
print('v2 registered, total variants:', len(PROMPT_VARIANTS))
"
```
Expected: `v2 registered, total variants: <N>` (no assertion error).

- [ ] **Step 3: Verify the runner validates variant names (unregistered name fails fast)**

```bash
python -c "
from app.config import AppConfig
from app.dependencies import build_semantic_plugins
from semantic.llm_agent_memory import LLMAgentMemoryPlugin
config = AppConfig.from_env()
plugin = build_semantic_plugins(config).get('llm_agent_memory')
try:
    plugin.with_prompt_variant('nonexistent_variant_xyz')
    print('ERROR: should have raised')
except ValueError as e:
    print('Fast-fail OK:', e)
"
```
Expected output contains: `Fast-fail OK:`

- [ ] **Step 4: Commit**

```bash
git add semantic/llm_agent_memory.py
git commit -m "eval: register strict_typed_memory_v7_claude_structured_v2 with expanded subject_hints rule"
```

---

## Task 5: Run the baseline and first candidate

- [ ] **Step 1: Run both variants against the fixture**

```bash
python -m evals.subject_hints_runner \
  --prompt-variants strict_typed_memory_v7_claude_structured,strict_typed_memory_v7_claude_structured_v2 \
  --workers 4 \
  --cache-dir .local/llm-cache \
  --run-name subject-hints-baseline
```

The console prints one summary row per variant:
```
variant                                                  recall  spurious   perfect
--------------------------------------------------------------------------------
strict_typed_memory_v7_claude_structured                  X.XX         X      X/15
strict_typed_memory_v7_claude_structured_v2               X.XX         X      X/15
```

- [ ] **Step 2: Record the numbers**

Open `evals/subject_hints/output/subject-hints-baseline/summary.json` and note for each variant:
- `recall`
- `spurious_count`
- `perfect_items`

The baseline (v7 current) recall is expected to be low (≤ 0.60) for modifier-position patterns. v2 should be higher.

- [ ] **Step 3: Check per-item misses for v2**

```bash
python -c "
import json, pathlib
results = [json.loads(l) for l in pathlib.Path('evals/subject_hints/output/subject-hints-baseline/results.jsonl').read_text().splitlines() if l.strip()]
v2 = [r for r in results if r['prompt_variant'] == 'strict_typed_memory_v7_claude_structured_v2' and r.get('misses_count', 0) > 0]
for r in v2:
    print(r['source_id'], 'misses:', r['misses'])
"
```

Use the miss list to decide what to fix in the next iteration.

---

## Task 6: Iterate until acceptance criteria are met

**Acceptance criteria (from spec):**
- recall ≥ 0.85 across all 15 items
- spurious_count = 0 across all items (not just negative controls)

**Decision tree for iteration:**

| Situation | Action |
|---|---|
| spurious_count > 0 on negative controls (sh-009, sh-010, sh-011) | Strengthen the "return [] for negated/peripheral" clause. Add more negative examples to the prompt. |
| spurious_count > 0 on positive items (unexpected extra hints extracted) | Narrow the worked example; add "only extract the named subject, not the surrounding context" guidance. |
| recall low on adjective-modifier items (sh-001, sh-002) | The modifier-position pattern definition needs a clearer example. |
| recall low on genitive items (sh-007, sh-008) | Add genitive to the worked example in the prompt. |
| recall low on multi-anchor items (sh-012, sh-013) | Verify the workstream kind is covered by examples. |

**For each iteration:**

- [ ] **Step 1: Add the next variant to `PROMPT_VARIANTS` in `semantic/llm_agent_memory.py`**

Name it `strict_typed_memory_v7_claude_structured_v3`, `_v4`, etc. Keep all prior variants — do not overwrite them.

- [ ] **Step 2: Run the runner with the new variant and all prior candidates**

```bash
python -m evals.subject_hints_runner \
  --prompt-variants strict_typed_memory_v7_claude_structured,strict_typed_memory_v7_claude_structured_v2,strict_typed_memory_v7_claude_structured_v3 \
  --workers 4 \
  --cache-dir .local/llm-cache \
  --run-name subject-hints-iter2
```

- [ ] **Step 3: Read the per-item miss/spurious breakdown for the new variant**

```bash
python -c "
import json, pathlib
VARIANT = 'strict_typed_memory_v7_claude_structured_v3'
results = [json.loads(l) for l in pathlib.Path('evals/subject_hints/output/subject-hints-iter2/results.jsonl').read_text().splitlines() if l.strip()]
for r in results:
    if r['prompt_variant'] != VARIANT:
        continue
    status = 'ok' if r.get('hits_count') == r.get('required_count') and r.get('spurious_count') == 0 else 'FAIL'
    print(f\"{status} {r['source_id']:10s}  hits={r.get('hits_count',0)} miss={r.get('misses_count',0)} spurious={r.get('spurious_count',0)}  {r.get('misses',[])}\")
"
```

- [ ] **Step 4: Commit after each iteration**

```bash
git add semantic/llm_agent_memory.py
git commit -m "eval: add v3 prompt variant — <one-line description of the change>"
```

Repeat Task 6 steps until the winning variant achieves: recall ≥ 0.85 AND spurious_count = 0.

---

## Task 7: Gate pass — promote the winning variant

Run the full regressions with the winning variant name. Replace `<WINNER>` with the actual variant name (e.g., `strict_typed_memory_v7_claude_structured_v3`).

**7a: Typed-memory classification regression on items.jsonl**

- [ ] **Step 1: Establish the current baseline**

```bash
python -m evals.semantic_runner \
  --prompt-variants strict_typed_memory_v7_claude_structured \
  --max-concurrency 4 \
  --cache-dir .local/llm-cache \
  --run-name gate-pass-baseline
```

Open `evals/semantic/output/gate-pass-baseline/summary.json`. Record `per_variant.strict_typed_memory_v7_claude_structured.promoted_counts`:
```
decision: <N>
investigation_outcome: <N>
turn_summary: <N>
```

- [ ] **Step 2: Run with the winning variant**

```bash
python -m evals.semantic_runner \
  --prompt-variants <WINNER> \
  --max-concurrency 4 \
  --cache-dir .local/llm-cache \
  --run-name gate-pass-winner
```

Open `evals/semantic/output/gate-pass-winner/summary.json`. Record the same counts.

- [ ] **Step 3: Verify classification is unchanged within ±1 per category**

```bash
python -c "
import json, pathlib
BASE = 'gate-pass-baseline'
WINNER = 'gate-pass-winner'
BASELINE_VARIANT = 'strict_typed_memory_v7_claude_structured'
WINNER_VARIANT = '<WINNER>'  # replace with actual name

base = json.loads(pathlib.Path(f'evals/semantic/output/{BASE}/summary.json').read_text())
win = json.loads(pathlib.Path(f'evals/semantic/output/{WINNER}/summary.json').read_text())
b = base['per_variant'][BASELINE_VARIANT]['promoted_counts']
w = win['per_variant'][WINNER_VARIANT]['promoted_counts']
print('Baseline:', b)
print('Winner:  ', w)
for key in ('decision', 'investigation_outcome', 'turn_summary'):
    diff = abs(b[key] - w[key])
    status = 'OK' if diff <= 1 else 'FAIL'
    print(f'  {key}: {b[key]} -> {w[key]}  diff={diff}  {status}')
"
```
All diffs must be ≤ 1.

**7b: Memory routing benchmark**

- [ ] **Step 4: Run memory routing benchmark with winner**

Before running, temporarily set the active variant to the winner. Edit `pallium.local.toml` to change the `prompt_variant` for `llm_agent_memory` to `<WINNER>`. Then run:

```bash
python -m evals.memory_routing_benchmark
```

Expected: output directory printed. Open the summary JSON, verify `suite_passed` is `true` (or the pass rate matches the current baseline noted in `docs/context/state.md`).

After verifying, revert `pallium.local.toml` if you changed it (you will permanently switch in the final step).

**7c: Work resumption benchmark**

- [ ] **Step 5: Run work resumption benchmark with winner**

With the winner still set in `pallium.local.toml`:

```bash
python -m evals.work_resumption_benchmark
```

Expected: pass rate matches baseline in `docs/context/state.md`.

**7d: Promote the winning variant**

- [ ] **Step 6: Set the winner as the default in `pallium.local.toml`**

Find the `prompt_variant` key under the `llm_agent_memory` package config and change its value to `<WINNER>`.

- [ ] **Step 7: Verify the active variant via the plugin**

```bash
python -c "
from app.config import AppConfig
from app.dependencies import build_semantic_plugins
from semantic.llm_agent_memory import LLMAgentMemoryPlugin
config = AppConfig.from_env()
plugin = build_semantic_plugins(config).get('llm_agent_memory')
print('Active variant:', plugin.prompt_variant)
"
```
Expected: prints `<WINNER>`.

- [ ] **Step 8: Run the full test suite**

```bash
python -m pytest tests/ -x -q
```
Expected: all tests pass.

- [ ] **Step 9: Commit**

```bash
git add pallium.local.toml semantic/llm_agent_memory.py
git commit -m "feat: promote <WINNER> as active extraction variant — subject_hints recall ≥ 0.85, zero spurious"
```
