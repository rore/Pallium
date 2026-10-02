<!-- agent-workflow:start -->
**Outcome:**
Agents can recover prior planning decisions from Session History despite competing automated turns, with regression evidence for the confirmed failure mechanisms.

**Target:**
Pallium Session History.

**Scope:**
Diagnose the reported planning-recall miss; implement the smallest generic retrieval or caller-guidance correction supported by it; add anonymized caller regression coverage; align the owning roadmap and documentation; review and deliver through PR and installed verification.

**Constraints:**
Preserve exact explicit filters, visibility, forgetting, redaction, source provenance and retrieval-is-not-use. No project-specific rankings, source IDs, phrases, private transcripts in Git, new model providers, paid evaluations, schema migrations or weakened protected tests. Existing production data is read-only. Reuse existing retrieval and test seams. At most two concurrent workers; inexpensive bounded implementation and independent consequential review.

**Completion criteria:**
Reproduce confirmed generic failure classes before fixes; verify improved candidate recovery or agent-visible evidence through the real caller surface and negative/lifecycle boundaries; distinguish recovery from downstream task accuracy; independent review accepted, full selected validation passed, roadmap reconciled, PR merged and installed service verified.

**Requirement baseline:**
{"source":"80bd2a80-eb38-4c1c-9ba2-6d9ca751db92","outcome":"Agents can recover prior planning decisions from Session History despite competing automated turns, with regression evidence for the confirmed failure mechanisms.","scope":"Diagnose the reported planning-recall miss; implement the smallest generic retrieval or caller-guidance correction supported by it; add anonymized caller regression coverage; align the owning roadmap and documentation; review and deliver through PR and installed verification.","constraints":"Preserve exact explicit filters, visibility, forgetting, redaction, source provenance and retrieval-is-not-use. No project-specific rankings, source IDs, phrases, private transcripts in Git, new model providers, paid evaluations, schema migrations or weakened protected tests. Existing production data is read-only. Reuse existing retrieval and test seams. At most two concurrent workers; inexpensive bounded implementation and independent consequential review.","completion_criteria":"Reproduce confirmed generic failure classes before fixes; verify improved candidate recovery or agent-visible evidence through the real caller surface and negative/lifecycle boundaries; distinguish recovery from downstream task accuracy; independent review accepted, full selected validation passed, roadmap reconciled, PR merged and installed service verified."}

**Risk:**
Elevated

**Complexity:**
Moderate

**Reason:**
Provisional GRAY retrieval/storage implementation, BLUE tests/report/roadmap; retrieval correctness and private evidence handling need independent review. Any API, model or persistence-contract change requires reassessment before edits.

**Discovery:**
The original planning exchange exists in non-forgotten source rows. The reported role=user query excluded assistant-authored planning by contract and its six delivered results were automated heartbeat messages. Other reported searches did not expose known sources on delivered pages; unread pages remain unclassified. Broad lexical search applies source filters after a globally limited BM25 pool; no automated-origin distinction is present. Exact mechanisms and useful minimal correction are being narrowed before implementation.

**Material assumptions:**
This inspected incident is development evidence, not an independent holdout. Fresh current SQL ranking is not exact replay of original hybrid results. Do not solve a caller filter mistake by overriding explicit scope. Do not assume suppressing automation is safe or that a vague query has one unique answer.

**Plan:**
1. Invoke Agent Workflow, record context and classify risk before code edits. Normal non-exempt branch/PR flow; runtime/tests are outside the documentation allowlist.
2. Finish bounded source/candidate diagnosis and select concrete paths, regression contracts, and minimal correction; obtain independent plan review before implementation.
3. Implement reviewed correction with red-before-green anonymized HTTP/MCP tests, preserving explicit-filter and source lifecycle boundaries. Lead owns roadmap/docs/record; delegated worker owns only named runtime/test paths.
4. Run focused tests, affected subsystem, whole-change selector and full non-slow suite once; independently review, resolve findings, merge and verify installed delivery. Reconcile roadmap and preserve private artifacts before retiring checkout.

Concrete correction for review: in storage/sqlite_search.py, reuse the existing exact-work bounded fetchmany cursor for all source-only lexical searches, continuing past rejected candidates until the requested eligible hit count or exhaustion. Keep source lifecycle/visibility/filter checks and BM25 order; stabilize score ties by index-entry ID and deduplicate target views across pages. Leave mixed/derived search unchanged. No numerical ranking changes and no heartbeat suppression. Add tests/test_history_planning_retrieval.py with anonymized HTTP filter-starvation, exclusion/lifecycle, exhaustion, tie and duplicate-view cases, plus real MCP planning-table/neighbor-acceptance recovery with automated user-role noise and explicit role=user negative. Amend all three integrations/*/skills/pallium-memory/references/history-replay.md copies: for conversational decisions use topic anchors, omit role unless authorship is explicitly requested, distinguish user role from human origin, expand neighbors for proposals/qualifications/approval, never infer missing ingestion from missed search results. tests/test_guidance_budget.py verifies parity/required guidance. Lead owns guidance/tests there, docs/session-history.md and roadmap/features/investigate-history-navigation-and-on-demand-compression.md; runtime/test worker owns only storage/sqlite_search.py and tests/test_history_planning_retrieval.py.

**Verification plan:**
- Confirmed failure and improvement -> anonymized red/green caller regression with negative scope and lifecycle cases.
- Preserved contracts -> existing relevant History E2E and protected behavior contracts through the selected test lane.
- Evidence limits and smallest scope -> clean-context plan/result review, no claims of held-out or downstream accuracy from this incident.
- Delivery -> whole-change selector, full non-slow suite, workflow/import checks, GitHub checks, installed revision and health verification.

**Plan review:**
Agent technical review: /root/planning_fix_review (clean-context Sol) approved concrete plan at 1d931b9f. Deduplicate source targets after eligibility, preserving strongest eligible text view; cover exhaustion and stable ties. Scripted MCP replay proves evidence recovery under the procedure, not agent adoption or downstream accuracy.

**Approvals:**
Approved by user 2026-10-02: "don't stop, improve this!" Existing authorization includes PR/merge according to repository guidelines. User separately authorized read-only direct database and cross-project inspection.

**Exceptions:**
—

**State:** Ready to implement
<!-- agent-workflow:end -->

## Implementation

Planning gate only; not awaiting renewed user approval. Branch feat/history-planning-retrieval at d993f639. Owning roadmap: roadmap/features/investigate-history-navigation-and-on-demand-compression.md; its earlier no-case preflight is now superseded for development diagnosis by a concrete authorized incident, not by recovered held-out evaluation provenance. The injected git-branch work reference concerns another task and does not identify this Work Record. No association inferred.

Independent design recommendation selected two distinct changes: caller-guidance correction addresses the observed role-filter miss; source-only lexical refill fixes the separately discovered global-candidate starvation boundary. Do not claim refill alone solves the reported heartbeat dominance. Automated history remains searchable, exact requested roles remain binding, and no preference weights are introduced. docs/context/eval-from-live-failures.md excludes clear reproducible bugfixes and documentation from its numerical-tuning research loop; use red/green caller reproduction here, not a new ranking experiment. Intended paths are GRAY storage/integration guidance plus BLUE tests/docs/record/roadmap, with no API/schema/protected-test changes or new dependency edges.

Concrete plan approved before implementation. Runtime/test worker owns storage/sqlite_search.py and tests/test_history_planning_retrieval.py; lead owns remaining named files and records worker evidence. Existing helpers may be imported rather than copied. Use the shared virtualenv interpreter; no provider calls or model downloads. Source scan batches are bounded, but total rejected rows scanned can reach exhaustion; do not claim constant latency.

## Evidence

Read-only SQLite incident inspection and existing caller source code. Initial diagnosis was outside workflow; user then explicitly expanded to implementation. Private source IDs and excerpts remain in chat/Relay, not this record.

## Result review

Pending.
