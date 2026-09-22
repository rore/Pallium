<!-- agent-workflow:start -->
**Outcome:**
Agents repair and continue Session History retrieval without repeating delivered evidence, and an anonymized deterministic replay reports navigation/presentation cost and required-evidence recovery without overstating the measured layer.

**Target:**
Pallium.

**Scope:**
Session History retry and continuation guidance in `integrations/{claude-code,codex,opencode}/skills/pallium-memory/SKILL.md`, `integrations/{codex,opencode}/AGENTS.md`, `integrations/claude-code/claude_md_block.py`, and `integrations/opencode/.opencode/command/pallium-memory.md`; the deterministic replay entry point `evals/history_pull_decision/replay.py`; focused coverage in `tests/test_history_pull_decision_harness.py`, `tests/test_guidance_budget.py`, and `tests/test_history_guidance_replay_e2e.py`; `docs/claude-code-integration.md` and `docs/codex-integration.md`; and roadmap slice 6.

**Constraints:**
Add no production API, store, retrieval/ranking behavior, dependency, automatic query rewriter, or generated recap service. Reuse existing search paging, expansion continuation, and parent lineage. Preserve privacy, visibility, forgetting, historical-state warnings, and the rule that retrieval alone never changes accessibility or ranking. Bound retries, keep guidance within existing byte ceilings, verify current-state claims separately against live state, and label the replay as navigation/presentation evidence unless an agent actually performs the downstream task.

**Completion criteria:**
1. Supported skill copies, global guidance, the OpenCode command, and integration docs consistently tell agents to keep a delivered-page ledger across query repair, retry the same failed page, continue only unread pages, bound retries, preserve lookup lineage, and verify current state live.
2. One anonymized deterministic replay compares a restart-from-zero baseline policy with the revision-aware ledger policy against identical fixtures, query sequence, and candidate windows through the real MCP search and expansion tools. Both arms recover the same required-evidence oracle; the ledger arm has no missing content and no repeated successfully delivered expansion page for an unchanged source revision. A completed source recurring after query repair is revalidated with a terminal probe at its recorded total length and prior content revision. An unchanged revision stays complete; a stale response resets and rereads the source; and for a prior empty source probed at offset zero, a successful response with a different revision becomes the first delivered page of the new source version and resets progress without discarding that page.
3. Each arm reports searches, search-result pages, candidate occurrences, unique candidates, exact-repeat candidates, expansion attempts, successfully delivered expansion pages, repeated delivered expansion pages, returned Unicode characters, elapsed latency, and required evidence recovered. Cost differences are explained; latency is observational only; both arms are labeled `navigation/presentation`, never candidate-recovery, injection-precision, or downstream-task-effect.
4. Only a successfully delivered page advances the ledger. A failed delivery retries the identical request at most twice; a repaired query retains successfully delivered source progress; an unchanged recurring source continues its first unread offset; a stale result revision restarts that search window; and a stale/equal-length-changed content revision resets source progress for the new revision. At most two query repairs are attempted. Transport failures allow two retries after the initial call. Stale result revisions allow two restarts per query window, and stale content revisions allow two restarts per source; each repeated stale response consumes that budget. Exhaustion reports unrecovered evidence without silently skipping content.
5. The roadmap and shipped guidance agree, focused and affected tests pass, known failures are rerun, the full non-slow suite passes once, and clean-context result review has no unresolved findings.

**Requirement baseline:**
{"source":"roadmap/features/fix-session-history-evidence-access.md#6-tighten-retry-guidance-and-run-the-end-to-end-replay","outcome":"Update all supported Pallium-memory skill copies consistently so agents reuse lookup lineage, remember completed source pages during query repair, continue unread pages, bound retries, and separate a historical recap from live verification. Re-run one anonymized deterministic version of the observed recap.","scope":"Guidance and deterministic end-to-end replay for Session History retry, continuation, cost, and required-evidence recovery.","constraints":"Default to deterministic fixtures and zero paid model calls; do not add production retrieval-model work; report the measured layer honestly; preserve visibility, forgetting, and historical-versus-live-state semantics.","completion_criteria":"The anonymized replay reports exact-repeat and expansion cost before and after without claiming candidate recovery, injection precision, or downstream task effect unless measured; documentation, skill templates, roadmap state, and shipped contract agree."}

**Risk:**
Elevated.

**Complexity:**
Moderate.

**Reason:**
Agent Redline classifies the integration guidance paths as gray and the docs, evals, tests, and roadmap as blue, with no boundary violation or mandatory checkpoint. The change synchronizes several guidance surfaces and adds a deterministic multi-step replay, but deliberately avoids production code.

**Discovery:**
- Existing MCP contracts already provide frozen search paging (`result_offset`/`result_revision`), expansion continuation (`content_offset`/`content_revision`/`next_offset`), and `parent_lookup_id`; no production primitive is missing.
- All three installed skill copies are byte-identical and currently describe only one search followed by expansion. Global guidance, the OpenCode command, and integration docs omit a delivered-page ledger, bounded repair/retry, and unread-page continuation. `docs/session-history.md` already documents continuation/revisions and its historical-evidence warning already requires separate live verification; this slice aligns the integration guidance to that existing contract rather than inventing it.
- `evals/history_pull_decision/harness.py` performs one search and at most one expansion. Its current behavioral metrics do not measure query repair, paging, exact repeats, returned characters, latency, or required-evidence recovery.
- Existing caller-surface paging and diagnostics E2E coverage belongs to earlier slices. This slice should reuse those contracts and add only the missing deterministic caller-efficiency replay and guidance contracts.
- Redline pre-edit classification: `integrations/**` gray; `docs/**`, `evals/**`, `tests/**`, and `roadmap/**` blue; no API, persistence, security, runtime-config, watch-path, or dependency checkpoint applies. Gray paths must be explicit in the pull request.

**Material assumptions:**
1. Existing MCP paging and lineage contracts suffice. Disproved by the real-MCP replay being unable to express a required search/expansion step through current tool inputs or outputs; if disproved, stop implementation and return to planning instead of changing production APIs in this slice.
2. Guidance fits existing byte ceilings. Disproved by the guidance budget test after removing redundant prose; if disproved, tighten wording rather than raising caps unless separately replanned.
3. A deterministic adapter can replay the navigation behavior without paid model calls. Disproved if task completion itself must be judged; if disproved, keep the report at navigation/presentation evidence and do not claim downstream-task effect.

**Plan:**
1. Add failing focused tests in `tests/test_history_pull_decision_harness.py` and `tests/test_guidance_budget.py` for revision-aware ledger state, partially read sources recurring after repair, more than two continuation pages, identical-request delivery retry, two-retry/two-repair exhaustion, equal-length revision change, lineage, duplicate/gap prevention, report fields/layer label, and synchronized guidance within existing budgets. Add `tests/test_history_guidance_replay_e2e.py::test_navigation_replay_compares_restart_and_ledger_over_real_mcp`, marked `@pytest.mark.slow`, which seeds identical anonymized fixtures for both policies and calls the real `pallium_search_history` and `pallium_expand_source` MCP tools over the in-process HTTP app; inject only a transport/delivery failure around the MCP call.
2. Implement the smallest deterministic replay driver in `evals/history_pull_decision/replay.py`, with a restart-from-zero baseline policy and a revision-aware ledger policy. Search-page state is keyed by query/window revision and offset; expansion state is keyed by source, content revision, and offset. Preserve the lookup ID from the exact search page that supplied each anchor. Successfully delivered pages alone advance state; retry identical failed arguments; on stale search revision restart that window, and on stale content revision restart the source under its new revision. When a completed source recurs, issue a terminal probe at the recorded `content_total_chars` with its prior revision: an unchanged revision returns no new content, while a stale response consumes the source restart budget before rereading from offset zero. Compare the revision even on a successful probe: for prior length zero, a changed revision may return the new first page instead of a stale error; reset progress and consume that page normally. Partially read recurring sources continue at their first unread offset, which performs the same revision check. Use `time.perf_counter()` and stdlib collections only; do not change production code or add dependencies.
3. Update the three skill copies, `integrations/claude-code/claude_md_block.py`, both integration `AGENTS.md` files, the OpenCode command, `docs/claude-code-integration.md`, and `docs/codex-integration.md` in lockstep; retain all existing safeguards and byte ceilings.
4. Run focused tests while editing, affected Session History/eval tests after the coherent change, `--lf`, and the full non-slow suite once. Update roadmap slice 6 with exact measurement-layer wording only after evidence passes.
5. Obtain clean-context result review, resolve every finding, open a pull request that calls out gray integration paths, wait for required checks/reviews, merge, and verify the installed service only if runtime code or installed guidance deployment requires it.

**Verification plan:**
- Criterion 1: guidance-parity and byte-budget tests inspect every supported surface and assert ledger, bounded retry, continuation, lineage, and live-verification rules.
- Criteria 2–4: focused deterministic replay tests cover empty/one-hit/repeated-hit repair, partially read source recurrence, identical failed-page retry, two bounds, stale/equal-length revision restart, more than two expansion pages, Unicode/escaped content, retry exhaustion, page-specific parent lineage, idempotence, and no duplicate/gap. The slow real-MCP comparison must show both policies recover the exact evidence oracle while the ledger arm repeats no successfully delivered unchanged expansion page and returns no more content than baseline. Focused tests cover completed-source terminal revalidation for unchanged and equal-length changed content, empty-to-empty and empty-to-nonempty recurrence, partially read recurrence, and exhaustion of both result- and content-stale restart budgets.
- Existing production contract evidence credited rather than cloned: `tests/test_mcp_integration.py::test_mcp_history_source_continuation_real_http_lifecycle` covers expansion paging, retries, Unicode, exact/over-end, stale/missing/unauthorized/forgotten lifecycle, lineage, and unchanged memory state; `tests/test_mcp_integration.py::test_mcp_history_result_pages_cover_fifty_hits_with_fresh_audit_lineage` covers >2 result pages, frozen order, fresh per-page lookup lineage, stale scope, forgetting, and unchanged memory state; `tests/test_work_history_contract.py::test_history_paging_validation_happens_before_http`, `::test_stale_history_revision_does_not_finalize`, `::test_history_later_page_retry_is_stable_with_fresh_lookup_ids`, and `::test_equal_length_visible_change_stales_without_finalizing` cover limits/offsets, failed/stale delivery, later-page retry, and equal-length changes. Existing source-context visibility and diagnostics E2E remain authoritative for authorization/redaction.
- Criterion 3: serialize and assert both policy reports, metric definitions, evidence-oracle result, and `navigation/presentation` label; reject candidate-recovery, injection-precision, and downstream-task-effect claims. Latency has no pass/fail threshold.
- Criterion 5: run `python scripts/agent-workflow-check.py --repo-root . --slug history-guidance-replay`, focused tests, the named existing MCP/contract E2E nodes, the full replay with `python -m pytest tests/test_history_guidance_replay_e2e.py::test_navigation_replay_compares_restart_and_ledger_over_real_mcp -q -n 0 -m slow`, affected subsystem tests with `python -m pytest tests/test_history_pull_decision_harness.py tests/test_guidance_budget.py tests/test_mcp_integration.py tests/test_work_history_contract.py -q -n 0`, `python -m pytest --lf --lfnf=none -q -n 0`, Import Linter, the full non-slow suite once, and clean-context exact-HEAD result review; record commands and outcomes below. Verify an ordinary MCP search/expand call changes neither accessibility/ranking nor memory state through the named E2E assertions, then separately verify a current-state claim against live repository/service state rather than History.
- Significant risk: inspect the final diff for production code, public signature, new dependency, visibility/forgetting, and retrieval-state changes. Any such change invalidates this plan and requires reclassification.

**Plan review:**
Clean-context review at `ad34f75f` did not approve: it required the actual MCP surface, explicit before/after policies and acceptance conditions, revision-aware ledger semantics and concrete retry bounds, a concrete path/check inventory, slow-replay execution, unchanged-state evidence, and correction of the existing `docs/session-history.md` safeguards. The revision at `780e3f0c` addressed those findings but re-review still required completed-source revision revalidation, bounded stale restarts, and exact replay/test/doc paths. The revision at `1e9ffc33` addressed those findings except the offset-zero empty-source revision case. This revision compares successful probe revisions and consumes a changed first page; re-review pending.

**Approvals:**
Not required at this risk level.

**Exceptions:**
—

**State:** Blocked
<!-- agent-workflow:end -->

## Implementation

No implementation yet. `apply_patch` failed with the machine-local Windows CreateProcessWithLogonW 1327 error while applying plan-review corrections; the Work Record was rewritten deterministically as the explicitly named file.

## Evidence

Pending.

## Result review

Pending.
