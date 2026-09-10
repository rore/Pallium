# Reliable paired evaluation runner

<!-- agent-workflow:start -->
**Outcome:**
A small reusable evaluation runner is qualified before any further Session History model experiment. It executes complete baseline/candidate pairs against frozen isolated fixtures through Pallium's production search, formatting, and expansion path; persists auditable attempts and cost; resumes safely; and excludes transport-invalid pairs from quality claims.

**Target:**
Pallium repository evaluation tooling for Session History downstream-effect experiments.

**Scope:**
Add `evals/reliable_pair_runner.py` and `tests/test_reliable_pair_runner.py`; after implementation evidence, align `docs/benchmarks.md` and `roadmap/features/improve-session-history-search-quality.md`. This Work Record tracks the task.

**Constraints:**
No model/evaluator spend, new search variant, broad corpus inventory, gold grading, production service/runtime/plugin change, installed-state change, or live History/Relay mutation during infrastructure qualification. Use stdlib and existing dependencies only. Preserve exact-work scope, retrieval-only accessibility invariants, private corpus isolation, UTF-8, and honest measurement labels. Gold is never passed to the chooser. No experiment begins until the architect verifies the deterministic pilot.

**Completion criteria:**
1. A frozen pack containing configuration, cases, gold, and anonymized sources is hashed canonically; incompatible resume is rejected.
2. Each case completes baseline then candidate before the next case; durable records preserve every search, expansion, and driver step with lookup lineage, input, exact tool output, response, status, usage/cost, and scoring provenance. Resume reuses completed steps.
3. Resume derives state from records and never repeats a durably completed call.
4. Only allowlisted safe read-only transport failures receive bounded retries. Input and output ceilings, pair completion, and retry allowance are reserved before a pair starts; insufficient budget yields cannot-start-pair. Every attempt remains inspectable, unknown cost is reported unknown, and indeterminate crash windows are charged conservatively.
5. Valid answer/abstention/product outcomes remain distinct from transport-invalid, interrupted, permanent-failure, and budget-skipped states. Reports calculate quality only for usable completed pairs and reconcile counts/cost with durable records.
6. A deterministic scripted subprocess pilot uses an isolated persistent run-directory SQLite/ASGI app, real production search/expansion routes and MCP formatting, Unicode data that crosses the process boundary, and a small interactive driver seam where the driver chooses expansions from search text. Expansion after restart retains correct lookup lineage.
7. Focused E2E tests cover a real runner-process interruption/restart in the same pack/state directory, the indeterminate crash-after-execution-before-persist window, transient and permanent transport failures, malformed or undelivered tool output, Unicode, no repeat of durably completed steps, frozen-pack/schema/type/attempt/budget validation, source/config mismatch, terminal invalid/all-invalid reporting, output and pair budget boundaries, ordering, and report reconciliation.
8. Independent Sol review, affected tests, repository workflow check, full `tests/` CI-equivalent suite, documentation/roadmap alignment, and a review-ready PR are complete.

**Risk:**
Routine

**Complexity:**
Moderate

**Reason:**
The diff is confined to blue-zone evaluation, test, documentation, roadmap, and workflow-record paths, with no production runtime or schema change. Complexity is Moderate because durable interruption recovery, budget accounting, and failure taxonomy require a nontrivial state machine.

**Discovery:**
Existing runners provide useful local patterns but no runner satisfies the requested contract. `evals/eval_common.py` offers common run IDs and JSONL/progress conventions, while its ID-only resume is insufficient. `evals/longmemeval_benchmark.py` has the strongest current result/report flow but writes after parallel work and lacks pair sequencing, attempt history, failure taxonomy, and reserved retry budget. `evals/real_corpus_pull_eval.py` shows usage extraction and pre-call reservation but only in memory. `evals/eval_rate_limiter.py` throttles requests, not spend.

The failed private trial at `.worktrees/history-budget-4000-trial/.local/history-budget-4000-trial` had zero valid pairs. Its `budget_ledger.py` demonstrated atomic replacement and reservations, but manual multi-script orchestration, reconstructed payloads, and stdout transport caused the observed failure. `trial_expand.py` persisted a Unicode expansion before Windows stdout encoding failed; a later attempt produced no readable tool output. Those artifacts are evidence to generalize, not code to copy or commit.

Production seams already exist: `PalliumMcpClient` calls the real History HTTP routes; `app.mcp.server._compact_history` and `_bounded_expansion` are the exact caller-facing formatters. `tests/test_search_history_tool.py` already demonstrates an isolated `create_app` + SQLite + `httpx.ASGITransport` pattern. Redline classification is blue-zone / no checkpoint for every planned path.

**Material assumptions:**
- Assumption: the existing ASGI client seam can exercise production search and expansion without a live service. Disproof: it cannot reproduce one of the MCP formatter inputs or lookup-linked expansion. Action: stop and return a design blocker rather than mock or reconstruct the response.
- Assumption: a small UTF-8 JSON-lines subprocess seam is sufficient for the scripted pilot and leaves a narrow future adapter boundary. Disproof: interactive expansion choice or usage metadata requires framework/runtime work. Action: stop rather than expand the runner; any future external adapter remains separately unqualified.
- Assumption: input-token ceilings can conservatively gate the next call while optional measured monetary cost remains report-only. Disproof: the authorized provider cannot expose or conservatively bound input usage. Action: do not run it.
- Assumption: planned changes remain within the listed blue-zone paths. Disproof: a production path or dependency must change. Action: reclassify, update this record, and repeat the required review checkpoint before editing.

**Plan:**
1. Invoke and follow the repository agent-workflow skill; record discovery, Routine/Moderate classification, and the design approval gate here before code.
2. Send the architect a concise design with exact reuse/new files and the acceptance command. Stop until approval.
3. Implement one eval-only runner module: canonical pack hashing and strict input validation; persistent isolated production-surface search/expansion state; a UTF-8 JSON-lines subprocess driver that chooses expansions; sequential pair state machine; atomic per-step/attempt records; input/output pair and retry reservations; explicit indeterminate/retry classification; and a derived reconciled report.
4. Add one focused E2E test module that is also the independently runnable deterministic pilot/driver. It creates a frozen anonymized Unicode pack, leaves inspectable records/report, performs real process interruption/restart, and covers every completion criterion without paid calls.
5. Run the focused test, affected subsystem tests, workflow checker, last-failure rerun if applicable, then the full test suite once.
6. Obtain an independent high-reasoning Sol review, address findings, rerun focused verification, and align benchmark docs, roadmap, and this Work Record.
7. Open a PR with measured pilot evidence and one explicit human gate: architect verification before any model experiment. Close the PR lifecycle only after required review and CI.

**Verification plan:**
- Criteria 1–7 -> `python -m pytest tests/test_reliable_pair_runner.py -q -n 0 -m slow`.
- Exact production-path fidelity -> focused tests fail if real ASGI search/expansion or MCP formatter output differs; no hand-authored search response is accepted.
- Workflow -> `python scripts/agent-workflow-check.py --repo-root . --slug reliable-eval-runner`.
- Regression -> affected History/MCP test files, then `python -m pytest tests/ -x -q` once before review/PR.
- Review -> independent Sol review records actionable findings or explicit no-findings result.
- Closure -> PR checks green; report/doc/roadmap/Work Record agree that the pilot qualifies infrastructure only and no downstream effect was measured.

**Plan review:**
self; architect approved implementation via app delegation on 2026-09-10 with corrections incorporated above: interactive expansion choice, honest indeterminate crash semantics, real subprocess restart, input/output pair reservation, strict validation, all-invalid reporting, and no experiment/merge/install.

**Approvals:**
Not required at this risk level. Architect design approval and later pilot verification are explicit task gates, not High-risk workflow approvals.

**Exceptions:**
—

<!-- Ready to implement | Blocked | Ready for review -->
**State:** Ready to implement
<!-- agent-workflow:end -->

## Implementation

Architect approval received 2026-09-10. Implementation is limited to `evals/reliable_pair_runner.py` and `tests/test_reliable_pair_runner.py` first; documentation, roadmap, and this record follow only after pilot evidence. No production path or dependency may change. `apply_patch` previously failed with Windows error 1327, so edits use the narrow deterministic replacement fallback allowed by local instructions.

The bounded Luna worker was stopped after producing no usable runner and an incompatible partial test draft; direct implementation avoided further coordination cost. The runner now uses an isolated persistent SQLite database, real ASGI search/expansion routes, direct production formatters, atomic per-step and per-attempt records, pair-first input/output reservations, explicit indeterminate crash recovery, and a minimal interactive UTF-8 subprocess protocol. The test module doubles as the independent scripted pilot/driver. Initial focused acceptance passed 20 tests. After independent review, focused acceptance expanded to 33 passing tests covering production-format truncation/finalization, exact-work parity, strict route and artifact-kind bounds, finite timeout/cost values, durable-key collisions, persistence-error separation, and mid-pair budget exhaustion. Fresh corrected pilot artifacts: `.local/reliable-pair-pilot-v4/state/report.json`; one usable scripted pair, zero invalid pairs, two completed attempts, 40 charged input tokens, 10 charged output tokens, USD 0.00. This qualifies infrastructure only.

A cheap deletion audit found only cosmetic helper inlining, which would not materially reduce the state machine, and one real crash-accounting gap. Search and expansion steps now persist started/completed attempts and convert a prior started step to indeterminate before safe read-only replay; driver reservations still begin only immediately before driver dispatch, avoiding false model charges for pre-dispatch tool work. The Sol result review found five blockers: deferred delivery/finalization parity, persistence errors misclassified as transport, normalized filename collisions, route-bound validation gaps, and a discarded budget-skipped state. The first five are addressed. Sol follow-up confirmed four closed and found two remaining validation edges: artifact-kind enum enforcement and finite timeout/cost values. Those are now addressed with focused regressions; final reviewer confirmation remains before review readiness.

## Evidence

Focused acceptance passed 20 tests in 59.43s. Independent affected-path verification passed the same 20 focused tests in 60.83s and 30 production History/MCP tests in 10.93s. The final deterministic no-model pilot at `.local/reliable-pair-pilot-v4/state/report.json` produced one usable pair, zero invalid pairs, two completed attempts, 40 charged input tokens, 10 charged output tokens, and USD 0.00. This is infrastructure evidence only; no paid model or evaluator call ran and no downstream quality was measured. Full non-slow regression at corrected revision `abf7c4cd` passed 4,835 tests with 33 skipped and 2 expected failures in 204.22s. Final validation-only changes then passed the 33-case focused suite in 72.21s. Import-boundary, redline, and workflow gates passed with Routine detected risk, no boundary violations, and no triggered review checkpoints.

## Result review

Independent Sol review found five blockers in be57bc1; the correction review confirmed deferred/finalized production parity, Windows persistence separation, collision rejection, and durable budget-skipped reconciliation, then identified artifact-kind and non-finite number validation edges. All findings have focused regressions and are addressed in the current implementation. Final no-findings confirmation is pending. Scope remains the approved eval/test/docs/roadmap slice, assumptions now match the production surfaces, and Routine/Moderate classification is unchanged.
