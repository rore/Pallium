# Routing Layer CC Refactor — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use the executing-plans skill (`tools/execution-loop/SKILL.md`) to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce cyclomatic complexity in the routing/scoring layer hotspots from pathological ranges (CC 41–98) to maintainable ranges (≤ 20 per function) through pure structural refactoring with zero behavior change.

**Architecture:** Each refactor is a pure decomposition — no logic changes, no new behavior, only structural reorganization (extract sub-functions, split by dispatch key, extract typed helpers). Every step is verified by the full test suite before committing.

**Tech Stack:** Python 3.12+, radon (CC measurement), pytest

---

## Scope

### In scope (F-grade functions, CC ≥ 41)

| File | Function | CC | Strategy |
|------|----------|----|----------|
| `routing_scoring.py` | `_specificity_bonus` | 41 | Split by result_kind |
| `routing_scoring.py` | `_candidate_evidence_shape_score` | 41 | Split by memory type |
| `routing_scoring.py` | `_summarize_query_family_candidates` | 43 | Extract per-item accumulator |
| `routing_scoring.py` | `_query_family_candidate_score` | 70 | Typed signal dataclass + family dispatch |
| `routing_signals.py` | `_work_resumption_signal_types` | 44 | Split by result_kind/type |
| `routing_signals.py` | `_derive_query_signal_envelope` | 48 | Extract signal derivation helpers |
| `routing_selection.py` | `_prefer_duplicate_candidate` | 41 | Extract recall_mode branches |
| `routing_selection.py` | `_build_injectable_blocks` | 98 | Extract gate-blocked resolver + injection summary builder |
| `semantic/common.py` | `build_process_result` | 52 | Extract per-type memory builders |

### Deferred (document rationale)

- `route_query_results` (CC=47, `routing.py`) — top-level orchestrator; its CC comes from necessary guard clauses (floor filter, low_value short-circuit, empty results), not structural nesting. Decomposing it would add abstraction without readability gain.
- `build_thread_summary` (CC=38, `threads.py`), `_normalize_task_checkpoint_current_state` (CC=36) — threads.py is a separate concern; tackle in a follow-on.
- D-grade functions (CC 20–29) — borderline, acceptable for now.

---

## File Map

**Modified files (no new files):**

- `semantic/agent_conversation_memory_routing_scoring.py` — new private helpers co-located: `_specificity_bonus_memory_hit`, `_specificity_bonus_source_hit`, `_source_hit_shape_score`, `_lower_level_exact_shape_score`, `_task_checkpoint_shape_score`, `_continuity_shape_score`, `_pattern_memory_shape_score`, `_generic_summary_shape_score`, `_base_locality_score`, `CandidateSignalBundle` dataclass, `_recall_candidate_score`, `_work_resumption_candidate_score`, `_evidence_trace_candidate_score`, `_structured_recall_candidate_score`, `_accumulate_layer_stats`, `_resolve_cross_thread_continuity`
- `semantic/agent_conversation_memory_routing_signals.py` — new private helpers: `_source_hit_signal_types`, `_task_checkpoint_signal_types`, `_lower_level_signal_types`, `_summary_signal_types`, `_derive_resume_state_signal`, `_derive_history_lookup_signal`, `_derive_latest_status_signal`
- `semantic/agent_conversation_memory_routing_selection.py` — new private helpers: `_prefer_duplicate_by_recall_mode`, `_prefer_duplicate_by_content`, `_resolve_gate_blocked_injection`, `_make_injection_result`
- `semantic/common.py` — new private helpers: `_build_decision_result`, `_build_investigation_result`, `_build_interest_result`, `_build_turn_summary_result`

**Test files (read-only — verify only):**

- `tests/test_routing_selection.py`
- `tests/test_routing_quality_score.py`
- `tests/test_routing_injection_check.py`
- `tests/test_agent_conversation_memory_routing_injection.py`
- `tests/test_agent_conversation_memory_routing_recall.py`
- `tests/test_agent_conversation_memory_routing_resumption.py`
- `tests/test_agent_conversation_memory_routing_query_signals.py`
- `tests/test_routing_justification.py`

---

## Task 0: Baseline

**Files:**
- Read: `semantic/agent_conversation_memory_routing_scoring.py`
- Read: `semantic/agent_conversation_memory_routing_selection.py`
- Read: `semantic/agent_conversation_memory_routing_signals.py`
- Read: `semantic/common.py`

- [ ] **Step 0.1: Run full test suite and confirm green**

```bash
python -m pytest tests/ -x -q --tb=short
```
Expected: ~1802 tests pass, 6 skipped.

**Known flaky test:** `tests/test_thread_summary_accumulation.py::test_dual_package_concurrent_rapid_fire` fails intermittently due to a race condition (re-run passes). Ignore isolated failures of this test only during verification steps. Any other new failure is a regression.

- [ ] **Step 0.2: Capture radon baseline snapshot**

```bash
python -m radon cc semantic/ -n D -s 2>/dev/null | grep -v "^semantic/"
```

Record output. Target after all tasks: all hotspot functions ≤ CC 20.

---

## Task 1: `routing_scoring.py` — `_specificity_bonus` (CC=41)

**Files:**
- Modify: `semantic/agent_conversation_memory_routing_scoring.py`

The function has 14 independent `if` blocks that all check `item.result_kind`. Split by result_kind into two private helpers, keeping the exact scoring arithmetic unchanged.

- [ ] **Step 1.1: Read the function in full**

```bash
# Lines 692–725
grep -n "_specificity_bonus" semantic/agent_conversation_memory_routing_scoring.py
```

Read `semantic/agent_conversation_memory_routing_scoring.py` lines 692–725.

- [ ] **Step 1.2: Extract `_specificity_bonus_memory_hit` and `_specificity_bonus_source_hit`**

Add these two helpers immediately before `_specificity_bonus`. Then replace the body of `_specificity_bonus` with a dispatcher.

Target structure:

```python
def _specificity_bonus_memory_hit(item: QueryResultItem, intent: str) -> int:
    bonus = 0
    if item.type in ROUTING_LOWER_LEVEL_EXACT_TYPES:
        if intent == "structured_recall":
            bonus += 48 if item.type == "investigation_outcome" else 40
        elif intent == "evidence_trace":
            bonus += 25 if item.type == "decision" else 23
        else:
            bonus += 10
    if item.type in ROUTING_SUMMARY_TYPES and intent in {"structured_recall", "evidence_trace"}:
        bonus -= 20
    if item.type == "thread_summary" and intent == "work_resumption":
        if _memory_hit_has_selected_work_artifacts(item):
            bonus += 18
    if item.type == "task_checkpoint":
        if intent == "work_resumption":
            bonus += 28
        elif intent in {"structured_recall", "evidence_trace"}:
            bonus -= 18
    if item.type == "continuity_memory" and intent == "recall":
        bonus += 13
    if item.type in ROUTING_LOWER_LEVEL_EXACT_TYPES and intent == "recall":
        bonus += 43 if item.type == "decision" else 38
    if item.type == "continuity_memory" and intent == "recall":
        bonus -= 23
    if item.type == "pattern_memory" and intent == "recall":
        bonus += 13
    return bonus


def _specificity_bonus_source_hit(item: QueryResultItem, intent: str) -> int:
    if intent == "evidence_trace":
        return 15 if item.artifact_kind == "assistant_output" else 5
    if intent == "work_resumption":
        return 23 if (item.artifact_kind or "") in SELECTED_WORK_ARTIFACT_KINDS else 10
    if intent == "structured_recall":
        return 3 if item.artifact_kind == "assistant_output" else 1
    return 0


def _specificity_bonus(item: QueryResultItem, intent: str) -> int:
    if item.result_kind == "memory_hit":
        return _specificity_bonus_memory_hit(item, intent)
    if item.result_kind == "source_hit":
        return _specificity_bonus_source_hit(item, intent)
    return 0
```

**Critical invariant:** The two `continuity_memory + recall` blocks in `_specificity_bonus_memory_hit` MUST both be present (net effect: +13 − 23 = −10). Do not collapse them into a single `bonus -= 10` — preserve the original structure.

- [ ] **Step 1.3: Run routing tests**

```bash
python -m pytest tests/test_routing_selection.py tests/test_routing_quality_score.py tests/test_routing_injection_check.py tests/test_agent_conversation_memory_routing_recall.py -x -q --tb=short
```
Expected: All pass (same count as baseline).

- [ ] **Step 1.4: Run full test suite**

```bash
python -m pytest tests/ -x -q --tb=short
```
Expected: All pass.

- [ ] **Step 1.5: Check CC improvement**

```bash
python -m radon cc semantic/agent_conversation_memory_routing_scoring.py -n C -s 2>/dev/null
```
Expected: `_specificity_bonus` no longer appears in grade D+ list. `_specificity_bonus_memory_hit` should be CC ≤ 15.

- [ ] **Step 1.6: Architect review subagent**

Dispatch a `feature-dev:code-reviewer` subagent with this prompt:
> "Review the refactoring of `_specificity_bonus` in `semantic/agent_conversation_memory_routing_scoring.py`. The goal was pure structural decomposition — no logic change. Verify: (1) all scoring conditions from the original are present in the new helpers, (2) the two `continuity_memory + recall` blocks are both preserved (they are intentional accumulators, not a duplicate), (3) no new behavior was added. Report any behavioral differences found."

If the reviewer flags any issue, fix before proceeding.

- [ ] **Step 1.7: Commit**

```bash
git add semantic/agent_conversation_memory_routing_scoring.py
git commit -m "refactor: split _specificity_bonus by result_kind (CC 41 → ~14)"
```

---

## Task 2: `routing_scoring.py` — `_candidate_evidence_shape_score` (CC=41)

**Files:**
- Modify: `semantic/agent_conversation_memory_routing_scoring.py`

The function branches on `item.result_kind` and then on `item.type`. Extract a base locality scorer and per-type helpers, keeping arithmetic identical.

- [ ] **Step 2.1: Read the function in full**

Read `semantic/agent_conversation_memory_routing_scoring.py` lines 742–809.

- [ ] **Step 2.2: Extract helpers and rewrite dispatcher**

Add helpers immediately before `_candidate_evidence_shape_score`:

```python
def _base_locality_score(item: QueryResultItem, query_filters: QueryFilters | None) -> int:
    score = min(len(item.evidence), 3) * 8
    if _candidate_matches_thread(item, query_filters):
        score += 12
    elif _candidate_matches_container(item, query_filters):
        score += 6
    return score


def _source_hit_shape_score(item: QueryResultItem) -> int:
    artifact_kind = (item.artifact_kind or "").lower()
    if artifact_kind in SELECTED_WORK_ARTIFACT_KINDS:
        return 34
    elif artifact_kind == "assistant_output":
        return 28
    return 18


def _lower_level_exact_shape_score(item: QueryResultItem) -> int:
    score = 42
    payload = item.payload or {}
    if str(payload.get("decision_evidence_text") or payload.get("investigation_evidence_text") or "").strip():
        score += 10
    return score


def _task_checkpoint_shape_score(item: QueryResultItem) -> int:
    payload = item.payload or {}
    explicit_fields = sum(
        1
        for key in ("task", "current_state", "blocker_state", "next_step", "freshness_signal")
        if str(payload.get(key) or "").strip()
    )
    selected_work_artifacts = payload.get("selected_work_artifacts", [])
    artifact_count = len(selected_work_artifacts) if isinstance(selected_work_artifacts, list) else 0
    key_findings = _parse_string_list(payload.get("key_findings"))
    evidence_lines = _parse_string_list(payload.get("evidence"))
    score = 18 + min(explicit_fields, 5) * 8 + min(artifact_count, 4) * 6
    score += min(len(key_findings), 3) * 4 + min(len(evidence_lines), 3) * 5
    if str(payload.get("blocker_state") or "").strip() and str(payload.get("next_step") or "").strip():
        score += 10
    freshness_text = str(payload.get("freshness_signal") or "").lower()
    if freshness_text and any(marker in freshness_text for marker in ("latest", "current", "stale")):
        score += 6
    if not evidence_lines and not key_findings:
        score -= 12
    return score


def _continuity_memory_shape_score(item: QueryResultItem) -> int:
    payload = item.payload or {}
    score = 18
    if str(payload.get("carry_forward_answer") or "").strip():
        score += 18
    return score


def _pattern_memory_shape_score(item: QueryResultItem) -> int:
    payload = item.payload or {}
    score = 14
    label = str(payload.get("pattern_label") or "").strip()
    if label and label != "generic_pattern":
        score += 10
    return score


def _generic_summary_shape_score(item: QueryResultItem) -> int:
    payload = item.payload or {}
    score = 8
    conclusions = payload.get("conclusions", [])
    if isinstance(conclusions, list):
        score += min(len([e for e in conclusions if isinstance(e, dict) and e.get("text")]), 3) * 8
    return score


def _candidate_evidence_shape_score(
    item: QueryResultItem,
    *,
    layer: str,
    query_filters: QueryFilters | None,
) -> int:
    score = _base_locality_score(item, query_filters)
    if item.result_kind == "source_hit":
        return score + _source_hit_shape_score(item)
    if item.type in ROUTING_LOWER_LEVEL_EXACT_TYPES:
        return score + _lower_level_exact_shape_score(item)
    if item.type == "task_checkpoint":
        return score + _task_checkpoint_shape_score(item)
    if item.type == "continuity_memory":
        return score + _continuity_memory_shape_score(item)
    if item.type == "pattern_memory":
        return score + _pattern_memory_shape_score(item)
    if item.type in ROUTING_SUMMARY_TYPES:
        return score + _generic_summary_shape_score(item)
    return score
```

Note: the original function had a final `return score` at the bottom after the `ROUTING_SUMMARY_TYPES` block — this is now the final fallback `return score` in the dispatcher.

- [ ] **Step 2.3: Run routing tests**

```bash
python -m pytest tests/test_routing_selection.py tests/test_routing_quality_score.py tests/test_routing_injection_check.py tests/test_agent_conversation_memory_routing_recall.py -x -q --tb=short
```
Expected: All pass.

- [ ] **Step 2.4: Run full test suite**

```bash
python -m pytest tests/ -x -q --tb=short
```
Expected: All pass.

- [ ] **Step 2.5: Check CC**

```bash
python -m radon cc semantic/agent_conversation_memory_routing_scoring.py -n C -s 2>/dev/null
```
Expected: `_candidate_evidence_shape_score` no longer in grade C+. Each per-type helper should be CC ≤ 8.

- [ ] **Step 2.6: Architect review subagent**

Dispatch a `feature-dev:code-reviewer` with prompt:
> "Review the refactoring of `_candidate_evidence_shape_score` in `semantic/agent_conversation_memory_routing_scoring.py`. Pure structural decomposition, no logic change. Verify: (1) `_base_locality_score` is called unconditionally in the dispatcher and not inside any type branch (it was at the top of the original), (2) each per-type helper returns the type-specific score only (without the base), (3) the dispatcher's final `return score` fallback is present for unmatched types, (4) the `ROUTING_SUMMARY_TYPES` branch result includes `_generic_summary_shape_score` which contains the `conclusions` scoring logic from the original. Report behavioral differences."

Fix any flagged issues before proceeding.

- [ ] **Step 2.7: Commit**

```bash
git add semantic/agent_conversation_memory_routing_scoring.py
git commit -m "refactor: split _candidate_evidence_shape_score by type (CC 41 → ~6)"
```

---

## Task 3: `routing_scoring.py` — `_query_family_candidate_score` (CC=70)

**Files:**
- Modify: `semantic/agent_conversation_memory_routing_scoring.py`

The function has a 30-line preamble extracting metrics from `candidate_signals`, then dispatches to four independent family branches each returning independently. Decompose into: (1) a named `CandidateSignalBundle` dataclass, (2) four family-specific scorer functions, (3) a dispatch table.

- [ ] **Step 3.1: Read the function in full**

Read `semantic/agent_conversation_memory_routing_scoring.py` lines 389–563.

- [ ] **Step 3.2: Add `CandidateSignalBundle` dataclass**

Add immediately before `_query_family_candidate_score`.

**Import placement:** `from dataclasses import dataclass` must be added to the module's top-level import block (after the existing imports at the top of the file), NOT inline before the class definition. The `@dataclass` decorator must reference the module-level import.

```python
@dataclass(frozen=True)
class CandidateSignalBundle:
    pattern_support: int
    pattern_count: int
    continuity_support: int
    continuity_same_thread_hits: int
    checkpoint_support: int
    thread_summary_support: int
    turn_summary_support: int
    checkpoint_same_thread_hits: int
    checkpoint_work_usefulness: int
    source_support: int
    source_same_thread_hits: int
    source_evidence_hits: int
    source_work_usefulness: int
    decision_support: int
    investigation_support: int
    lower_level_support: int
    # Derived aggregates
    sharp_lower_level_support: int
    sharp_lower_level_rationale_hits: int
    sharp_lower_level_evidence_hits: int
    sharp_lower_level_same_thread_hits: int
    structured_recall_support: int
    structured_summary_support: int
    top_layer: str
    fresh_thread_cross_thread_recall: bool
    history_recall_with_relevant_carry_forward: bool
    constraint_recall: bool

    @classmethod
    def from_signals(
        cls,
        candidate_signals: dict[str, object],
        query_shape_tags: list[str],
        runtime_context: QueryRuntimeContext | None,
    ) -> "CandidateSignalBundle":
        supported_floor = ROUTING_SUPPORT_THRESHOLD["supported"]
        p_sup = _query_family_layer_metric(candidate_signals, "pattern_memory", "best_support")
        p_cnt = _query_family_layer_metric(candidate_signals, "pattern_memory", "count")
        cont_sup = _query_family_layer_metric(candidate_signals, "continuity_memory", "best_support")
        cont_sth = _query_family_layer_metric(candidate_signals, "continuity_memory", "same_thread_hits")
        ck_sup = _query_family_layer_metric(candidate_signals, "task_checkpoint", "best_support")
        ts_sup = _query_family_layer_metric(candidate_signals, "thread_summary", "best_support")
        tu_sup = _query_family_layer_metric(candidate_signals, "turn_summary", "best_support")
        ck_sth = _query_family_layer_metric(candidate_signals, "task_checkpoint", "same_thread_hits")
        ck_wu = _query_family_layer_metric(candidate_signals, "task_checkpoint", "best_work_usefulness")
        src_sup = _query_family_layer_metric(candidate_signals, "source_evidence", "best_support")
        src_sth = _query_family_layer_metric(candidate_signals, "source_evidence", "same_thread_hits")
        src_eh = _query_family_layer_metric(candidate_signals, "source_evidence", "evidence_hits")
        src_wu = _query_family_layer_metric(candidate_signals, "source_evidence", "best_work_usefulness")
        dec_sup = _query_family_layer_metric(candidate_signals, "decision", "best_support")
        inv_sup = _query_family_layer_metric(candidate_signals, "investigation_outcome", "best_support")
        ll_sup = _query_family_layer_metric(candidate_signals, "lower_level_memory", "best_support")
        sharp_ll = max(dec_sup, inv_sup, ll_sup)
        sharp_rh = sum(
            _query_family_layer_metric(candidate_signals, l, "rationale_hits")
            for l in ("investigation_outcome", "decision", "lower_level_memory")
        )
        sharp_eh = sum(
            _query_family_layer_metric(candidate_signals, l, "evidence_hits")
            for l in ("investigation_outcome", "decision", "lower_level_memory")
        )
        sharp_sth = sum(
            _query_family_layer_metric(candidate_signals, l, "same_thread_hits")
            for l in ("investigation_outcome", "decision", "lower_level_memory")
        )
        struct_rec = max(p_sup, cont_sup, ck_sup, ts_sup, tu_sup, sharp_ll)
        struct_sum = max(ck_sup, ts_sup, tu_sup)
        top = _query_family_top_layer(candidate_signals)
        ftctr = _runtime_context_prefers_cross_thread_recall(runtime_context)
        hrcf = (
            "history_lookup" in query_shape_tags
            and bool(candidate_signals.get("relevant_cross_thread_continuity_in_scope"))
            and sharp_ll >= supported_floor
        )
        cr = "constraint_recall" in query_shape_tags
        return cls(
            pattern_support=p_sup, pattern_count=p_cnt,
            continuity_support=cont_sup, continuity_same_thread_hits=cont_sth,
            checkpoint_support=ck_sup, thread_summary_support=ts_sup,
            turn_summary_support=tu_sup, checkpoint_same_thread_hits=ck_sth,
            checkpoint_work_usefulness=ck_wu,
            source_support=src_sup, source_same_thread_hits=src_sth,
            source_evidence_hits=src_eh, source_work_usefulness=src_wu,
            decision_support=dec_sup, investigation_support=inv_sup,
            lower_level_support=ll_sup,
            sharp_lower_level_support=sharp_ll,
            sharp_lower_level_rationale_hits=sharp_rh,
            sharp_lower_level_evidence_hits=sharp_eh,
            sharp_lower_level_same_thread_hits=sharp_sth,
            structured_recall_support=struct_rec,
            structured_summary_support=struct_sum,
            top_layer=top,
            fresh_thread_cross_thread_recall=ftctr,
            history_recall_with_relevant_carry_forward=hrcf,
            constraint_recall=cr,
        )
```

- [ ] **Step 3.3: Extract four family scorer functions**

Add each immediately before `_query_family_candidate_score`. Copy the exact body of each `if family == ...` block into the corresponding function, replacing local variable names with `sig.fieldname` accesses:

```python
def _recall_candidate_score(
    sig: CandidateSignalBundle,
    query_shape_tags: list[str],
) -> tuple[int, list[str]]:
    supported_floor = ROUTING_SUPPORT_THRESHOLD["supported"]
    score = 0
    reasons: list[str] = []
    # ... exact copy of the `if family == "recall":` body, using sig.* fields
    return score, reasons


def _work_resumption_candidate_score(
    sig: CandidateSignalBundle,
    query_shape_tags: list[str],
    runtime_context: QueryRuntimeContext | None,
) -> tuple[int, list[str]]:
    supported_floor = ROUTING_SUPPORT_THRESHOLD["supported"]
    score = 0
    reasons: list[str] = []
    # ... exact copy of the `if family == "work_resumption":` body
    return score, reasons


def _evidence_trace_candidate_score(
    sig: CandidateSignalBundle,
    query_shape_tags: list[str],
) -> tuple[int, list[str]]:
    supported_floor = ROUTING_SUPPORT_THRESHOLD["supported"]
    score = 0
    reasons: list[str] = []
    # ... exact copy of the `if family == "evidence_trace":` body
    return score, reasons


def _structured_recall_candidate_score(
    sig: CandidateSignalBundle,
    query_shape_tags: list[str],
) -> tuple[int, list[str]]:
    supported_floor = ROUTING_SUPPORT_THRESHOLD["supported"]
    score = 0
    reasons: list[str] = []
    # ... exact copy of the fallthrough (structured_recall) body at lines 545–563
    return score, reasons
```

When copying body content, replace each local variable reference with its corresponding `sig.*` attribute. For example:
- `pattern_support` → `sig.pattern_support`
- `history_recall_with_relevant_carry_forward` → `sig.history_recall_with_relevant_carry_forward`
- `structured_recall_support` → `sig.structured_recall_support`
- `structured_summary_support` → `sig.structured_summary_support` ← **critical**: this field is used in the `evidence_trace` and `recall` scorers; in `from_signals` it must map to `struct_sum = max(ck_sup, ts_sup, tu_sup)` assigned to `structured_summary_support=struct_sum`
- `sharp_lower_level_support` → `sig.sharp_lower_level_support`
- `constraint_recall` → `sig.constraint_recall`
- `fresh_thread_cross_thread_recall` → `sig.fresh_thread_cross_thread_recall`

- [ ] **Step 3.4: Rewrite `_query_family_candidate_score` as dispatcher**

```python
_FAMILY_CANDIDATE_SCORERS = {
    "recall": lambda sig, tags, ctx: _recall_candidate_score(sig, tags),
    "work_resumption": lambda sig, tags, ctx: _work_resumption_candidate_score(sig, tags, ctx),
    "evidence_trace": lambda sig, tags, ctx: _evidence_trace_candidate_score(sig, tags),
}

def _query_family_candidate_score(
    family: str,
    *,
    candidate_signals: dict[str, object],
    query_shape_tags: list[str],
    runtime_context: QueryRuntimeContext | None,
) -> tuple[int, list[str]]:
    sig = CandidateSignalBundle.from_signals(candidate_signals, query_shape_tags, runtime_context)
    scorer = _FAMILY_CANDIDATE_SCORERS.get(family)
    if scorer is not None:
        return scorer(sig, query_shape_tags, runtime_context)
    return _structured_recall_candidate_score(sig, query_shape_tags)
```

- [ ] **Step 3.5: Verify `structured_recall` path is exercised**

Before running the full test suite, check which test file covers `family == "structured_recall"`:

```bash
grep -r "structured_recall" tests/ --include="*.py" -l
```

If no test explicitly routes to the `structured_recall` family scorer, add a minimal fixture test to `tests/test_routing_quality_score.py`:

```python
def test_structured_recall_family_candidate_score():
    from semantic.agent_conversation_memory_routing_scoring import _query_family_candidate_score
    # Minimal candidate_signals with no special support
    signals = {"layer_support": {}, "top_layers": [], "sharp_lower_level_in_scope": False,
               "strong_task_checkpoint_in_scope": False, "strong_source_evidence_in_scope": False,
               "relevant_cross_thread_continuity_in_scope": False, "continuity_topic_alignment_tokens": []}
    score, reasons = _query_family_candidate_score(
        "structured_recall", candidate_signals=signals, query_shape_tags=[], runtime_context=None
    )
    assert isinstance(score, int)
    assert isinstance(reasons, list)
```

- [ ] **Step 3.6: Run routing tests**

```bash
python -m pytest tests/test_routing_selection.py tests/test_routing_quality_score.py tests/test_routing_injection_check.py tests/test_agent_conversation_memory_routing_recall.py tests/test_agent_conversation_memory_routing_resumption.py tests/test_agent_conversation_memory_routing_query_signals.py -x -q --tb=short
```
Expected: All pass.

- [ ] **Step 3.7: Run full test suite**

```bash
python -m pytest tests/ -x -q --tb=short
```
Expected: All pass.

- [ ] **Step 3.8: Check CC**

```bash
python -m radon cc semantic/agent_conversation_memory_routing_scoring.py -n C -s 2>/dev/null
```
Expected: `_query_family_candidate_score` CC ≤ 5. Each family scorer CC ≤ 18.

- [ ] **Step 3.9: Architect review subagent**

Dispatch `feature-dev:code-reviewer`:
> "Review the refactoring of `_query_family_candidate_score` in `semantic/agent_conversation_memory_routing_scoring.py`. Pure structural decomposition. Verify: (1) `CandidateSignalBundle.from_signals()` computes every local variable that existed in the original preamble (lines 396–444), including derived aggregates like `sharp_lower_level_support = max(decision_support, investigation_support, lower_level_support)`. (2) Each family scorer function uses `sig.*` field accesses for the same values that the original accessed via local variables. (3) The fallthrough path (structured_recall, original lines 545–563) is now `_structured_recall_candidate_score` and is reached when family is not in the dispatch table. (4) The `supported_floor = ROUTING_SUPPORT_THRESHOLD['supported']` binding is present inside each family scorer where the original used it. Report any behavioral differences."

- [ ] **Step 3.10: Commit**

```bash
git add semantic/agent_conversation_memory_routing_scoring.py
git commit -m "refactor: decompose _query_family_candidate_score into typed signal bundle + family dispatch (CC 70 → ~5)"
```

---

## Task 4: `routing_scoring.py` — `_summarize_query_family_candidates` (CC=43)

**Files:**
- Modify: `semantic/agent_conversation_memory_routing_scoring.py`

The function has three conceptual phases: (1) per-item loop accumulating layer stats, (2) continuity candidate filtering, (3) final aggregation and return. Extract each to a named helper.

- [ ] **Step 4.1: Read the function in full**

Read `semantic/agent_conversation_memory_routing_scoring.py` lines 191–350.

- [ ] **Step 4.2: Extract `_accumulate_layer_stats`**

Extract the body of the main `for item in retrieved_candidates:` loop (the stats accumulation per item) into:

```python
def _accumulate_layer_stats(
    item: QueryResultItem,
    *,
    layer: str,
    query_filters: QueryFilters | None,
    query_text: str,
    query_tokens: tuple[str, ...],
) -> dict[str, object] | None:
    """Accumulates per-item signals into a stats dict.
    
    Returns None if this item should be skipped (e.g. it is the current query echoed back).
    The caller uses the returned dict to update layer_support and conditionally append
    to continuity_candidates.
    
    Returned dict keys: layer, support_score, same_thread, same_container,
    work_signal_types, work_usefulness, work_reasons, has_rationale,
    has_explicit_evidence, candidate_is_strong, sharp_candidate.
    """
```

**Critical:** The `_source_hit_matches_current_query_text` check in the original is a `continue` that skips the entire stats accumulation AND the `continuity_candidates.append`. The helper must return `None` for this case, and the caller must handle `None` by skipping both the `layer_support.setdefault(...)` update AND any continuity candidate append.

**Continuity candidates:** The original loop appends to `continuity_candidates` when `layer == "continuity_memory"`. This append happens AFTER the skip check. The helper should include a boolean `is_continuity_candidate` in the returned dict, and the caller does:

```python
result = _accumulate_layer_stats(item, ...)
if result is None:
    continue
# update layer_support using result fields
...
if result["layer"] == "continuity_memory":
    continuity_candidates.append({
        "result_id": _routing_result_id(item),
        "support": result["support_score"],
        "same_thread": result["same_thread"],
        "content_overlap_count": 0,
        "content_overlap_tokens": [],
        "strong_candidate": result["candidate_is_strong"],
    })
```

- [ ] **Step 4.3: Extract `_resolve_cross_thread_continuity_candidates`**

Extract the continuity filtering block (after `bounded_layer_support` is built, before `sharp_lower_level_topic_tokens`) into:

```python
def _resolve_cross_thread_continuity_candidates(
    continuity_candidates: list[dict[str, object]],
    bounded_layer_support: dict[str, dict[str, object]],
) -> dict[str, object] | None:
    """Returns the best relevant cross-thread continuity candidate or None."""
    # ... exact copy of the filtering and sorting logic
```

- [ ] **Step 4.4: Rewrite main function body**

The main function becomes: call per-item helper → accumulate layer_support → call continuity resolver → build final return dict. No logic changes.

- [ ] **Step 4.5: Run full test suite**

```bash
python -m pytest tests/ -x -q --tb=short
```
Expected: All pass.

- [ ] **Step 4.6: Check CC**

```bash
python -m radon cc semantic/agent_conversation_memory_routing_scoring.py -n C -s 2>/dev/null
```
Expected: `_summarize_query_family_candidates` CC ≤ 15.

- [ ] **Step 4.7: Architect review + commit**

Dispatch `feature-dev:code-reviewer`:
> "Review refactoring of `_summarize_query_family_candidates` in routing_scoring.py. Verify: (1) `_accumulate_layer_stats` skips items where `_source_hit_matches_current_query_text` returns True (returns None) — same as the `continue` in the original. (2) The continuity candidate list and the cross-thread resolution logic produce identical output structures. (3) The final return dict has the same keys and value derivations as the original."

```bash
git add semantic/agent_conversation_memory_routing_scoring.py
git commit -m "refactor: decompose _summarize_query_family_candidates (CC 43 → ~12)"
```

---

## Task 5: `routing_signals.py` — `_work_resumption_signal_types` (CC=44)

**Files:**
- Modify: `semantic/agent_conversation_memory_routing_signals.py`

The function branches on `item.result_kind` and then on `item.type`. Each branch is independent. Extract per-type signal collectors.

- [ ] **Step 5.1: Read the function in full**

Read `semantic/agent_conversation_memory_routing_signals.py` lines 31–82.

- [ ] **Step 5.2: Extract type-specific signal collectors**

```python
def _source_hit_signal_types(item: QueryResultItem) -> set[str]:
    signal_types: set[str] = set()
    excerpt = str(item.excerpt or "").strip()
    signal_type = _classify_work_signal_text(item.artifact_kind, excerpt)
    if signal_type:
        signal_types.add(signal_type)
    if excerpt:
        signal_types.add("evidence")
    return signal_types


def _task_checkpoint_signal_types(payload: dict[str, object]) -> set[str]:
    signal_types: set[str] = set()
    if str(payload.get("task") or "").strip():
        signal_types.add("task")
    if str(payload.get("current_state") or "").strip():
        signal_types.add("progress_update")
    if _parse_string_list(payload.get("key_findings")):
        signal_types.add("key_finding")
    if str(payload.get("blocker_state") or "").strip():
        signal_types.add("blocker")
    if str(payload.get("next_step") or "").strip():
        signal_types.add("next_step")
    if _parse_string_list(payload.get("evidence")):
        signal_types.add("evidence")
    if str(payload.get("freshness_signal") or "").strip():
        signal_types.add("freshness")
    for artifact in payload.get("selected_work_artifacts", []):
        if not isinstance(artifact, dict):
            continue
        artifact_signal = str(artifact.get("signal_type") or "").strip()
        if artifact_signal in {"progress_update", "blocker", "next_step"}:
            signal_types.add(artifact_signal)
    return signal_types


def _lower_level_signal_types(payload: dict[str, object]) -> set[str]:
    signal_types: set[str] = {"key_finding"}
    if str(payload.get("decision_evidence_text") or payload.get("investigation_evidence_text") or "").strip():
        signal_types.add("evidence")
    return signal_types


def _summary_signal_types(item: QueryResultItem, payload: dict[str, object]) -> set[str]:
    signal_types: set[str] = set()
    if str(payload.get("summary") or "").strip():
        signal_types.add("key_finding")
    for artifact in payload.get("selected_work_artifacts", []):
        if not isinstance(artifact, dict):
            continue
        artifact_signal = str(artifact.get("signal_type") or "").strip()
        if artifact_signal in {"progress_update", "blocker", "next_step"}:
            signal_types.add(artifact_signal)
    return signal_types


def _work_resumption_signal_types(item: QueryResultItem) -> tuple[str, ...]:
    if item.result_kind == "source_hit":
        signal_types = _source_hit_signal_types(item)
        return tuple(signal for signal in WORK_RESUMPTION_SIGNAL_TYPES if signal in signal_types)
    payload = item.payload or {}
    if item.type == "task_checkpoint":
        signal_types = _task_checkpoint_signal_types(payload)
    elif item.type in ROUTING_LOWER_LEVEL_EXACT_TYPES:
        signal_types = _lower_level_signal_types(payload)
    elif item.type in ROUTING_SUMMARY_TYPES:
        signal_types = _summary_signal_types(item, payload)
    elif item.type == "continuity_memory":
        signal_types = {"key_finding"} if str(payload.get("carry_forward_answer") or "").strip() else set()
    elif item.type == "pattern_memory" and str(payload.get("summary") or "").strip():
        signal_types = {"key_finding"}
    else:
        signal_types = set()
    return tuple(signal for signal in WORK_RESUMPTION_SIGNAL_TYPES if signal in signal_types)
```

- [ ] **Step 5.3: Run full test suite**

```bash
python -m pytest tests/ -x -q --tb=short
```
Expected: All pass.

- [ ] **Step 5.4: Check CC**

```bash
python -m radon cc semantic/agent_conversation_memory_routing_signals.py -n C -s 2>/dev/null
```
Expected: `_work_resumption_signal_types` CC ≤ 6.

- [ ] **Step 5.5: Architect review + commit**

Dispatch `feature-dev:code-reviewer`:
> "Review refactoring of `_work_resumption_signal_types` in routing_signals.py. Verify the signal_types collected in each extracted helper exactly match the original conditional blocks. Pay attention to: (1) `_source_hit_signal_types` — excerpt must be non-empty for `evidence` signal, (2) `_summary_signal_types` — applies to both thread_summary and turn_summary types (ROUTING_SUMMARY_TYPES includes both), (3) `continuity_memory` and `pattern_memory` cases use inline set construction, not helpers — confirm these are handled correctly in the dispatcher. Report behavioral differences."

```bash
git add semantic/agent_conversation_memory_routing_signals.py
git commit -m "refactor: split _work_resumption_signal_types by type (CC 44 → ~6)"
```

---

## Task 6: `routing_signals.py` — `_derive_query_signal_envelope` (CC=48)

**Files:**
- Modify: `semantic/agent_conversation_memory_routing_signals.py`

The function derives 5 signal booleans and a confidence level. Extract the derivation of each non-trivial signal into a named helper function.

- [ ] **Step 6.1: Read the function in full**

Read `semantic/agent_conversation_memory_routing_signals.py` lines 402–548.

- [ ] **Step 6.2: Extract signal derivation helpers**

```python
def _derive_resume_state_signal(
    *,
    runtime_context: QueryRuntimeContext | None,
    policy_evidence: dict[str, object],
    anchor_prefiltered_candidates: list[QueryResultItem],
) -> tuple[bool, list[str]]:
    """Returns (resume_state, derivation_reasons)."""
    derivation: list[str] = []
    is_resumed = runtime_context is not None and runtime_context.turn_kind == "resumed_session"
    if not is_resumed:
        return False, derivation
    work_gate = _work_state_evidence_gate_passes(policy_evidence)
    if work_gate:
        return True, ["resumed_session_with_evidence"]
    # Fallback: resumed without checkpoint evidence — check for sharp candidates with no vector match
    _candidate_vec_scores = [
        int(getattr(item, "vector_score", 0) or 0)
        for item in anchor_prefiltered_candidates
        if getattr(item, "vector_score", None) is not None
    ]
    _has_composite_scores = any(
        getattr(item, "lexical_score", None) is not None
        or getattr(item, "vector_score", None) is not None
        for item in anchor_prefiltered_candidates
    )
    _best_candidate_vec = max(_candidate_vec_scores) if _candidate_vec_scores else (0 if _has_composite_scores else None)
    _RESUMED_SESSION_SUPPORT_FLOOR = 40
    _has_supported_sharp = (
        _best_candidate_vec is not None
        and _best_candidate_vec == 0
        and any(
            item.result_kind == "memory_hit"
            and getattr(item, "type", None) in ("decision", "investigation_outcome")
            and _policy_candidate_support_estimate(item, _result_layer(item)) >= _RESUMED_SESSION_SUPPORT_FLOOR
            for item in anchor_prefiltered_candidates
        )
    )
    if _has_supported_sharp:
        return True, ["resumed_session_with_supported_decision"]
    return False, derivation


def _derive_history_lookup_signal(
    candidate_evidence: dict[str, object],
) -> tuple[bool, list[str]]:
    dominant = str(candidate_evidence.get("dominant_memory_layer") or "")
    per_layer = candidate_evidence.get("per_layer_support", {})
    history_layers = {"pattern_memory", "continuity_memory"}
    sharp_layers = {"decision", "investigation_outcome"}
    if dominant in history_layers:
        return True, [f"dominant_{dominant}"]
    if dominant in sharp_layers:
        layer_info = per_layer.get(dominant, {})
        if isinstance(layer_info, dict) and int(layer_info.get("best_support_score", 0)) >= POLICY_SUPPORT_THRESHOLD:
            return True, [f"strong_{dominant}"]
    return False, []


def _derive_latest_status_signal(
    candidate_evidence: dict[str, object],
    anchor_prefiltered_candidates: list[QueryResultItem],
) -> tuple[bool, list[str]]:
    dominant = str(candidate_evidence.get("dominant_memory_layer") or "")
    from datetime import timezone as _tz
    _now = datetime.now(_tz.utc)
    for item in anchor_prefiltered_candidates:
        if item.result_kind != "memory_hit":
            continue
        if item.type not in {"task_checkpoint", "thread_summary"}:
            continue
        payload = item.payload or {}
        has_state = bool(payload.get("current_state") or payload.get("freshness_signal"))
        if not has_state:
            continue
        if item.freshness_at and (_now - item.freshness_at).total_seconds() < 86400:
            if _result_layer(item) == dominant:
                return True, ["dominant_fresh_state_memory"]
    return False, []
```

Then rewrite `_derive_query_signal_envelope` to call these helpers and assemble the result. The call site must preserve the original guard ordering — `_derive_latest_status_signal` must only be called when neither `resume_state` nor `history_lookup` is already True:

```python
# In _derive_query_signal_envelope, after deriving resume_state and history_lookup:
signals["resume_state"], resume_derivation = _derive_resume_state_signal(...)
derivation.extend(resume_derivation)
signals["history_lookup"], history_derivation = _derive_history_lookup_signal(candidate_evidence)
derivation.extend(history_derivation)

# latest_status_request only fires when neither resume_state nor history_lookup is set
if not signals["resume_state"] and not signals["history_lookup"]:
    signals["latest_status_request"], latest_derivation = _derive_latest_status_signal(
        candidate_evidence, anchor_prefiltered_candidates
    )
    derivation.extend(latest_derivation)
```

**Critical:** Do NOT call `_derive_latest_status_signal` unconditionally and then discard the result. The original iterates `anchor_prefiltered_candidates` with a `break` inside this guard — calling it unconditionally wastes work and may shadow a correct `resume_state` signal with a `latest_status_request` signal in edge cases.

- [ ] **Step 6.3: Run full test suite**

```bash
python -m pytest tests/ -x -q --tb=short
```
Expected: All pass.

- [ ] **Step 6.4: Check CC**

```bash
python -m radon cc semantic/agent_conversation_memory_routing_signals.py -n C -s 2>/dev/null
```
Expected: `_derive_query_signal_envelope` CC ≤ 12.

- [ ] **Step 6.5: Architect review + commit**

Dispatch `feature-dev:code-reviewer`:
> "Review refactoring of `_derive_query_signal_envelope` in routing_signals.py. Verify: (1) `_derive_resume_state_signal` handles both the `is_resumed + work_gate` path AND the fallback sharp-candidate check. The fallback has a non-obvious invariant: it only fires when `_best_candidate_vec == 0`, meaning vector search found nothing — confirm this is preserved. (2) `_derive_latest_status_signal` only fires when neither `resume_state` nor `history_lookup` is already True (the original had `if not any(signals[s] ...)`). Verify the new code preserves this ordering — the helper should not be called if those signals are already set. (3) The `tier1_confidence` calculation and final return are unchanged. Report differences."

```bash
git add semantic/agent_conversation_memory_routing_signals.py
git commit -m "refactor: decompose _derive_query_signal_envelope signal derivation (CC 48 → ~10)"
```

---

## Task 7: `routing_selection.py` — `_build_injectable_blocks` (CC=98)

**Files:**
- Modify: `semantic/agent_conversation_memory_routing_selection.py`

The function has two major paths: (A) gate-blocked path (try 5 override strategies in priority order), (B) normal path (build eligible candidates, dedup, cap, return). Both paths build nearly identical result dicts. Extract: `_make_injection_result` for the repeated dict construction, `_resolve_gate_blocked_injection` for the full gate-blocked path.

- [ ] **Step 7.1: Read the full function**

Read `semantic/agent_conversation_memory_routing_selection.py` lines 232–end of function. Look for where the gate-blocked path ends and the normal path begins (around line 469 where `primary_non_discussion_eligible` is defined).

- [ ] **Step 7.2: Extract `_make_injection_result`**

This is a dict factory for the result tuple. Currently the function builds nearly-identical dicts at 7+ return sites. Extract a helper:

```python
def _make_injection_result(
    blocks: list[InjectableBlock],
    *,
    should_inject: bool,
    decision_reason: str,
    returned_block_ids: list[str],
    eligible_result_ids: list[str],
    dropped_by_cap_result_ids: list[str],
    same_thread_context: dict[str, object],
    injection_method: str | None = None,
    dedup_applied: bool = False,
    dedup_removed_count: int = 0,
    dedup_removed_result_ids: list[str] | None = None,
    dedup_kept_map: dict | None = None,
    expansion_applied: bool = False,
    expansion_added_count: int = 0,
    best_lexical: float | None = None,
    best_vector: int | None = None,
    cap_config: dict[str, object] | None = None,
) -> tuple[list[InjectableBlock], dict[str, object]]:
    result: dict[str, object] = {
        "should_inject": should_inject,
        "decision_reason": decision_reason,
        "returned_block_ids": returned_block_ids,
        "eligible_result_ids": eligible_result_ids,
        "dropped_by_cap_result_ids": dropped_by_cap_result_ids,
        "cap": INJECTION_HARD_CEILING,
        "dedup_applied": dedup_applied,
        "dedup_removed_count": dedup_removed_count,
        "dedup_removed_result_ids": dedup_removed_result_ids or [],
        "dedup_kept_map": dedup_kept_map or {},
        "expansion_applied": expansion_applied,
        "expansion_added_count": expansion_added_count,
        "same_thread_context_evaluation": same_thread_context,
    }
    if injection_method is not None:
        result["injection_method"] = injection_method
    if best_lexical is not None:
        result["best_lexical"] = best_lexical
    if best_vector is not None:
        result["best_vector"] = best_vector
    if cap_config is not None:
        result["cap_config"] = cap_config
    return blocks, result
```

**Note:** `cap_config` is only present on the normal-path final return site (lines ~665–669 in the original). The gate-blocked override returns do NOT include `cap_config`. Pass `cap_config={"floor": INJECTION_MIN_FLOOR, "expansion_ratio": INJECTION_EXPANSION_RATIO, "ceiling": INJECTION_HARD_CEILING}` only at the normal-path return site, not in `_resolve_gate_blocked_injection`.

Replace all 7+ hand-built result dicts with calls to `_make_injection_result(...)`.

- [ ] **Step 7.3: Extract `_resolve_gate_blocked_injection`**

Extract the entire gate-blocked branch (lines ~285–467) into:

```python
def _resolve_gate_blocked_injection(
    final_candidates: list[dict[str, object]],
    ranked_candidates: list[dict[str, object]],
    *,
    intent: str,
    recall_mode: str,
    query_text: str,
    evidence_request: bool,
    same_thread_context: dict[str, object],
) -> tuple[list[InjectableBlock], dict[str, object]] | None:
    """Try override strategies in priority order when the confidence gate blocked injection.
    
    Returns a result tuple if any override applies, or None to fall through to normal path.
    """
    # 1. Constraint supplement
    constraint_supplements = _find_constraint_supplements(ranked_candidates, already_selected_ids=set())
    if constraint_supplements:
        ...  # exact copy
        return _make_injection_result(...)
    # 2. Carry-forward low confidence override
    carry_forward_override = _carry_forward_low_confidence_override_candidates(final_candidates, ...)
    if carry_forward_override:
        ...
        return _make_injection_result(...)
    # 3. Supported exact low confidence override
    exact_memory_override = _supported_exact_low_confidence_override_candidates(final_candidates, ...)
    if exact_memory_override:
        ...
        return _make_injection_result(...)
    # 4. Source evidence provenance override
    source_evidence_override = _source_evidence_provenance_override_candidates(final_candidates, ...)
    if source_evidence_override:
        ...
        return _make_injection_result(...)
    # 5. Fact summary override
    fact_summary_override = _fact_summary_low_confidence_override_candidates(final_candidates, ...)
    if fact_summary_override:
        ...
        return _make_injection_result(...)
    return None
```

- [ ] **Step 7.4: Rewrite `_build_injectable_blocks` main body**

```python
def _build_injectable_blocks(...) -> tuple[list[InjectableBlock], dict[str, object]]:
    same_thread_context = _evaluate_same_thread_local_context(...)
    if same_thread_context["suppress_injection"]:
        return _make_injection_result([], should_inject=False, decision_reason="same_thread_context_sufficient", ...)
    if not final_candidates:
        return _make_injection_result([], should_inject=False, decision_reason="no_relevant_memory", ...)
    if not should_allow_injection(final_candidates, query_text=query_text, intent=intent):
        resolved = _resolve_gate_blocked_injection(final_candidates, ranked_candidates, ...)
        if resolved is not None:
            return resolved
        return _make_injection_result([], should_inject=False, decision_reason="low_injection_confidence", ...)
    # Normal path: build eligible candidates, source evidence override, dedup, cap, return
    ...  # normal path code, unchanged
```

- [ ] **Step 7.5: Add direct test for `_resolve_gate_blocked_injection`**

The gate-blocked resolver is only exercised indirectly through `_build_injectable_blocks`. Add a targeted test in `tests/test_routing_injection_check.py`:

```python
def test_resolve_gate_blocked_injection_constraint_supplement(make_memory_hit):
    """Constraint supplement fires when gate is blocked but a recent constraint was retrieved."""
    from semantic.agent_conversation_memory_routing_selection import _resolve_gate_blocked_injection
    constraint_candidate = make_memory_hit(type="constraint_memory", support_score=50)
    same_thread_ctx = {"suppress_injection": False}
    result = _resolve_gate_blocked_injection(
        [constraint_candidate],
        [constraint_candidate],
        intent="recall",
        recall_mode="default",
        query_text="what were my constraints?",
        evidence_request=False,
        same_thread_context=same_thread_ctx,
    )
    assert result is not None
    blocks, meta = result
    assert meta["should_inject"] is True
    assert meta["decision_reason"] == "constraint_supplement"
```

Adapt `make_memory_hit` to produce the dict structure the function expects (a `dict` with `"item"` key containing a `QueryResultItem`).

- [ ] **Step 7.6: Run routing tests**

```bash
python -m pytest tests/test_routing_selection.py tests/test_routing_injection_check.py tests/test_agent_conversation_memory_routing_injection.py -x -q --tb=short
```
Expected: All pass.

- [ ] **Step 7.7: Run full test suite**

```bash
python -m pytest tests/ -x -q --tb=short
```
Expected: All pass.

- [ ] **Step 7.8: Check CC**

```bash
python -m radon cc semantic/agent_conversation_memory_routing_selection.py -n D -s 2>/dev/null | grep "_build_injectable_blocks\|_resolve_gate_blocked"
```
Expected: `_build_injectable_blocks` CC ≤ 15. `_resolve_gate_blocked_injection` CC ≤ 20.

- [ ] **Step 7.9: Architect review subagent**

Dispatch `feature-dev:code-reviewer`:
> "Review refactoring of `_build_injectable_blocks` in routing_selection.py. This is the highest-risk task — CC was 98. Verify: (1) `_make_injection_result` produces dicts identical in keys/values to each original hand-built dict. Pay special attention to the `low_injection_confidence` return site — original had `best_lexical` and `best_vector` keys, confirm `_make_injection_result` passes these through. (2) `_resolve_gate_blocked_injection` tries the 5 override strategies in the exact same priority order as the original. (3) The verbose injection logging calls (`_injection_verbose(...)`) are present in `_resolve_gate_blocked_injection` at the same decision points. (4) The normal path after the gate check is unchanged. Report any behavioral differences."

Fix any flagged issues before proceeding.

- [ ] **Step 7.10: Commit**

```bash
git add semantic/agent_conversation_memory_routing_selection.py
git commit -m "refactor: decompose _build_injectable_blocks gate-blocked path (CC 98 → ~12)"
```

---

## Task 8: `common.py` — `build_process_result` (CC=52)

**Files:**
- Modify: `semantic/common.py`

The function is a factory that creates different `MemoryObject` instances. It has exactly **three type-gated branches** (`decision`, `investigation_outcome`, `interest`) and **one terminal fallback** (`_should_create_turn_summary`). Note: `constraint_memory`, `task_checkpoint`, and `thread_summary` are NOT built here — they belong to separate processing paths. The terminal fallback uses a structural check (`_should_create_turn_summary(source_item, extraction)`) not a `candidate_type` check.

- [ ] **Step 8.1: Read the function in full**

Read `semantic/common.py` lines 300–499. Identify the four branches and the shared post-processing block (lines 465–499: relation + index entries).

- [ ] **Step 8.2: Extract three per-type builders and one terminal fallback**

Each builder returns `tuple[MemoryObject | None, str | None]` — the object and its index source text, or `(None, None)` if guards fail.

```python
def _build_decision_result(
    source_item: SourceItem,
    extraction: SemanticExtraction,
    decision_text: str,
    decision_evidence_text: str,
    rationale_text: str,
    schema_prefix: str,
    semantic_metadata: dict[str, str] | None,
) -> tuple["MemoryObject | None", "str | None"]:
    if (
        extraction.is_low_value_meta
        or extraction.candidate_type != "decision"
        or (source_item.role and source_item.role.lower() != "user")
        or not decision_text
        or not decision_evidence_text
        or not _typed_memory_payload_is_quality_viable(decision_text, decision_evidence_text)
        or not has_grounded_decision_text(source_item, decision_text)
        or not has_grounded_decision_evidence(source_item, decision_evidence_text)
    ):
        return None, None
    canonical_key = normalize_for_index(decision_text)
    obj = MemoryObject(
        type="decision",
        schema_id=f"{schema_prefix}.decision",
        schema_version="v1",
        payload={
            "decision": decision_text,
            "decision_evidence_text": decision_evidence_text,
            "rationale": rationale_text,
            "canonical_key": canonical_key,
            "source_type": source_item.source_type,
            "source_id": source_item.source_id,
            **({"semantic_provenance": semantic_metadata} if semantic_metadata else {}),
        },
        visibility=source_item.visibility,
        container_ref=source_item.container_ref,
        actor_ref=_resolve_actor_ref(source_item),
    )
    index_source = " ".join(p for p in (
        extraction.summary, decision_text or "",
        decision_evidence_text or "", rationale_text or "", canonical_key,
    ) if p)
    return obj, index_source
```

Create `_build_investigation_result` analogously (same guard structure: `extraction.candidate_type != "investigation_outcome"`, `not investigation_text`, `not investigation_evidence_text`, calls `_investigation_payload_is_quality_viable` + `has_grounded_investigation_evidence`).

Create `_build_interest_result` — preserve all four guards from the original `elif`: `extraction.candidate_type == "interest"`, `extraction.interest_text`, role guard, AND **visibility guard** (`source_item.visibility not in ("container", "public")`), AND source tokens guard (`len(tokenize_text(source_item.content)) >= _MINIMUM_INTEREST_SOURCE_TOKENS`). The visibility and token guards are easy to miss.

```python
def _build_turn_summary_result(
    source_item: SourceItem,
    extraction: SemanticExtraction,
    schema_prefix: str,
    semantic_metadata: dict[str, str] | None,
) -> tuple["MemoryObject | None", "str | None"]:
    """Terminal fallback: uses _should_create_turn_summary(), NOT candidate_type == 'turn_summary'."""
    if not _should_create_turn_summary(source_item, extraction):
        return None, None
    obj = MemoryObject(
        type="turn_summary",
        schema_id=f"{schema_prefix}.turn_summary",
        schema_version="v1",
        payload={
            "summary": extraction.summary,
            "source_type": source_item.source_type,
            "source_id": source_item.source_id,
            **({"semantic_provenance": semantic_metadata} if semantic_metadata else {}),
        },
        visibility=source_item.visibility,
        container_ref=source_item.container_ref,
        actor_ref=_resolve_actor_ref(source_item),
    )
    index_source = " ".join(p for p in (
        extraction.summary,
        extraction.constraint_text or "",
        extraction.blocker_text or "",
        extraction.progress_text or "",
        extraction.next_step_text or "",
        extraction.key_finding_text or "",
    ) if p)
    return obj, index_source
```

- [ ] **Step 8.3: Rewrite `build_process_result` dispatcher**

Use an explicit loop — do NOT use Python `or` chaining on tuples (a `(None, None)` tuple is truthy and would short-circuit incorrectly):

```python
    for builder in (
        lambda: _build_decision_result(source_item, extraction, decision_text, decision_evidence_text, rationale_text, schema_prefix, semantic_metadata),
        lambda: _build_investigation_result(source_item, extraction, investigation_text, investigation_evidence_text, rationale_text, key_finding_text, schema_prefix, semantic_metadata),
        lambda: _build_interest_result(source_item, extraction, schema_prefix, semantic_metadata),
        lambda: _build_turn_summary_result(source_item, extraction, schema_prefix, semantic_metadata),
    ):
        memory_object, index_source = builder()
        if memory_object is not None:
            memory_objects.append(memory_object)
            break
    else:
        index_source = ""
    # ... shared post-processing (lines 465–499) unchanged
```

- [ ] **Step 8.4: Run full test suite**

```bash
python -m pytest tests/ -x -q --tb=short
```
Expected: All pass.

- [ ] **Step 8.5: Check CC**

```bash
python -m radon cc semantic/common.py -n C -s 2>/dev/null
```
Expected: `build_process_result` CC ≤ 10. Each per-type builder CC ≤ 12.

- [ ] **Step 8.6: Architect review + commit**

Dispatch `feature-dev:code-reviewer`:
> "Review refactoring of `build_process_result` in semantic/common.py. Verify: (1) The three type-gated builders (`_build_decision_result`, `_build_investigation_result`, `_build_interest_result`) preserve all their original guard conditions. For `_build_interest_result` specifically, check for the visibility guard (`source_item.visibility not in ('container', 'public')`) and source-tokens guard — these are easy to drop. (2) `_build_turn_summary_result` uses `_should_create_turn_summary()` as its guard, NOT `extraction.candidate_type == 'turn_summary'`. (3) The dispatcher loop exits on the first successful builder (for-else pattern, not or-chaining). (4) The shared post-processing block (relation + lexical + vector index entries) is executed unchanged after the loop. Report differences."

```bash
git add semantic/common.py
git commit -m "refactor: decompose build_process_result into per-type builders (CC 52 → ~8)"
```

---

## Task 9: Final Verification

- [ ] **Step 9.1: Run full test suite — must be green**

```bash
python -m pytest tests/ -x -q --tb=short
```
Expected: All pass. Same count as Task 0.

- [ ] **Step 9.2: Final CC report**

```bash
python -m radon cc semantic/ -n D -s 2>/dev/null | grep -v "^semantic/"
```

Compare against Task 0 baseline. Expected: `_build_injectable_blocks`, `_query_family_candidate_score`, `_specificity_bonus`, `_candidate_evidence_shape_score`, `_summarize_query_family_candidates`, `_work_resumption_signal_types`, `_derive_query_signal_envelope`, `build_process_result` should all be gone from the D+ list (or replaced by their smaller extracted helpers at ≤ CC 20).

- [ ] **Step 9.3: Final architect review subagent**

Dispatch `feature-dev:code-reviewer`:
> "Review the complete routing CC refactor across these files: semantic/agent_conversation_memory_routing_scoring.py, semantic/agent_conversation_memory_routing_signals.py, semantic/agent_conversation_memory_routing_selection.py, semantic/common.py. Check: (1) No public API surface has changed — all new helpers are private (underscore prefix). (2) No existing imports in other files need updating. (3) The radon CC report shows all formerly-F-grade functions are gone or replaced by ≤ CC 20 decompositions. (4) No dead code was introduced. Report any issues."

- [ ] **Step 9.4: Report CC delta**

Run:
```bash
python -m radon cc semantic/ -a -s 2>/dev/null | tail -3
```

Report new average CC (was 4.8 project-wide with hotspot skewing). Target: all routing files average ≤ 8.
