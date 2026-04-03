# Simplify Constraint Memory Creation

**Date:** 2026-04-03  
**Status:** Approved  
**Scope:** `semantic/` layer only — no changes to `core/`, `capabilities/`, routing weights, or the query path

---

## Problem

User-stated operational constraints (e.g. "don't try to open jira here — I don't have a local connection") are never promoted to `constraint_memory` objects. They are invisible to future threads.

### Root Cause

Three separate failures conspire:

1. **LLM won't populate `constraint_candidates`** for ambient natural-language constraints. The schema requires `primary_scope_anchor`, which is ambiguous when a user states a general prohibition without a named tool or system as an explicit anchor. The LLM leaves the array empty.

2. **`_append_typed_constraint_memory_objects` gates on `constraint_candidates`** — if the array is empty, it returns immediately. There is no fallback path from `constraint_text`.

3. **`_normalize_constraint_candidates` silently discards all structured fields** (primary_scope_anchor, target_anchor, action_class, polarity, confidence) and reads only `constraint_text` per item, reducing the structured candidate to the same information as the flat `constraint_text` signal. The structure is never used.

### Historical context

The structured `constraint_candidates` path was scaffolding for a "constraint compatibility engine" (~1000 lines) that was deliberately removed in roadmap item `add-language-agnostic-query-signals-and-typed-constraint-state`. The extraction scaffold was left behind, orphaned. The gate it provides now prevents the feature from working at all.

---

## Design

Unify constraint memory creation onto `constraint_text`. Delete the structured path entirely.

### Change 1 — Prompt schema (`semantic/llm_agent_memory.py`)

Remove `constraint_candidates` from all three prompt variant texts (`strict_typed_memory_v7_claude_structured`, `strict_typed_memory_v7_claude_minimal`, `strict_typed_memory_v7_claude_clean`) and from the JSON output schema block.

`constraint_text` stays unchanged. It is already reliably populated by the LLM for natural-language prohibitions.

### Change 2 — Payload normalizer (`semantic/llm_agent_memory.py`)

Delete `_normalize_constraint_candidates()`. Stop reading `constraint_candidates` from the LLM JSON payload in `_parse_extraction_payload`.

### Change 3 — Dataclass cleanup (`semantic/common.py`)

Delete `ConstraintCandidate` dataclass. Remove `constraint_candidates: tuple[ConstraintCandidate, ...]` from `SemanticExtraction`.

### Change 4 — Memory object creation (`semantic/agent_conversation_memory_memory.py`)

Rewrite `_append_typed_constraint_memory_objects` to gate on `extraction.constraint_text` (non-null, non-empty after strip):

- Role guard: user-only (unchanged)
- Visibility guard: skip container/public (unchanged)
- Create one `constraint_memory` object from `constraint_text`
- Append the `supported_by` relation to the source item
- Append the lexical index entry
- No loop — `constraint_text` is a single string

### Change 5 — Dead code removal (`semantic/agent_conversation_memory_constraints.py`)

Delete:
- `CONSTRAINT_HARD_POLARITIES` (only used by dead functions)
- `CONSTRAINT_CONFIDENCES` (only used by `_constraint_confidence_from_candidate`, which is itself dead)
- `_constraint_supersession_identity()` — never called
- `_constraint_compatibility_domain()` — never called
- `_constraint_strength_for_polarity()` — never called
- `_constraint_summary_text()` — never called; also broken (accesses `.polarity` and `.target_anchor` which don't exist on `ConstraintCandidate`)
- `_constraint_confidence_from_candidate()` — never called

**Keep:**
- `CONSTRAINT_ALLOWED_ANCHOR_KINDS` — actively used by `_deserialize_subject_anchor`

**Keep:**
- `CONSTRAINT_MARKERS` — used by `agent_conversation_memory_threads.py`
- `CONSTRAINT_TOOL_MARKERS` — used by `agent_conversation_memory_threads.py`
- All anchor/subject utilities (`_merge_subject_anchors`, `_serialize_subject_anchors`, `SUBJECT_HINT_METADATA_KEY`)
- Schema constants (`CONSTRAINT_MEMORY_TYPE`, `CONSTRAINT_MEMORY_SCHEMA_ID`, `CONSTRAINT_MEMORY_SCHEMA_VERSION`)

---

## Data flow after this change

```
User message: "don't try to open jira here"
  → LLM extraction: constraint_text = "don't try to open jira here"
  → _append_typed_constraint_memory_objects: constraint_text is non-empty, role=user, visibility=private
  → constraint_memory object created
  → routing: work_resumption score 490, broad_recall 430
  → injected in future threads
```

---

## Known gap

No deduplication if the user restates the same constraint across multiple turns. Each restatement creates a new `constraint_memory` object. Routing handles redundancy gracefully — both objects will score identically and the top-k cap limits injection volume. Deduplication is a separate concern (supersession keys), not in scope for this slice.

---

## What this does not change

- Routing weights for `constraint_memory` — unchanged
- Thread-level constraint signal extraction (`_extract_constraint_signal_text`) — unchanged
- `CONSTRAINT_MARKERS` and `CONSTRAINT_TOOL_MARKERS` — preserved
- Role guard and visibility guard semantics — unchanged
- `constraint_text` as a `SemanticExtraction` field — unchanged
- The query path, injection logic, and all other memory types — untouched

---

## Files changed

| File | Change |
|------|--------|
| `semantic/llm_agent_memory.py` | Remove `constraint_candidates` from prompt texts and output schema; delete `_normalize_constraint_candidates`; stop reading `constraint_candidates` from payload |
| `semantic/common.py` | Delete `ConstraintCandidate`; remove `constraint_candidates` from `SemanticExtraction` |
| `semantic/agent_conversation_memory_memory.py` | Rewrite `_append_typed_constraint_memory_objects` to gate on `constraint_text` |
| `semantic/agent_conversation_memory_constraints.py` | Delete dead constants and five dead functions |
| `tests/tiered_memory_stub_providers.py` | Remove `constraint_candidates` key from the definitive-statement stub response (`constraint_text` is already populated there) |
