# Subject Hints Prompt Validation Loop — Design

**Date:** 2026-04-03
**Status:** Approved

## Problem

The active extraction prompt (`strict_typed_memory_v7_claude_structured`) under-extracts
subject hints when a domain name appears as a modifier rather than the grammatical
subject of a statement. "Recent importer work" does not produce `component=importer`
because the prompt defines extraction only as "explicit workstream|component|surface only —
return [] if not safely explicit", with no examples and no definition of "explicit".

Claude follows "explicit proof" instructions literally (see lessons.md, 2026-03-21).
Without a worked example or a concrete boundary definition, it treats modifier-position
domain names as context rather than named subjects.

The fix is a prompt-side change to the subject_hints rule in
`strict_typed_memory_v7_claude_structured`. Because prompt changes carry regression risk
(typed-memory classification must not degrade), changes must go through a validated
iteration loop before landing.

## Approach

A dedicated subject_hints eval runner with a targeted fixture, separate from the
committed `items.jsonl` regression set. Isolation protects the typed-memory baseline
while enabling fast iteration on subject_hint extraction quality.

Two phases:

1. **Tight loop** — run candidate prompt variants against the subject_hints fixture,
   read recall/spurious numbers, adjust, repeat.
2. **Gate pass** — once a variant achieves target recall with no spurious regressions,
   run it against the full `items.jsonl` to verify typed-memory classification is
   unchanged, then run memory routing and work resumption benchmarks.

## Fixture

**File:** `evals/semantic/input/subject_hints_items.jsonl`

Same base schema as `items.jsonl` (compatible with `LLMAgentMemoryPlugin.analyze_item`),
with two additional metadata fields:

```json
{
  "source_type": "chat_message",
  "source_id": "sh-001",
  "content_type": "text/plain",
  "role": "user",
  "content": "recent importer work was mostly LIB-4521 title search filtering in patron portal.",
  "container_ref": "workspace:library-alpha",
  "thread_ref": "thread-1",
  "occurred_at": "2026-04-03T10:00:00Z",
  "metadata": {
    "expected_subject_hints": [
      {"kind": "workstream", "value": "LIB-4521"},
      {"kind": "component", "value": "title search filtering"},
      {"kind": "component", "value": "importer"},
      {"kind": "surface", "value": "patron portal"}
    ],
    "forbidden_subject_hints": []
  }
}
```

`expected_subject_hints` — hints that must all appear in the extraction (recall scored
against this set). `forbidden_subject_hints` — hints that must not appear (each counts
as a spurious extraction).

**Pattern coverage** — the fixture covers the full taxonomy of extraction gap patterns
identified in the investigation:

| Pattern class | Example | Expected |
|---|---|---|
| Adjective-modifier | "recent importer work" | component=importer |
| "Work on X" | "work on authentication" | component=auth |
| Prepositional locus | "fixed a bug in the reservation service" | component=reservation service |
| Genitive | "catalog sync's delay increased" | component=catalog sync |
| Peripheral hedge (negative) | "nothing new on the X side" | [] |
| Multi-anchor | "LIB-4521 title search filtering in patron portal" | workstream + component + surface |
| Explicit subject (positive control) | "catalog sync started failing" | component=catalog sync |

Approximately 15–20 items. Negative controls (items that should produce []) are included
to score the lower bound of the precision-penalty.

**Matching:** normalized via `_anchor_display_value` semantics — case-insensitive,
leading/trailing noise tokens stripped. Kind + normalized value must match exactly.

## Runner

**File:** `evals/subject_hints_runner.py`

Thin runner that reuses `LLMAgentMemoryPlugin` directly.

**CLI:**
```bash
python -m evals.subject_hints_runner \
  --prompt-variants strict_typed_memory_v7_claude_structured,strict_typed_memory_v7_claude_structured_v2 \
  --workers 4 \
  --cache-dir .local/llm-cache \
  --run-name subject-hints-baseline
```

**Internals:**
- Loads `evals/semantic/input/subject_hints_items.jsonl`
- For each item × variant, calls `plugin.with_prompt_variant(variant).analyze_item(item)`
- Extracts `extraction.subject_hints` from the result
- Scores against `expected_subject_hints` / `forbidden_subject_hints` from item metadata
- Writes `evals/subject_hints/output/<run-name>/results.jsonl` + `summary.json`

**Dependencies:** `AppConfig`, `LLMAgentMemoryPlugin`, same provider config as the
semantic runner. No new abstractions.

## Scoring

Per item, per variant:

```
required  = normalized set of (kind, value) from expected_subject_hints
extracted = normalized set of (kind, value) from extraction.subject_hints
forbidden = normalized set of (kind, value) from forbidden_subject_hints

hits      = required ∩ extracted     # correctly extracted
misses    = required − extracted      # under-extraction failures
spurious  = extracted ∩ forbidden    # over-extraction failures
```

Per-variant summary:

| Metric | Definition |
|---|---|
| `recall` | total hits / total required across all items (0.0–1.0) |
| `spurious_count` | total spurious hits across all items |
| `perfect_items` | items where hits == required AND spurious == ∅ |

Console output prints one summary row per variant (recall, spurious, perfect) for fast
iteration reading.

Full per-item breakdown (hits, misses, spurious lists) in `results.jsonl`.

**Asymmetry note:** spurious extraction is treated as a harder failure than under-extraction.
A missing anchor leaves the memory as `unanchored_legacy` — still retrievable as a fallback.
A spurious anchor may cause `anchored_conflicting` classification at query time, which is a
hard exclusion: the memory is never returned, even when it should be. Wrong anchor is worse
than no anchor. This maps directly to the Pallium premise that wrong memory is worse than no
memory. Variants with non-zero spurious_count are deprioritized regardless of recall gains.

## Prompt Change Target

The subject_hints rule in `strict_typed_memory_v7_claude_structured` (active variant,
confirmed in `pallium.local.toml`):

**Before:**
```
subject_hints: explicit workstream|component|surface only. Return [] if not safely explicit.
```

**Direction of change:** add a definition of "explicit" that covers modifier-position
domain names, and add at least one worked example. Exact wording is determined by the
iteration loop — the fixture is the arbiter, not a priori wording choices.

The conservative default (`Return [] if not safely explicit`) must be preserved or
strengthened — the goal is to narrow the undefined word "explicit" to cover clear
syntactic patterns, not to lower the extraction threshold generally. Ambiguous or
hedged references must still produce [].

New variants during iteration are registered in the `PROMPT_VARIANTS` dict in
`semantic/llm_agent_memory.py` under a name like `strict_typed_memory_v7_claude_structured_v2`,
`_v3`, etc. The runner validates variant names against this dict at startup, so
unregistered names fail fast before any LLM calls are made.

## Acceptance Criteria for Gate Pass

Before the winning variant can replace the active default:

1. **Subject hints recall ≥ 0.85** on the targeted fixture with **zero spurious hits
   across all items** (not just negative controls). Spurious extraction creates
   `anchored_conflicting` hard exclusions downstream — wrong anchor is worse than no
   anchor.
2. **Typed-memory classification unchanged** on `items.jsonl`: decision and
   investigation_outcome promotion rates must match the committed baseline within ±1
   item per category.
3. **Memory routing benchmark** passes at current baseline score.
4. **Work resumption benchmark** passes at current baseline score.

## File Layout

```
evals/
  semantic/
    input/
      subject_hints_items.jsonl          # new targeted fixture
  subject_hints/
    output/
      <run-name>/
        results.jsonl
        summary.json
evals/subject_hints_runner.py            # new runner
```

`items.jsonl` and `semantic_runner.py` are not modified.

## What Is Not In Scope

- Routing-side changes (`_classify_memory_candidate_anchor_state`) — addressed
  separately if the prompt fix is insufficient.
- Index-side matched-token propagation (Option C) — deferred to FTS5 migration.
- Changes to variants other than `v7_claude_structured` — other variants are not
  the active path and are not touched.
