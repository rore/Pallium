# Routing Module Decomposition

## Status

Proposal — not yet accepted.

## Problem

`semantic/agent_conversation_memory_routing.py` is 4,238 lines containing 36
module-level constants, 5 dataclasses, and 75+ functions. It currently owns every
concern in the query-routing pipeline:

| Concern | Approximate line range | Function count |
|---|---|---|
| Constants and dataclasses | 1–224 | — |
| Orchestrator (`route_query_results`) | 225–581 | 1 |
| Prefiltering (anchor + kind) | 583–779 | 4 |
| Intent inference and family scoring | 781–1027 | 4 |
| Candidate evidence scoring | 1027–1285 | 6 |
| Scoring, locality, specificity | 1285–1430 | 4 |
| Freshness and suppression shaping | 1430–1670 | 8 |
| Layer helpers and query-token utils | 1670–1845 | 7 |
| Trace building | 1845–2000, 2320–2340, 2725–2900 | 6 |
| Policy evidence and candidate evidence | 1883–2060 | 5 |
| Recall mode selection | 2055–2107 | 3 |
| Signal envelope derivation | 2109–2256 | 2 |
| Resolver invocation and ambiguity | 2258–2320, 2484–2700 | 7 |
| Lane narrowing | 2347–2482 | 2 |
| Injection block building | 2900–3430 | 14 |
| Sharp-candidate diagnostics | 3436–3590 | 1 |
| Work-resumption packaging | 3590–3790 | 7 |
| Final candidate selection | 3791–3970 | 4 |
| Routing focus and fallback | 3990–4238 | 7 |

### Why this matters now

1. **Cognitive load.** The file exceeds comfortable single-file comprehension.
   Adding a scoring tweak requires understanding prefilter, scoring, shaping,
   focus, packaging, and injection — all interleaved in one namespace.

2. **Merge friction.** Any two routing-related changes touch the same file and
   frequently conflict.

3. **Test coupling.** Test files already split by concern (lane narrowing,
   injection, recall, resumption, signals, constraints) but the code they test
   is not split. Refactoring tests is harder when every private function lives
   in the same module.

4. **Constant sprawl.** 36 module-level constants sit at the top of the file.
   Many are only consumed by a single concern (e.g., the 7 `WORK_RESUMPTION_*`
   constants are only used by the work-resumption packaging functions).

### What is NOT a problem

- The routing pipeline itself is well-structured sequentially. The orchestrator
  calls steps in a clear order.
- Existing extractions (anchors, constraints, resolver, threads, embedding)
  already demonstrate that the package can split without losing coherence.
- Test coverage is solid (631 passing, 5 skipped) and already partitioned by
  concern.

## Proposed Decomposition

Split the routing module into one orchestrator plus five concern modules, all
within the existing `semantic/` package. The naming convention follows the
existing pattern (`agent_conversation_memory_routing_<concern>.py`).

### Module map

```
semantic/
  agent_conversation_memory_routing.py           # orchestrator (shrinks to ~300 lines)
  agent_conversation_memory_routing_signals.py   # signal envelope + recall mode
  agent_conversation_memory_routing_scoring.py   # candidate scoring + shaping
  agent_conversation_memory_routing_selection.py # final selection + injection + diagnostics
  agent_conversation_memory_routing_policy.py    # lanes, policy family, resolver bridge
  agent_conversation_memory_routing_trace.py     # all trace/diagnostic assembly
  agent_conversation_memory_routing_constants.py # shared constants + dataclasses
```

### What goes where

#### `_routing_constants.py` — Shared constants and dataclasses

Everything that is consumed by two or more concern modules:

- All dataclasses: `PolicySelectedContext`, `LaneEligibility`, `LaneNarrowingResult`,
  `QuerySignalEnvelope`, `RoutingOverrides`
- Cross-cutting constants: `ROUTING_POLICY_NAME`, `ROUTING_HIGHER_LEVEL_TYPES`,
  `ROUTING_LOWER_LEVEL_EXACT_TYPES`, `ROUTING_SUMMARY_TYPES`,
  `ROUTING_PREFERRED_LAYERS`, `ROUTING_LAYER_WEIGHTS`,
  `ROUTING_SAFE_FALLBACK_LAYERS`, `ROUTING_SUPPORT_THRESHOLD`,
  `ROUTING_FAMILY_ALLOWED_ENVELOPE_KINDS`, `ROUTING_FAMILY_INFERENCE_PRIORITY`,
  `ROUTING_FALLBACK_MARGIN`, `ROUTING_FOCUS_BOOST`,
  `ROUTING_DEMOTED_HIGHER_LEVEL_PENALTY`, `HIGHER_LEVEL_RETRIEVAL_FLOOR`,
  `PASSTHROUGH_POLICY`
- Policy-layer constants: `QUERY_POLICY_FAMILY_ALLOWED_INTENTS`,
  `LATEST_STATUS_COLLAPSED_INTENTS`, `POLICY_WORK_STATE_USEFULNESS_THRESHOLD`,
  `POLICY_SUPPORT_THRESHOLD`, `AMBIGUITY_MARGIN_*`
- Lane-narrowing constants: `LANE_INTENT_MAPPING`, `LANE_POLICY_FAMILY_MAPPING`
- Recall mode constants: `RECALL_MODE_WEIGHTS`, `RECALL_MODE_FRESHNESS_BONUS`,
  `RECALL_MODE_FRESH_THREAD_PREFERENCE`
- Shared small helpers: `_routing_result_id`, `_result_layer`,
  `_routing_query_tokens`, `_routing_support_grade`,
  `_candidate_matches_thread`, `_candidate_matches_container`,
  `_candidate_thread_refs`, `_candidate_container_refs`,
  `_candidate_freshness_timestamp`, `_normalize_timestamp`,
  `_parse_iso_timestamp`, `is_query_topic_signal_empty`

Constants consumed by only one concern module move to that module (e.g.,
`WORK_RESUMPTION_*` constants move into `_scoring.py` alongside the packaging
functions).

#### `_routing_signals.py` — Signal envelope and recall mode

Current functions:

- `_derive_query_signal_envelope`
- `_check_evidence_trace_override`
- `_policy_family_from_signal_envelope`
- `_select_recall_mode`
- `_build_policy_evidence`
- `_policy_candidate_support_estimate`
- `_work_state_evidence_gate_passes`
- `_candidate_layer_dominance`
- `_compute_typed_candidate_evidence`

This module answers: "What kind of query is this, based on typed evidence?"

#### `_routing_policy.py` — Lane narrowing, policy classification, resolver bridge

Current functions:

- `_determine_eligible_lanes`
- `_classify_query_policy_family`
- `_build_ambiguity_options`
- `_build_latest_vs_resume_pair`
- `_maybe_invoke_resolver`
- `_apply_policy_intent_restriction`
- `_invoke_resolver_for_ambiguity`
- `_build_resolver_candidate_cards`

This module answers: "Which lane/policy family applies, and do we need LLM
disambiguation?"

#### `_routing_scoring.py` — Candidate scoring, shaping, and work-resumption packaging

Current functions:

- `_score_routed_candidate`
- `_locality_adjustment`
- `_specificity_bonus`
- `_higher_level_retrieval_floor_adjustment`
- `_candidate_evidence_shape_score`
- `_apply_same_kind_freshness_shaping`
- `_apply_fresh_thread_structured_recall_preference`
- `_apply_current_query_source_suppression`
- `_apply_recall_source_noise_suppression`
- `_apply_recall_structured_summary_suppression`
- `_apply_work_resumption_packaging`
- `_work_resumption_signal_types`
- `_work_resumption_usefulness_score`
- `_work_resumption_freshness_adjustment`
- `_is_thin_task_checkpoint_payload`
- `_candidate_matches_requested_locality`
- All `_source_noise_*`, `_structured_summary_*`, `_summary_low_value_*` helpers
- `_summarize_routing_layers`
- `_select_routing_focus`
- `_routing_focus_adjustment`
- `_infer_query_intent`
- `_query_family_query_shape_score`
- `_summarize_query_family_candidates`
- `_query_family_candidate_score`
- `_query_family_layer_metric`
- `_query_family_top_layer`
- `_candidate_has_rationale`
- `_candidate_has_explicit_evidence`

This module answers: "How should each candidate be scored and shaped?"

Work-resumption constants (`WORK_RESUMPTION_SIGNAL_TYPES`,
`WORK_RESUMPTION_THIN_CHECKPOINT_PENALTY`, etc.) move here because they are
only consumed by this module.

#### `_routing_selection.py` — Final candidate selection and injection

Current functions:

- `_select_final_candidates`
- `_select_compatible_recall_candidates`
- `_candidate_locality_compatible_for_packaging`
- `_build_injectable_blocks`
- `_build_injectable_block_from_candidate`
- `_task_checkpoint_injection_text`
- `_join_unique_text_parts`
- `_evaluate_same_thread_local_context`
- `_candidate_could_supply_external_carry_forward`
- `_candidate_qualifies_as_same_thread_local_state`
- `_candidate_is_injection_eligible`
- `_candidate_is_low_value`
- `_source_candidate_is_primary_injection_eligible`
- `_source_candidate_is_companion_injection_eligible`
- `_source_candidate_has_quote_grade_support`
- `_source_excerpt_disclaims_exact_evidence`
- `_query_requests_quote_grade_source`
- `_annotate_excluded_candidates`

This module answers: "Which candidates make it into the final result set and
injectable blocks?"

#### `_routing_trace.py` — Trace assembly and diagnostics

Current functions:

- `_build_routing_trace`
- `_build_routing_trace_entry`
- `_build_lane_narrowing_trace`
- `_build_signal_envelope_trace`
- `_build_kind_prefilter_trace_entry`
- `_build_anchor_prefilter_trace_entry`
- `_build_sharp_candidate_diagnostics`
- `_routing_reason`
- `_routing_strategy_name`
- `_routing_fallback_suffix`
- `_routing_packaging_suffix`
- `_query_family_label`

This module answers: "How do we explain what routing did?"

#### `_routing.py` (the existing file) — Orchestrator only

After extraction, the main file retains only:

- `route_query_results` (the pipeline orchestrator, ~300 lines)
- Prefilter functions that are tightly coupled to the orchestrator's flow:
  `_anchor_prefilter_candidates` and `_kind_prefilter_candidates`
- Re-exports for backward compatibility (public names like
  `route_query_results`, `RoutingOverrides`, `PolicySelectedContext`, etc.)

The orchestrator imports from the five concern modules and calls them in
sequence. Its structure stays the same — the decomposition moves function
definitions, not pipeline logic.

## Module Boundaries

### Dependency direction

```
routing.py (orchestrator)
  ├── routing_constants.py    (shared types + constants)
  ├── routing_signals.py      (imports constants)
  ├── routing_policy.py       (imports constants, signals)
  ├── routing_scoring.py      (imports constants)
  ├── routing_selection.py    (imports constants, scoring helpers)
  └── routing_trace.py        (imports constants; receives data, no domain logic)
```

Rules:

- `_routing_constants.py` imports nothing from routing modules (leaf dependency).
- `_routing_trace.py` imports only from `_routing_constants.py`. It receives
  pre-computed dicts and dataclasses — it does not call scoring or selection
  functions.
- No circular imports between concern modules. If a function is needed by two
  concern modules, it belongs in `_routing_constants.py`.
- The orchestrator is the only module that touches all concerns.

### Public API surface

The only public entry point remains `route_query_results()` plus
`RoutingOverrides` and the dataclasses. Tests may import private functions from
concern modules by full path (as they already do today), but the plugin file
(`agent_conversation_memory.py`) imports only from the orchestrator module.

## Migration Path

Incremental, one concern at a time, each landing as a standalone commit that
passes the full test suite. The order is chosen to minimize cross-concern
dependencies at each step.

### Phase 1: Extract constants and shared helpers

1. Create `agent_conversation_memory_routing_constants.py`.
2. Move all dataclasses, all module-level constants, and the shared small
   helpers listed above.
3. Update the orchestrator to import from the new module.
4. Add re-exports in the orchestrator for any names that tests import directly.
5. Run full test suite. Verify no import breakage.

**Risk:** Lowest. Only moves declarations; no logic changes.

### Phase 2: Extract trace assembly

1. Create `agent_conversation_memory_routing_trace.py`.
2. Move all `_build_*_trace*` functions plus `_routing_reason`,
   `_routing_strategy_name`, `_routing_fallback_suffix`,
   `_routing_packaging_suffix`, `_query_family_label`.
3. Update orchestrator imports.
4. Run full test suite.

**Risk:** Low. Trace functions are pure data transformers with no side effects.

### Phase 3: Extract signal envelope and evidence

1. Create `agent_conversation_memory_routing_signals.py`.
2. Move `_derive_query_signal_envelope`, `_check_evidence_trace_override`,
   `_policy_family_from_signal_envelope`, `_select_recall_mode`,
   `_build_policy_evidence`, `_policy_candidate_support_estimate`,
   `_work_state_evidence_gate_passes`, `_candidate_layer_dominance`,
   `_compute_typed_candidate_evidence`.
3. Update orchestrator and any cross-references from the policy module.
4. Run full test suite.

**Risk:** Low-medium. `_work_state_evidence_gate_passes` is called from both
signals and policy/lane-narrowing. It should live in constants or signals and
be imported by policy.

### Phase 4: Extract policy and lane narrowing

1. Create `agent_conversation_memory_routing_policy.py`.
2. Move lane narrowing, policy classification, ambiguity option building, and
   resolver bridge functions.
3. Update orchestrator imports.
4. Run full test suite — especially `test_routing_lane_narrowing.py` and
   `test_routing_query_signals.py`.

**Risk:** Medium. The resolver bridge does a lazy import of
`agent_conversation_memory_resolver`. That import must continue to be lazy
(it pulls in the LLM provider). Verify the lazy import path still works from
the new file location.

### Phase 5: Extract scoring and shaping

1. Create `agent_conversation_memory_routing_scoring.py`.
2. Move all scoring, shaping, freshness, suppression, work-resumption
   packaging, intent inference, and family scoring functions.
3. Move `WORK_RESUMPTION_*` and `SHARP_DIAGNOSTIC_MEMORY_TYPES` constants
   into this module (they are only consumed here).
4. Update orchestrator imports.
5. Run full test suite — especially `test_routing_recall.py`,
   `test_routing_resumption.py`.

**Risk:** Medium. This is the largest extraction. Functions like
`_candidate_evidence_shape_score` are called from both scoring and signal
modules. If that happens, the shared function should stay in constants or
signals. Audit cross-references before moving.

### Phase 6: Extract selection and injection

1. Create `agent_conversation_memory_routing_selection.py`.
2. Move final candidate selection, injection block building, and all
   injection-eligibility helpers.
3. Update orchestrator imports.
4. Run full test suite — especially `test_routing_injection.py`.

**Risk:** Low-medium. `_candidate_is_low_value` is used by both selection and
trace diagnostics. It should live in constants.

### Phase 7: Clean up orchestrator

1. Remove re-exports that are no longer needed (only keep those that external
   test files import).
2. Verify the orchestrator is ~300 lines and reads as a sequential pipeline.
3. Final full test suite run.

## Risk Assessment

### What could break

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Import cycles between concern modules | Medium | Blocks extraction | Strict dependency direction; audit before each phase |
| Test files that import private names from the old monolith path | High | Test failures | Add re-exports in orchestrator during migration; remove after all phases |
| Lazy imports (resolver) break from new file location | Low | Resolver path fails | Keep the lazy `from semantic.agent_conversation_memory_resolver import ...` pattern; test explicitly |
| Shared function used by two concerns missed during audit | Medium | Import error at runtime | `grep` for every moved function name across the whole file before deleting it from the old location |
| `RoutingOverrides` or dataclass moves break plugin import | Low | Plugin instantiation fails | Phase 1 adds re-exports; plugin import path tested in every phase |
| Performance regression from import overhead | Very low | Negligible | Python module imports are cached after first load; no measurable effect |

### What this does NOT change

- No pipeline logic changes. The orchestrator calls the same functions in the
  same order.
- No constant value changes. All thresholds, weights, and margins stay
  identical.
- No public API changes. `route_query_results` stays the only public entry
  point. The plugin file does not change.
- No test logic changes. Tests continue to call the same functions; only import
  paths may update (via re-exports during migration).

## Testing Strategy

### Per-phase verification

Each phase is a single commit that must pass:

```bash
python -m pytest tests/ -x -q
```

All 631+ tests, including the 6 routing-specific test files:

- `test_agent_conversation_memory_routing_constraints.py`
- `test_agent_conversation_memory_routing_injection.py`
- `test_agent_conversation_memory_routing_lane_narrowing.py`
- `test_agent_conversation_memory_routing_query_signals.py`
- `test_agent_conversation_memory_routing_recall.py`
- `test_agent_conversation_memory_routing_resumption.py`

Plus the benchmark:

- `test_memory_routing_benchmark.py`

### Import verification

After each phase, run a targeted import check to confirm no cycles:

```bash
python -c "from semantic.agent_conversation_memory_routing import route_query_results"
```

### Re-export audit

After Phase 7, search for any remaining direct imports from the old monolith
path that reference functions now living in concern modules. Any such import
should be updated to the new module path or kept as a re-export if it is in
a test helper used by multiple test files.

### Regression baseline

Before starting Phase 1, record the current benchmark results:

```bash
python -m pytest tests/test_memory_routing_benchmark.py -x -q
```

After Phase 7, re-run and confirm identical results. No routing logic changes
means benchmark numbers must not move.

## Alternatives Considered

### Single large refactor (big-bang)

Rejected. A single commit that moves 4,000+ lines risks hard-to-debug import
failures and merge conflicts with any in-flight routing work.

### Class-based decomposition

The functions could be reorganized into classes (e.g., `SignalDeriver`,
`CandidateScorer`). Rejected for now. The current functions are stateless and
composable. Classes would add indirection without clear benefit. If a concern
module grows to need internal state later, a class can be introduced within
that module.

### Fewer modules (3 instead of 5+1)

Combining signals+policy and scoring+selection into two larger modules was
considered. Rejected because the test files already split along the finer
boundaries, and the finer split keeps each file under ~800 lines.

### Moving routing into a sub-package (`semantic/routing/`)

Rejected for now. The existing naming convention
(`agent_conversation_memory_routing_*.py`) is consistent with the sibling
extractions (anchors, constraints, threads, resolver, embedding, memory).
A sub-package adds a directory level without clear benefit at the current
module count.
