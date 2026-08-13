# Task: add-historical-lookup-funnel-telemetry

P0 measurement contract for historical-lookup reuse (Pallium vNext Phase 0).
Execution context: `docs/designs/015-vnext-historical-work-execution.md` (P0 contract + Measurement model).

<!-- agent-workflow:start -->
**Outcome:**
A documented, defensible measurement contract for historical-lookup reuse exists (eligible-session denominator, retrospective judge protocol, three-rung reuse ladder, per-100 rollup formula, visibility-violation reporting format), plus the two reusable instrumentation primitives it needs: a client-visible `lookup_event_id` on the query response and an `agent_pull`/`mcp_pull` trigger_origin distinct from `user_explicit`. No event population yet (that ships with the P1 slice).

**Target:**
pallium

**Scope:**
`docs/specs/<new measurement-contract doc>`; `api/schemas.py` (add `lookup_event_id` response field); `api/routes.py` (add `agent_pull`/`mcp_pull` to trigger_origin allowlist; surface the id on the response); `core/service.py` (return the existing `query_audit_log` row id from the query path); `evals/` (per-100-eligible + three-rung reuse rollup skeleton); `tests/` (unit + E2E). NOT: new storage tables/columns, event population, raw search mode, MCP tool.

**Constraints:**
Existing `/query` and `/item-and-query` behavior unchanged except the additive `lookup_event_id` (typed `str | None`, `null` when the audit row was not written); `should_inject`/`injectable_blocks` unchanged; `agent_pull`/`mcp_pull` must NOT be added to `_TRIGGER_BYPASS_ORIGINS` (they take the normal routing path — verified: bypass set is a separate constant); no online opportunity/material-use classifier; `user_explicit` must NOT be reused for agent pulls; visibility semantics unchanged (no new exposure surface in P0); `api-stays-thin` boundary preserved (api imports only core); no internal/external product names in committed docs/tests.

**Completion criteria:**
1. When a client calls `/query`/`/item-and-query` (incl. debug variants) **with query-audit logging enabled**, the response shall include a `lookup_event_id` equal to the persisted `query_audit_log` row id; when audit logging is off, the field is `null` → E2E test (both audit-on and audit-off cases). **P0 scope = `lookup_event_id` on the response + the contract doc. P1 scope = the populated linked chain (exposures with source ids + ranks, expansion parentage, session/agent identity, subsequent-turn links).** This split satisfies the first clause of the ticket's Done When #1; the remainder is P1.
2. When a caller passes `trigger_origin=agent_pull` (or `mcp_pull`), the API shall accept and persist it distinct from `user_explicit`, and reject unknown origins → unit test.
3. A committed measurement-contract doc defines *substantive session*, *eligible session*, sampling, judge rubric + calibration, uncertainty, empty/abandoned handling, the three reuse rungs, the per-100-eligible rollup formula, retrospective directed-vs-decided labeling, and the visibility-violation reporting format → doc review.
4. The rollup skeleton computes per-100-eligible + three-rung breakdown from event inputs and is empty-data-safe → unit test on synthetic rows.

**Risk:** High

**Complexity:** Moderate

**Reason:**
Redline: red on `api/routes.py` + `api/schemas.py` (HTTP request/response contract → `api-review`) and `core/service.py` (orchestrator wiring → `architecture-review`); no boundary violation; no persistence/security surface. High per the contract-surface clause though the change is additive (new optional response field + additive enum values). Moderate: api + core + evals + docs + tests in one coherent slice, with measurement-definition uncertainty.

**Discovery:**
- `query_audit_log` row id is generated (`core/service.py:1195`, uuid4) and persisted (`write_query_audit_row`, `storage/sqlite.py:1124`) but is **internal-only** — `ItemAndQueryResponse`/`QueryResponse` (`api/schemas.py:325-331`, `:169-173`) do not return it.
- `trigger_origin` allowlist + validation at `api/routes.py:239-263`; `user_explicit` is defined-but-unemitted; no `agent_pull`/`mcp_pull`.
- `memory_usage_audit` is keyed on `memory_object_id` only (`storage/sqlite_schema.py:336-353`); **no raw source-exposure record anywhere** → exposure table + `parent_lookup_id` deferred to P1.
- `phase6_measurement.py` (`evals/injection_policy_2026_06/`) computes injection precision from `memory_usage_audit` + `memory_feedback`; **no session denominator / reuse funnel**. "substantive/eligible session" undefined in code (doc gap only).
- Subsequent-turn correlation is done at **eval time** via `(thread_ref, container_ref, created_at)` join — existing precedent (`storage/sqlite_schema.py:275`, subtask_selector_shadow); no stored FK. Adopted for turn linkage.
- Session identity = `thread_ref` = host `session_id` (Pallium never mints it); `agent_ref` is a hardcoded string on `source_items` only, not on audit rows.
- Migrations are inline ALTER/CREATE at startup (`storage/sqlite_schema.py:738-769`).
- `id_quote` citation handle is keyed on `memory_object_id` (`usage_audit_matcher.py:69`); raw source hits have no handle — kept optional/non-baseline per ticket.
- Judge scaffolding: `evals/anchor_probe/subagent_audit.py` + `evals/validation_runner.py` are the closest sampled-judge harness.

**Material assumptions:**
1. Assumption: the existing `query_audit_log` row id is a suitable, stable `lookup_event_id`. **Verified nuance:** the write is ordering-safe (row written before response) but is gated by `audit_log_enabled` (default False, `app/config.py:80`) and the id is currently dropped (`write_query_audit` returns `None`, `core/service.py:1106`). Resolution taken: return the id from the service seam; type the response field `str | None`; return `null` when audit is off. Disproof: returning the id forces a storage change or new cross-boundary import. Action: re-classify (persistence-review), re-plan.
2. Assumption: event population (exposure table, `parent_lookup_id`) can defer to the P1 slice without invalidating the contract (per design 015). Disproof: reviewer/user requires a populated chain now. Action: pull storage schema forward → re-classify (adds `persistence-review`), re-plan.
3. Assumption: eligible-session default (≥1 substantive user turn in a container with ≥N prior indexed source turns) is acceptable. Disproof: user rejects the shape/threshold. Action: revise doc definition; no code impact.
4. Assumption: eval-time turn linkage (join, not stored FK) is acceptable. Disproof: user/reviewer requires online linkage. Action: add stored linkage in P1 (persistence-review).

**Plan:**
Sequence:
1. Write the measurement-contract doc `docs/specs/2026-08-13-historical-lookup-measurement-contract.md`: definitions (substantive/eligible session), sampling plan, judge rubric + calibration + uncertainty, empty/abandoned handling, three-rung reuse ladder, retrospective directed-vs-decided labeling, per-100-eligible rollup formula, visibility-violation reporting format (with attempted-disallowed-access counts/types), and explicit non-goals. This is the gate deliverable and drives the code.
2. `api/schemas.py`: add optional `lookup_event_id: str | None` to `QueryResponse` (and `ItemAndQueryResponse` + debug variants). Additive, non-breaking.
3. `api/routes.py`: add `"agent_pull"`, `"mcp_pull"` to the trigger_origin allowlist; surface the audit row id into the serialized response.
4. `core/service.py`: return the `query_audit_log` row id from the query path so the API can read it (minimal orchestrator wiring; no new cross-boundary import).
5. `evals/`: rollup skeleton (extend `phase6_measurement.py` or new sibling `evals/historical_lookup_measurement.py`) computing per-100-eligible + three rungs from event inputs, reading current tables where available, empty-data-safe.
6. `tests/`: E2E asserting `lookup_event_id` on `/query` response equals the persisted row; unit for `agent_pull`/`mcp_pull` validation; unit for rollup math + empty safety.

Key conventions: trigger_origin allowlist + `_validate_trigger_origin` (`api/routes.py:239-263`); audit id at `core/service.py:1195`; `api-stays-thin` boundary; anonymized/domain-generic tests (AGENTS.md); every eval number labeled candidate-recovery vs injection-precision vs downstream-effect (`docs/context/lessons.md` invariant).

Target files: `docs/specs/2026-08-13-historical-lookup-measurement-contract.md`; `api/schemas.py`; `api/routes.py`; `core/service.py`; `evals/…`; `tests/…`.

Deviations: P0 telemetry is a deliberate contract straddle — storage schema and event population deferred to the P1 slice per design 015. Recorded as assumption 2.

**P1 carry-forward decision (from plan review):** the generic `/query` audit is gated by `audit_log_enabled` (default off), so P0's `lookup_event_id` is `str | None` on that path. The P1 *dedicated historical-lookup path* must persist its lookup event **unconditionally** (not gated on the legacy `audit_log_enabled` flag) — that is the path whose events feed the reuse funnel. The measurement-contract doc must state this requirement so P1 implements it.

Stop conditions: if surfacing the id requires storage-schema changes or a new cross-boundary import → stop, re-classify (persistence-review). If the query path an agent will use does not already write an audit row → stop, reconcile scope with P1.

**Verification plan:**
1. When a client calls `/query`/`/item-and-query` (incl. debug variants) with audit enabled, the response shall carry `lookup_event_id` == persisted row id; with audit disabled, the field shall be `null` → new HTTP E2E test covering both cases + debug variants.
2. When `trigger_origin=agent_pull`/`mcp_pull` is passed, the API shall accept and persist it distinct from `user_explicit`, rejecting unknown values → unit test (extend `tests/test_injection_policy_2026_06_phase4.py` pattern).
3. When the contract doc is reviewed, it shall contain all required sections with falsifiable definitions → clean-context doc review.
4. When the rollup runs on synthetic + empty inputs, it shall emit per-100-eligible + three-rung breakdown without error → unit test.
5. When the full suite runs, existing `should_inject`/`injectable_blocks` behavior shall be unchanged → `python -m pytest tests/ -x -q`.

**Plan review:**
Clean-context agent review completed — verdict APPROVE-WITH-CHANGES; both required changes incorporated (audit-flag nullable handling + P0/P1 completion-criteria split). See `## Plan review` below.

**Approvals:**
Approved by user 2026-08-13: "go" (approving the plan as recorded, including the audit-flag nullable resolution and P0/P1 completion-criteria split surfaced by the clean-context review).

**Exceptions:**
—

**State:** Ready for review
<!-- Implementation + verification complete; independent review findings addressed. -->
<!-- agent-workflow:end -->

## Implementation

- Code primitives (guarded, done by manager directly — small precise red-zone edits):
  - `core/service.py`: `write_query_audit(...)` now returns the audit row id (`row["id"]`); signature `-> str`.
  - `api/schemas.py`: `lookup_event_id: str | None` added to `QueryResponse` (inherited by `QueryDebugResponse`), `ItemAndQueryResponse`, `ItemAndQueryDebugResponse`.
  - `api/routes.py`: `agent_pull`/`mcp_pull` added to `_VALID_TRIGGER_ORIGINS` (comment notes they are deliberately NOT in `_TRIGGER_BYPASS_ORIGINS`); `_maybe_write_query_audit` returns `str | None`; `/query`, `/item-and-query`, and `/item-and-query/debug` surface the id as `lookup_event_id`. Uniform rule: id == persisted audit row, else `null` (`/query/debug` persists no row → `null`).
- Contract doc: `docs/specs/2026-08-13-historical-lookup-measurement-contract.md` — definitions (substantive/eligible session, N=50 default, eval-time join), event chain (P0 vs P1 table), three-rung ladder, judge protocol, empty-data-safe rollup formula, visibility-violation reporting format, non-goals.
- Delegated (Sonnet, in flight): API tests + reuse-rollup skeleton `evals/historical_lookup_measurement.py` + unit tests.

(pending: subagent test results, full-suite run, independent review)

## Evidence

- New tests: `tests/test_lookup_event_id_e2e.py` (20: E2E `lookup_event_id` == persisted row id on `/query` + `/item-and-query`; null when audit off; `/query/debug` writes no row → null; `/item-and-query/debug` persists a row when audit on → id; unit `agent_pull`/`mcp_pull` accepted, unknown → 400; guard: neither in `_TRIGGER_BYPASS_ORIGINS`) and `tests/test_historical_lookup_measurement.py` (23: three-rung per-100 math, empty-data safety, Wilson interval, per-session dedup, P1 loader stub). **43/43 pass** via the real interpreter.
- Full suite: `3377 passed, 1 failed, 15 skipped, 2 xfailed`. The single failure `tests/test_config.py::test_prompt_variants_legacy_fallback_unaffected` is **pre-existing and unrelated** (verified: it also fails with my tracked edits stashed) — config `prompt_variants` default drift, out of scope for this task.
- Two defects caught by the delegated API-test subagent and fixed before review: (a) `write_query_audit` had the `-> str` annotation but was missing `return row["id"]`; (b) `/item-and-query/debug` was not surfacing the id though it persists a row. Resolved to a uniform rule: `lookup_event_id` == persisted audit row id, else `null`.
- Command: `PYTHONPATH=".local/test-env/site-packages;." <cpython-3.13> -m pytest tests/ -q` (per `~/.claude/python-on-windows.md`).

## Plan review

Clean-context reviewer (fresh subagent, read the Work Record + ticket + design 015 + verified code claims). Verdict: **APPROVE-WITH-CHANGES**.

Per-probe verdicts:
1. **audit-id-as-lookup_event_id — WEAK.** Ordering is safe (row written before response on both paths). But `write_query_audit` returns `None` (`core/service.py:1106`) so the id is dropped today, and audit is gated by `audit_log_enabled` (default False, `app/config.py:80`; `/query` block at `routes.py:415`, `/item-and-query` early-return at `routes.py:275`). With audit off there is no row and no id. Required: define `lookup_event_id` behavior when audit is off. → Resolved: field `str | None`, `null` when off; completion criteria #1 reworded.
2. **The straddle — WEAK (delivery-disagreement risk, not architectural).** Deferring event population to P1 matches the ticket Notes and design 015, but ticket Done When #1 bundles the full linked chain; a reviewer would read P0 as failing it. Required: split completion criteria #1 into P0 (id on response) vs P1 (populated chain). → Resolved: split annotation added.
3. **eligible-session definition — SOUND.** Computable from existing `container_ref`/`thread_ref`/`role`/`created_at`; eval-time join precedent confirmed. Thresholds correctly deferred to the doc. Minor: doc must define the session boundary for "prior" turns.
4. **coupling risk — SOUND.** Bypass set `_TRIGGER_BYPASS_ORIGINS` (`semantic/agent_conversation_memory_routing_selection.py:57`) is separate from the validated allowlist; a new origin not added there takes the normal routing path — `should_inject`/`injectable_blocks` unchanged. Constraint added to lock this in.
5. **api-stays-thin — SOUND.** Returning the id is a pure return-value change; no new cross-boundary import; `core` does not import `api` (confirmed).
6. **Done When coverage — SOUND given the split.** Debug variants must also carry the field; E2E should cover them (verification plan #1 updated).

Both required changes applied to the marker block before requesting approval.

## Result review

Independent clean-context review (fresh subagent). Verdict: **PASS** on Done When
coverage (P0/P1 split honored, nothing overclaimed), no-coupling (agent_pull/mcp_pull
absent from `_TRIGGER_BYPASS_ORIGINS`; `should_inject`/`injectable_blocks` untouched),
guarded-edit correctness (all four endpoints wired; `write_query_audit` returns the id),
and contract-doc completeness. Issues found and **all addressed**:
1. (must-fix) `/item-and-query/debug` E2E asserted only non-null → added equality-to-persisted-row assertion.
2. (should-fix) reuse-ladder `measures` label was wrongly `injection-precision` for rungs 1–2 → corrected to `downstream-task-effect` for all three with a `claim` (observational/controlled) distinction, tethered to `docs/context/lessons.md`; doc + eval docstring + test updated.
3. (should-fix) added a `QueryDebugResponse` comment noting its `lookup_event_id` is always null.

Post-fix: `tests/test_lookup_event_id_e2e.py` + `tests/test_historical_lookup_measurement.py` = **43/43 pass**.

- **Session identity is integration-dependent (raised by user, 2026-08-13).** The
  contract originally equated *session* with `thread_ref`. That holds only for
  coding-agent integrations (host sets `thread_ref = session_id`, 1:1). For
  channel-threaded capture integrations, each reply-thread has its own `thread_ref`
  and the channel/container is the coarser "virtual thread" — so a conversation
  fragments across many `thread_ref`s and counting them as sessions would over-count
  the denominator. Contract updated: *session* is now defined abstractly with an
  integration-dependent key; the **P0 denominator is scoped to 1:1 integrations**
  (Experiment 1's target), and virtual-thread session-mapping is explicitly flagged
  out-of-scope, not silently mis-modeled. No code impact.
