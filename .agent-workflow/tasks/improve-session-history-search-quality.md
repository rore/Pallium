<!-- agent-workflow:start -->
**Outcome:** Session History returns and presents earlier work more usefully under a bounded real-usage study, with the smallest supported improvement shipped or a traceable no-change recommendation when no safe improvement is supported.

**Target:** Pallium Session History.

**Scope:** This Work Record; uncommitted read-only research under `.local/`; `docs/reports/session-history-search-quality-study.md`; and, only if the fixed holdout passes once, a presentation-only change in `retrieval/common.py` with focused existing caller/regression/E2E tests. API, app, core, storage, integration guidance, Relay registry/dashboard, and session-to-work association changes are excluded.

**Constraints:** Preserve exact-work scope, visibility/authorization, redaction/forgetting/retention, stale-history caution, derived-packages-disabled operation, and the retrieval-is-not-use invariant. Zero paid model calls unless a human approves a ceiling. Do not change/restart the live service, write to the private corpus, or commit private transcripts/IDs/raw reports. Compare an unchanged baseline at equal stated result/token budgets and separate current-corpus replay, historical exposure, candidate recovery, agent-visible evidence sufficiency, and downstream effect.

**Completion criteria:** A bounded report records serving state, sampling/exclusions/provenance, failure taxonomy, costs, counterexamples, and separate candidate-recovery/evidence-sufficiency/token/latency results; the smallest justified change (or explicit no-change recommendation) has reproducible development and independent holdout evidence; changed caller behavior has representative success plus miss/no-answer/near-match, exact-scope, old-untagged/new-tagged, Unicode, bounds, duplicate, expansion, and forgotten-source E2E coverage.

**Risk:** Elevated

**Complexity:** Moderate

**Reason:** Clean-context redline reassessment classifies the narrowed presentation-only scope gray+watch with no boundary, API, schema, security, or runtime-config flag. Elevated is conservative because `retrieval/common.py` is shared production code; Moderate complexity reflects empirical study plus independent holdout verification.

**Discovery:** Base is `origin/main` `0dbb0691`. The healthy vector-enabled live service serves clean `C:\Dev\rore\Pallium-installed` at `94934667`; relevant history-search files are identical to the branch, derived memory is disabled, and the queue is healthy. Read-only telemetry has 336 delivered lookups (94 sessions, 13 containers, 296 distinct query texts), 230 expansions, 14 exact-work lookups, and 61 no-answer results; 52 lookups span the latest three days. Of 749 distinct exposed sources, 707 exceed 240 characters, which establishes truncation exposure only—not a failure rate; 464 carry work metadata and 273 do not, and 175 lookups have linked expansion. Directly linked requests cover Codex well and Claude sparsely, no OpenCode; no recorded query is non-ASCII. `build_excerpt` truncates lexical/vector callers at the 160-character default; MCP can only re-bound that already-truncated excerpt to an upper bound of 240. Current broad/exact MCP tools share `/query`, exact SQL membership, visibility filtering, earliest-query-token excerpts, bounded response shaping, and linked expansion telemetry. Broad MCP/client defaults drift (3 versus 5). Redline found no boundary violation and noted AGENTS/policy drift for `core/query.py` outside the narrowed scope.

**Material assumptions:** (1) The serving process and stable-checkout revision remain unchanged during sampling; disprove by process/health/revision recheck, then restart the baseline inventory. (2) The corpus contains enough independent real tasks for a 30–50 lookup inventory and 10–15 deep cases; disprove by metadata inventory, then reduce the sample and report exclusions rather than manufacture independence. (3) A useful improvement can avoid Relay-owned surfaces and likely avoid HTTP contract changes; disprove if traces isolate the defect there, then coordinate ownership and repeat risk/plan review. (4) Local deterministic replay and human inspection can answer the first milestone without paid judges; disprove only by a named unresolved judgment that cannot be checked locally, then request a finite call/token ceiling.

**Plan:** Use existing `app.snapshot.create_snapshot` to make a validated paired SQLite snapshot under ignored `.local/`; never copy live SQLite/WAL files directly, and replay only in isolated storage. Freeze 48 delivered lookups (all 14 exact-work plus 34 stratified broad) and split by requesting session into 36 development/12 unopened single-use holdout cases; require at least 10 no-answer plus tagged/untagged, linked/unlinked request, expanded/unexpanded, old/recent, result-count, long-source, and available Codex/Claude strata. Score sufficiency only where originating request context supports a predeclared needed fact/qualifier; other cases remain descriptive. Deeply inspect 12 ambiguous development cases, then prototype one deterministic candidate using development data only: at each caller's existing `max_length` (160 upstream; MCP remains only an upper bound on already-truncated text), choose a truthful stored-text window by query-term density, preserve ellipses, and never change `MAX_EXCERPT_LENGTH`, source payloads, result IDs/order/scores/count, scope, provenance, stale-history warning, or expansion. Grade paired actual MCP output on predeclared evidence sufficiency—not term coverage—and challenge dense distractor/checklist/progress passages, sparse/paraphrased answers, and corrections/negation/conditions just outside the window. Run the fixed holdout once; do not tune on it. Report current-corpus replay separately from historical exposure, and candidate recovery separately from visible-evidence sufficiency, characters, latency, and unmeasured downstream effect. Absolute pre-measurement latency gate: p95 <= 5 ms and max <= 20 ms per helper call on observed p50/p90/max source and query lengths, with bounded runtime on adversarial long inputs. If the candidate misses any zero-material-regression gate, ship report-only/no-change. If it passes, edit only `retrieval/common.py`, targeted `tests/test_retrieval_common.py`, and existing lexical/vector/MCP caller E2E where coverage is missing; cover short, single-term, no-match, Unicode casefold, max/over-max, ellipses, and adversarial truth conditions. No scope expansion without reassessment.

**Verification plan:** Bounded report completeness and honest measurement labels → manual checklist review against roadmap Done When 1–4. Preserved candidate recovery/no-answer/exact-scope behavior → exact ID/order/count equality across development and single-use holdout replay at unchanged 160/240 caller budgets. Agent-visible evidence truth/sufficiency → predeclared request/source facts and paired actual MCP excerpts with wins/ties/losses, including dense distractors, sparse paraphrases, and nearby correction/negation/condition cases. Character/expansion budgets → existing MCP formatting and bounded expansion E2E with measured returned/expanded characters. Latency → helper benchmark at observed and adversarial bounds must meet p95 <= 5 ms and max <= 20 ms. Shared-caller behavior → focused `test_retrieval_common`, lexical, vector, history presentation/search tests for short/single/no-match/Unicode/casefold/bounds/ellipses, then affected subsystem and one full `python -m pytest tests/ -x -q`. Governance/no accessibility writes → diff inspection, audit-state regression, redline and agent-workflow checks.

**Plan review:** Pending architect response and clean-context agent review of this narrowed production plan.

**Approvals:** Not required at this risk level.

**Exceptions:** —

**State:** Blocked
<!-- agent-workflow:end -->

## Implementation

- 2026-09-09: Established isolated worktree/branch, read the roadmap and retrieval/eval invariants, verified serving checkout/config/index/queue health read-only, mapped the current search/expansion flow, and completed conservative pre-edit redline classification.
- 2026-09-09: Architect approved the zero-paid-call study and local prototype with corrected 160-character upstream budget, truth/sufficiency rubric, validated paired snapshot, single-use holdout, shared-caller coverage, and absolute latency gates. Production edits remain blocked pending clean-context plan review.

## Evidence

- First-milestone evidence will remain under `.local/` until reduced to a public-safe report. No private corpus text or identifiers will be committed.

## Result review

- Pending.
