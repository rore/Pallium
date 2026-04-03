# Simplify Constraint Memory Creation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix constraint_memory promotion so that natural-language user constraints ("don't try to open jira here") are reliably stored and injected in future threads.

**Architecture:** Delete the unused structured `constraint_candidates` path entirely and unify creation onto the flat `constraint_text` signal that the LLM already populates reliably. Four production files change and one test stub loses a stale key.

**Spec:** `docs/designs/009-simplify-constraint-memory-design.md`

**Tech Stack:** Python 3.12, dataclasses, pytest

---

## File Map

| File | Change |
|------|--------|
| `semantic/llm_agent_memory.py` | Remove `constraint_candidates` from 3 prompt strings + JSON schema block; delete `_normalize_constraint_candidates`; stop reading `constraint_candidates` in `_parse_extraction_payload` |
| `semantic/common.py` | Delete `ConstraintCandidate` dataclass; remove `constraint_candidates` field from `SemanticExtraction` |
| `semantic/agent_conversation_memory_constraints.py` | Delete `CONSTRAINT_CONFIDENCES`, `CONSTRAINT_HARD_POLARITIES`, and 5 dead functions |
| `semantic/agent_conversation_memory_memory.py` | Rewrite `_append_typed_constraint_memory_objects` to gate on `constraint_text` |
| `tests/tiered_memory_stub_providers.py` | Remove `constraint_candidates` key from definitive-statement stub response (line 395) |

---

## Task 1: Fix the stub — remove `constraint_candidates` from definitive-statement response

The stub already populates `constraint_text`; we just need to drop the now-removed key before we change production code. This keeps the test suite runnable at every step.

**Files:**
- Modify: `tests/tiered_memory_stub_providers.py:394-395`

- [ ] **Step 1: Run constraint guard tests before touching anything — establish baseline**

```bash
python -m pytest tests/test_constraint_tentative_guard.py -x -q
```

Expected: all tests pass (the stub currently populates `constraint_candidates` which flows through to memory creation — tests pass today).

- [ ] **Step 2: Remove `constraint_candidates` from the definitive-statement stub response**

In `tests/tiered_memory_stub_providers.py`, find the block that starts with `'constraint_text': content_line,` and delete the next line. The result should look like:

```python
        return {
            'summary': 'Constraint recorded in the conversation.',
            'candidate_type': None,
            'decision_text': None,
            'decision_evidence_text': None,
            'investigation_text': None,
            'investigation_evidence_text': None,
            'rationale_text': None,
            'is_low_value_meta': False,
            'constraint_text': content_line,
            'next_step_text': None,
            'blocker_text': None,
            'progress_text': None,
            'key_finding_text': None,
        }
```

(The line `'constraint_candidates': [{'constraint_text': content_line}],` is deleted.)

- [ ] **Step 3: Run constraint guard tests — expect ALL definitive-statement tests to fail now**

```bash
python -m pytest tests/test_constraint_tentative_guard.py -x -q
```

Expected: the six `TestDefinitiveStatementsProduceConstraintMemory` tests fail with `assert len(constraints) == 1` → `AssertionError: 0 != 1`. This is correct — we have broken the stub's path to confirm the tests are actually sensitive to the data.

- [ ] **Step 4: Commit stub change (tests intentionally red)**

```bash
git add tests/tiered_memory_stub_providers.py
git commit -m "test: remove stale constraint_candidates key from stub response"
```

---

## Task 2: Delete `ConstraintCandidate` and `constraint_candidates` from `SemanticExtraction`

**Files:**
- Modify: `semantic/common.py:53-76`

- [ ] **Step 1: Delete `ConstraintCandidate` dataclass and `constraint_candidates` field**

In `semantic/common.py`, delete lines 53–56 (the `ConstraintCandidate` dataclass):

```python
@dataclass(frozen=True)
class ConstraintCandidate:
    constraint_text: str
```

And delete line 76 from `SemanticExtraction`:

```python
    constraint_candidates: tuple[ConstraintCandidate, ...] = field(default_factory=tuple)
```

The final `SemanticExtraction` dataclass should look like:

```python
@dataclass(frozen=True)
class SemanticExtraction:
    summary: str
    candidate_type: str | None = None
    decision_text: str | None = None
    decision_evidence_text: str | None = None
    investigation_text: str | None = None
    investigation_evidence_text: str | None = None
    rationale_text: str | None = None
    interest_text: str | None = None
    matched_phrase: str | None = None
    is_low_value_meta: bool = False
    constraint_text: str | None = None
    next_step_text: str | None = None
    blocker_text: str | None = None
    progress_text: str | None = None
    key_finding_text: str | None = None
    subject_hints: tuple[MemorySubjectAnchor, ...] = field(default_factory=tuple)
```

- [ ] **Step 2: Run tests to confirm only expected failures**

```bash
python -m pytest tests/ -x -q 2>&1 | head -40
```

Expected: fails on import errors in `semantic/llm_agent_memory.py` (still imports `ConstraintCandidate`) and `semantic/agent_conversation_memory_constraints.py` (still imports `ConstraintCandidate`). No surprises beyond those.

- [ ] **Step 3: Commit**

```bash
git add semantic/common.py
git commit -m "refactor: remove ConstraintCandidate dataclass and constraint_candidates field from SemanticExtraction"
```

---

## Task 3: Remove dead code from `agent_conversation_memory_constraints.py`

**Files:**
- Modify: `semantic/agent_conversation_memory_constraints.py`

- [ ] **Step 1: Remove the `ConstraintCandidate` import**

At the top of `semantic/agent_conversation_memory_constraints.py`, line 6 currently reads:

```python
from semantic.common import ConstraintCandidate, normalize_for_index
```

Change it to:

```python
from semantic.common import normalize_for_index
```

- [ ] **Step 2: Delete `CONSTRAINT_CONFIDENCES` and `CONSTRAINT_HARD_POLARITIES`**

Delete lines 18–20:

```python
CONSTRAINT_CONFIDENCES = {"high", "medium", "low", "unknown"}

CONSTRAINT_HARD_POLARITIES = {"prohibit", "require"}
```

- [ ] **Step 3: Delete the five dead functions**

Delete these five functions entirely (lines 119–175 in the original file; exact range shifts after earlier edits — search by name):

- `_constraint_supersession_identity`
- `_constraint_compatibility_domain`
- `_constraint_strength_for_polarity`
- `_constraint_confidence_from_candidate`
- `_constraint_summary_text`

The functions begin at their `def` line and run to just before the next `def` or end of file. After deletion, the last function in the file should be `_subject_anchors_from_memory_objects`.

- [ ] **Step 4: Run tests to confirm import error in `llm_agent_memory.py` is the only remaining failure**

```bash
python -m pytest tests/ -x -q 2>&1 | head -20
```

Expected: `ImportError` in `semantic/llm_agent_memory.py` (still imports `ConstraintCandidate`). No other failures.

- [ ] **Step 5: Commit**

```bash
git add semantic/agent_conversation_memory_constraints.py
git commit -m "refactor: delete dead constraint constants and functions from agent_conversation_memory_constraints"
```

---

## Task 4: Update `llm_agent_memory.py` — remove `constraint_candidates` from prompts and parser

**Files:**
- Modify: `semantic/llm_agent_memory.py`

This task has three sub-parts: fix the import, clean the prompts, clean the parser.

- [ ] **Step 1: Fix the import — remove `ConstraintCandidate`**

At the top of `semantic/llm_agent_memory.py`, line 11 currently reads:

```python
from semantic.common import ConstraintCandidate, SemanticExtraction, build_process_result
```

Change it to:

```python
from semantic.common import SemanticExtraction, build_process_result
```

- [ ] **Step 2: Verify tests now import without error**

```bash
python -m pytest tests/test_constraint_tentative_guard.py -x -q 2>&1 | head -20
```

Expected: imports succeed; tests fail at assertion (six definitive tests still failing — correct).

- [ ] **Step 3: Remove `constraint_candidates` from `strict_typed_memory_v7_claude_structured` prompt text**

In the prompt string for `strict_typed_memory_v7_claude_structured`, find and delete this line (it appears in the field-description block near the bottom of that prompt):

```
- constraint_candidates: only use_surface|use_source|perform_step with prohibit|prefer|require. Return [] if unsafe or hedged.
```

- [ ] **Step 4: Remove `constraint_candidates` from `strict_typed_memory_v7_claude_minimal` prompt text**

In `strict_typed_memory_v7_claude_minimal`, find and delete:

```
- constraint_candidates: only use_surface|use_source|perform_step with prohibit|prefer|require. Return [] if unsafe or hedged.
```

Also delete the sentence that mentions both `constraint_text` and `constraint_candidates` together:

```
constraint_text and constraint_candidates require a definitive commitment — the speaker clearly states a requirement, prohibition, or hard rule. Hedged or tentative language ("I think", "maybe", "probably", "leaning towards", "not sure") is not a constraint; leave null/[].
```

Replace it with:

```
constraint_text requires a definitive commitment — the speaker clearly states a requirement, prohibition, or hard rule. Hedged or tentative language ("I think", "maybe", "probably", "leaning towards", "not sure") is not a constraint; leave null.
```

- [ ] **Step 5: Remove `constraint_candidates` from `strict_typed_memory_v7_claude_clean` prompt text**

In `strict_typed_memory_v7_claude_clean`, find and delete:

```
- constraint_candidates: normalized constraint objects. Return [] unless all required fields can be filled safely.
```

Also find this line:

```
Never infer anchors or normalized constraints. subject_hints may use only workstream|component|surface. constraint_candidates may use only use_surface|use_source|perform_step with prohibit|prefer|require. Return [] when anchors or constraints are not safely explicit.
```

Replace it with:

```
Never infer anchors. subject_hints may use only workstream|component|surface. Return [] when anchors are not safely explicit.
```

- [ ] **Step 6: Remove `constraint_candidates` from the JSON output schema block**

Find the `OUTPUT_SCHEMA` block (around line 245–260). It contains:

```python
        "constraint_candidates": "array of {primary_scope_anchor: {kind: workstream|component|surface, value: string}, target_anchor: {kind: workstream|component|surface, value: string}, action_class: use_surface|use_source|perform_step, polarity: prohibit|prefer|require, confidence: high|medium|low|unknown, constraint_text: string} or null",
```

Delete that entire line.

- [ ] **Step 7: Remove `_normalize_constraint_candidates` from the parser**

In `_parse_extraction_payload`, find and delete this line (around line 400):

```python
    constraint_candidates = _normalize_constraint_candidates(payload.get("constraint_candidates"))
```

And in the `SemanticExtraction(...)` constructor call a few lines below, delete:

```python
        constraint_candidates=constraint_candidates,
```

- [ ] **Step 8: Delete the `_normalize_constraint_candidates` function**

Delete the entire function (lines 427–444 in original, search by name):

```python
def _normalize_constraint_candidates(value: Any) -> tuple[ConstraintCandidate, ...]:
    if value is None or value == "unknown":
        return ()
    if not isinstance(value, list):
        return ()
    normalized: list[ConstraintCandidate] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        constraint_text = str(item.get("constraint_text") or "").strip()
        if not constraint_text or constraint_text.lower() == "unknown":
            continue
        normalized.append(
            ConstraintCandidate(
                constraint_text=constraint_text,
            )
        )
    return tuple(normalized)
```

- [ ] **Step 9: Run tests — expect only the six definitive-statement tests to still fail**

```bash
python -m pytest tests/ -x -q 2>&1 | head -30
```

Expected: clean import, six `TestDefinitiveStatementsProduceConstraintMemory` tests fail with `AssertionError: 0 != 1`. No other failures.

- [ ] **Step 10: Commit**

```bash
git add semantic/llm_agent_memory.py
git commit -m "refactor: remove constraint_candidates from prompts, output schema, and parser in llm_agent_memory"
```

---

## Task 5: Rewrite `_append_typed_constraint_memory_objects` to gate on `constraint_text`

This is the fix that makes constraint_memory creation work.

**Files:**
- Modify: `semantic/agent_conversation_memory_memory.py:101-171`

- [ ] **Step 1: Replace `_append_typed_constraint_memory_objects`**

Replace the entire function (lines 101–171) with:

```python
def _append_typed_constraint_memory_objects(
    result: ProcessResult,
    *,
    source_item: SourceItem,
    extraction: SemanticExtraction,
) -> ProcessResult:
    constraint_text = (extraction.constraint_text or "").strip()
    if not constraint_text:
        return result
    if source_item.role and source_item.role.lower() != "user":
        return result
    if source_item.visibility in ("container", "public"):
        return result
    semantic_provenance = _semantic_provenance_from_process_result(result)
    producer_schema_id = str(semantic_provenance.get("prompt_schema_id") or CONSTRAINT_MEMORY_SCHEMA_ID)
    producer_schema_version = str(semantic_provenance.get("prompt_schema_version") or CONSTRAINT_MEMORY_SCHEMA_VERSION)
    prompt_variant = semantic_provenance.get("prompt_variant") if isinstance(semantic_provenance.get("prompt_variant"), str) else None
    envelope_subjects = _merge_subject_anchors(extraction.subject_hints)
    payload = {
        "summary": constraint_text,
        "constraint_text": constraint_text,
        "container_ref": source_item.container_ref,
        "thread_ref": source_item.thread_ref,
        "semantic_provenance": dict(semantic_provenance),
    }
    memory_object = MemoryObject(
        type=CONSTRAINT_MEMORY_TYPE,
        schema_id=CONSTRAINT_MEMORY_SCHEMA_ID,
        schema_version=CONSTRAINT_MEMORY_SCHEMA_VERSION,
        payload=payload,
        visibility=source_item.visibility,
        container_ref=source_item.container_ref,
        actor_ref=_resolve_actor_ref(source_item),
        freshness_at=source_item.occurred_at,
        envelope=_build_memory_envelope(
            kind="constraint",
            container_ref=source_item.container_ref,
            thread_ref=source_item.thread_ref,
            confidence="medium",
            producer_kind="item_extraction",
            producer_schema_id=producer_schema_id,
            producer_schema_version=producer_schema_version,
            prompt_variant=prompt_variant,
            kind_basis="constraint_text",
            subjects=envelope_subjects,
        ),
    )
    return replace(
        result,
        memory_objects=list(result.memory_objects) + [memory_object],
        relations=list(result.relations) + [
            Relation(
                from_kind="memory_object",
                from_id=memory_object.id,
                relation_type="supported_by",
                to_kind="source_item",
                to_id=source_item.id,
            )
        ],
        index_entries=list(result.index_entries) + [
            build_index_entry(
                target_kind="memory_object",
                target_id=memory_object.id,
                index_type="lexical",
                text_view=normalize_for_index(constraint_text),
                text_view_name="memory_object.constraint_memory_context",
            )
        ],
    )
```

- [ ] **Step 2: Run the constraint guard tests — all 13 should now pass**

```bash
python -m pytest tests/test_constraint_tentative_guard.py -v
```

Expected output (all pass):
```
PASSED tests/test_constraint_tentative_guard.py::TestTentativeStatementsDoNotProduceConstraintMemory::test_i_think_python_service
PASSED tests/test_constraint_tentative_guard.py::TestTentativeStatementsDoNotProduceConstraintMemory::test_maybe_latency
PASSED tests/test_constraint_tentative_guard.py::TestTentativeStatementsDoNotProduceConstraintMemory::test_leaning_towards
PASSED tests/test_constraint_tentative_guard.py::TestTentativeStatementsDoNotProduceConstraintMemory::test_id_prefer
PASSED tests/test_constraint_tentative_guard.py::TestTentativeStatementsDoNotProduceConstraintMemory::test_could_probably
PASSED tests/test_constraint_tentative_guard.py::TestTentativeStatementsDoNotProduceConstraintMemory::test_was_thinking_maybe
PASSED tests/test_constraint_tentative_guard.py::TestTentativeStatementsDoNotProduceConstraintMemory::test_mixed_tentative_and_definitive_rejected
PASSED tests/test_constraint_tentative_guard.py::TestDefinitiveStatementsProduceConstraintMemory::test_not_going_saas
PASSED tests/test_constraint_tentative_guard.py::TestDefinitiveStatementsProduceConstraintMemory::test_has_to_run_linux
PASSED tests/test_constraint_tentative_guard.py::TestDefinitiveStatementsProduceConstraintMemory::test_absolutely_cannot
PASSED tests/test_constraint_tentative_guard.py::TestDefinitiveStatementsProduceConstraintMemory::test_must_be_rest
PASSED tests/test_constraint_tentative_guard.py::TestDefinitiveStatementsProduceConstraintMemory::test_no_external_deps
PASSED tests/test_constraint_tentative_guard.py::TestDefinitiveStatementsProduceConstraintMemory::test_must_be_encrypted
```

- [ ] **Step 3: Run full test suite**

```bash
python -m pytest tests/ -x -q
```

Expected: all tests pass (same count as before, roughly 732 passed, 5 skipped).

- [ ] **Step 4: Commit**

```bash
git add semantic/agent_conversation_memory_memory.py
git commit -m "fix: create constraint_memory from constraint_text, remove structured constraint_candidates path"
```

---

## Task 6: Verify actor-scoped integration tests still hold

**Files:** None changed — verification only.

- [ ] **Step 1: Run actor-scoped memory tests**

```bash
python -m pytest tests/test_actor_scoped_memory.py -v 2>&1 | head -40
```

Expected: all tests pass, including:
- `test_assistant_response_does_not_produce_constraint_memory` — role guard still works
- The shared-container interest/constraint suppression tests — visibility guard still works

- [ ] **Step 2: Run routing constraint tests**

```bash
python -m pytest tests/test_agent_conversation_memory_routing_constraints.py -v
```

Expected: all pass. Routing weights are unchanged; constraint_memory objects now exist, so routing can find them.

- [ ] **Step 3: Run full suite one more time for final green confirmation**

```bash
python -m pytest tests/ -q
```

Expected: `732 passed, 5 skipped` (or equivalent — exact count may vary slightly).

- [ ] **Step 4: Commit verification note if any count changed, otherwise nothing to commit**

If all counts match, nothing to commit. If a count differs unexpectedly, investigate before proceeding.

---

## Task 7: Update `state.md` and roadmap

The current `docs/context/state.md` does not mention the constraint_memory promotion bug. Since this fixes a silent gap in shipped behavior, it warrants a state update.

**Files:**
- Modify: `docs/context/state.md`

- [ ] **Step 1: Update the constraint_memory bullet in `state.md`**

Find the bullet that reads:
```
  - constraint_memory has a role guard — assistant messages cannot create it
```

Add a new sentence after it:
```
  - constraint_memory is now created directly from `constraint_text` — the structured `constraint_candidates` extraction path has been removed; natural-language constraints are reliably promoted
```

- [ ] **Step 2: Commit docs update**

```bash
git add docs/context/state.md
git commit -m "docs: note constraint_memory now created from constraint_text, structured path removed"
```
