# Work Record — add-historical-lookup-reuse-funnel

Task branch: `feat/add-historical-lookup-reuse-funnel`
Roadmap item: `roadmap/features/add-historical-lookup-reuse-funnel.md`

<!-- agent-workflow:start -->
**Outcome:**
On a fresh local Pallium install, real agent usage produces the Phase-1 reuse KPI. Every `pallium_search_history` call persists a lookup event (unconditionally, not gated on `audit_log_enabled`) carrying exposed source ids + raw ranks + fusion score + session/agent/container identity; every `pallium_expand_source` persists an expansion event carrying `parent_lookup_id`. `load_events_from_storage` reconstructs eligible sessions + loads events so `python -m evals.historical_lookup_measurement --db <db>` returns a non-empty, empty-data-safe rollup (reuse-per-100-eligible, rungs 1–2, Wilson intervals, supporting rates). A retrospective sampled judge emits rung labels + the user-directed-vs-agent-decided split + inter-rater κ. The funnel is armed by default on install and `pallium service status` reports whether it is armed.

**Target:**
Pallium repo. Guarded surfaces: `storage/` (new event tables), `core/query.py` + `core/service.py` (lookup/expansion persistence hooks), `app/cli/` (install config seeding + status health check), `app/config.py` (default). Non-guarded: `evals/historical_lookup_measurement.py` (loader), a judge harness under `evals/`, `pallium.example.toml`, runbook doc.

**Scope:**
1. New persisted lookup-event + exposures table(s) in `storage/`, written unconditionally by the historical-lookup path. 2. Expansion-event persistence carrying `parent_lookup_id`. 3. `load_events_from_storage` implementation (eligible-session reconstruction + event load) feeding `compute_reuse_rollup`. 4. Retrospective sampled judge harness (reuse anchor_probe protocol + eval_common providers). 5. Local enablement: unconditional event persistence + arm `[observability]` by default + `pallium service status` health check. 6. Runbook doc + visibility-violation reporting format in rollup output.
MAY NOT touch: the lookup/expansion *retrieval behavior* (scoring, source_only semantics) beyond adding a persistence hook; agent guidance/skills (separate feature `add-agent-historical-lookup-exposure`); dashboard surfacing (separate feature).

**Constraints:**
Lookup-event persistence must be UNCONDITIONAL (not gated on the legacy `audit_log_enabled`). Rollup must remain empty-data-safe (no events → valid empty rollup, no crash). No regression to existing retrieval behavior or existing metrics. Visibility/redaction/forgotten invariants must hold for persisted event data. No internal or external product names in any committed artifact. Persistence schema must follow the repo's existing table-declaration/creation pattern (no ad-hoc migrations).

**Completion criteria:**
Maps to the feature's "Done When" 1–6: (1) fresh install persists lookup + expansion events with the required fields; (2) `python -m evals.historical_lookup_measurement --db <db>` returns non-empty rollup with Wilson intervals + supporting rates, still empty-safe; (3) judge harness emits rung-1/2 labels + user-directed-vs-agent split + κ; (4) visibility-violation report emits 0 violations with attempted-disallowed-access counts; (5) `pallium service status` reports funnel-armed state; (6) runbook documents enable/use/read-KPI. Plus: `python -m pytest tests/ -q` green (modulo the known-benign `test_config.py::test_prompt_variants_legacy_fallback_unaffected`).

**Risk:** High

**Complexity:** Large

**Reason:**
Redline: touches red persistence surface (new tables in `storage/`) and `core/service.py` (architecture-review RED — orchestrator wiring). High because persistence is a contract/persistence surface. Large because it spans storage + core + cli + evals + a judge harness as independently-verifiable outcomes, likely across 2 PRs.

**Discovery:**
Pending — read-only seam-mapping agent in flight (rollup contract, storage table pattern, lookup/expansion path, config seeding, judge reuse, test fixtures). Findings recorded under `## Discovery` before the Plan is finalized.

**Material assumptions:**
- A1: `compute_reuse_rollup` already defines the event/rung shape the loader must produce. Disproof: rollup expects a different shape than the feature describes. Action: conform the persisted schema to the rollup's actual contract, note the deviation.
- A2: `storage/` has a single declarative table-creation pattern (à la `MetricRecord`) a new table can follow without a migration framework. Disproof: discovery finds a migrations dir / versioned schema. Action: follow that mechanism instead.
- A3: the historical-lookup path in `core/` has a single choke point where an unconditional persist hook can live without changing retrieval behavior. Disproof: persistence would require reshaping the query flow. Action: re-plan / re-classify.

**Plan:**
Pending — written after discovery, then sent for a clean-context plan review (High risk). Likely 2 PRs: (a) funnel persistence + rollup loader + judge; (b) local enablement (arm-by-default + status health check) + runbook.

**Verification plan:**
Pending — each completion criterion → method (unit tests for the new storage records + loader; an e2e assertion ingest→search_history→expand→events-persisted→non-empty rollup; empty-data-safe test; visibility/forgotten invariant tests; manual `pallium service status` check). Finalized with the Plan.

**Plan review:**
Pending — clean-context subagent review required (High risk). Reference recorded here once complete.

**Approvals:**
Approved by user 2026-08-14: "ok, so continue on all the features design, including the tool registration feature, then go into a nightly developemrn process. you have my ok for high risk changes"

**Exceptions:**
—

**State:** Blocked
<!-- agent-workflow:end -->

## Implementation

Planning in progress. Discovery agent in flight; Plan + Verification plan + clean-context Plan review are pending before any code edit. Standing High-risk approval is recorded above (overnight package mandate). State is `Blocked` only in the sense of "in planning, not yet Ready to implement"; it will flip to `Ready to implement` once the Plan and Plan review are written, then to `Ready for review` after implementation + verification.

Next agent, do first: read `## Discovery` (once populated) and the Plan; do not edit code until State is `Ready to implement`.
