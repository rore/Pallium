# Reliable paired evaluation runner

<!-- agent-workflow:start -->
**Outcome:**
A small reusable evaluation runner is qualified before any further Session History model experiment. It executes complete baseline/candidate pairs against frozen isolated fixtures through Pallium's production search, formatting, and expansion path; persists auditable attempts and cost; resumes safely; and excludes transport-invalid pairs from quality claims.

**Target:**
Pallium repository evaluation tooling for Session History downstream-effect experiments.

**Scope:**
Add `evals/reliable_pair_runner.py` and `tests/test_reliable_pair_runner.py`; after implementation evidence, align `docs/benchmarks.md` and `roadmap/features/improve-session-history-search-quality.md`. This Work Record tracks the task.

**Constraints:**
No model/evaluator spend, new search variant, broad corpus inventory, gold grading, production service/runtime/plugin change, installed-state change, or live History/Relay mutation during infrastructure qualification. Use stdlib and existing dependencies only. Preserve exact-work scope, retrieval-only accessibility invariants, private corpus isolation, UTF-8, and honest measurement labels. Do not begin implementation until the architect approves the design; do not begin any experiment until the architect verifies the deterministic pilot.

**Completion criteria:**
1. A frozen pack containing configuration, cases, gold, and anonymized sources is hashed canonically; incompatible resume is rejected.
2. Each case completes baseline then candidate before the next case; durable per-attempt records preserve input, exact tool outputs, response, status, usage/cost, and scoring provenance.
3. Resume derives state from records and never repeats a durably completed call.
4. Only allowlisted safe read-only transport failures receive bounded retries with pre-reserved input-token budget; every attempt remains inspectable and unknown usage is charged conservatively.
5. Valid answer/abstention/product outcomes remain distinct from transport-invalid, interrupted, permanent-failure, and budget-skipped states. Reports calculate quality only for usable completed pairs and reconcile counts/cost with durable records.
6. A deterministic scripted pilot uses an isolated SQLite/ASGI app, real production search/expansion routes and MCP formatting, Unicode data, and the same driver seam intended for later model use.
7. Focused E2E tests cover complete pair, interruption/resume, transient and permanent transport failures, malformed or undelivered tool output, Unicode, duplicate prevention, frozen-pack mismatch, budget boundary/exhaustion, pair ordering, and report reconciliation.
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
- Assumption: a small callable driver seam is sufficient for both the scripted pilot and a later separately authorized model adapter. Disproof: the target transport cannot expose delivered tool-output bytes and usage metadata through that seam. Action: amend the design and re-approve before adding transport-specific code.
- Assumption: input-token ceilings can conservatively gate the next call while optional measured monetary cost remains report-only. Disproof: the authorized provider cannot expose or conservatively bound input usage. Action: do not run it.
- Assumption: planned changes remain within the listed blue-zone paths. Disproof: a production path or dependency must change. Action: reclassify, update this record, and repeat the required review checkpoint before editing.

**Plan:**
1. Invoke and follow the repository agent-workflow skill; record discovery, Routine/Moderate classification, and the design approval gate here before code.
2. Send the architect a concise design with exact reuse/new files and the acceptance command. Stop until approval.
3. Implement one eval-only runner module: canonical pack hashing; isolated production-surface search/expansion adapter; sequential pair state machine; atomic per-attempt JSON records; conservative input-token reservations; allowlisted retry classification; strict UTF-8/tool-delivery validation; and a derived reconciled report.
4. Add one focused E2E test module using a temporary frozen anonymized pack and deterministic scripted driver. Cover every completion criterion and injected failure mode without paid calls.
5. Run the focused test, affected subsystem tests, workflow checker, last-failure rerun if applicable, then the full test suite once.
6. Obtain an independent high-reasoning Sol review, address findings, rerun focused verification, and align benchmark docs, roadmap, and this Work Record.
7. Open a PR with measured pilot evidence and one explicit human gate: architect verification before any model experiment. Close the PR lifecycle only after required review and CI.

**Verification plan:**
- Criteria 1–7 -> `python -m pytest tests/test_reliable_pair_runner.py -q -n 0`.
- Exact production-path fidelity -> focused tests fail if real ASGI search/expansion or MCP formatter output differs; no hand-authored search response is accepted.
- Workflow -> `python scripts/agent-workflow-check.py --repo-root . --slug reliable-eval-runner`.
- Regression -> affected History/MCP test files, then `python -m pytest tests/ -x -q` once before review/PR.
- Review -> independent Sol review records actionable findings or explicit no-findings result.
- Closure -> PR checks green; report/doc/roadmap/Work Record agree that the pilot qualifies infrastructure only and no downstream effect was measured.

**Plan review:**
self; architect approval required by assignment before implementation

**Approvals:**
Not required at this risk level. Architect design approval and later pilot verification are explicit task gates, not High-risk workflow approvals.

**Exceptions:**
—

<!-- Ready to implement | Blocked | Ready for review -->
**State:** Blocked
<!-- agent-workflow:end -->

## Implementation

Not started. Waiting for architect approval of the design.

## Evidence

No pilot/model evidence yet. The prior failed trial is discovery evidence only and reported zero valid pairs.

## Result review

Pending.
