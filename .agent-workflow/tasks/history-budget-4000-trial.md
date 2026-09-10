# Task: history-budget-4000-trial

<!-- agent-workflow:start -->
**Outcome:**
Decide whether increasing the agent-facing raw-history search response budget from 2,000 to 4,000 characters improves frozen-source retrieval-answer success without baseline losses, safety regressions, or more than 25% aggregate search-plus-expansion text growth.

**Target:**
pallium

**Scope:**
Authorized execution: freeze the inventoried 15 cases, partition full-source gold across two isolated reviewers, classify before variant outputs, then run one paired 2,000/4,000-character trial with separate contexts and no resampling. If the fixed rule passes: `app/mcp/server.py` (2,000 to 4,000 search response budget), focused history-presentation/MCP tests, `docs/reports/session-history-search-quality-study.md`, and `roadmap/features/improve-session-history-search-quality.md`. Ignored artifacts remain under `.local/history-budget-4000-trial/`. No merge, install, or service change. The result PR (#160) absorbs and supersedes closed PR #159 because that parent changed the same report and roadmap; every #159 finding and commit is preserved.

**Constraints:**
Freeze the inventoried 15 cases with no replacement or resampling. They are source-disjoint by frozen anchors, but may retain work/thread dependence; this supports a bounded local practical recommendation, not statistical independence or a population claim. Partition full-source gold across two isolated reviewers so each case is read once; independently inspect only ambiguous gold and later variant/safety disagreements. Before variant outputs, classify each case as answerable, partial, negative, or ungradable; freeze attainable critical facts, qualifiers, missing-evidence obligations, and proof that a 1,200-character answer fits. A partial case resolves only when it states every attainable critical fact and every required missing-evidence limitation. Report/exclude ungradable pairs consistently from both outcome and retrieval-text calculations. If fewer than three cases can possibly improve, REJECT and close. Otherwise compare two separately graded contexts per case through one fixed-candidate replay search, up to three cumulative 2,400-character expansions, and answer/abstain. Preserve identity/security semantics and byte identity for fitting responses. Retrieval alone never updates accessibility. Label results as downstream-task-effect. No tuning, new sampling, or synthetic real evidence. Enforce total model usage <=175k input / 25k output with a reservation ledger; the ship gate separately uses exact serialized search-plus-consumed-expansion characters.

**Completion criteria:**
1. Feasibility inventory reports credible independent-task count, pressure/fitting split, source/gold volume, and revised model-token estimate before any grading.
2. If approved, contract tests pass; the candidate adds at least three answerable successes, loses zero baseline successes, and adds no safety or negative regression.
3. Aggregate search-plus-expansion text is at most 125% of baseline; otherwise reject the change and close without prompt/model tuning or another automatic study.
4. Evidence, report, roadmap, and Work Record agree; production remains unchanged unless a later PR is explicitly approved.

**Risk:** Elevated

**Complexity:** Moderate

**Reason:**
`app/mcp/server.py` is a watched runtime surface, raising the eventual change above Routine. The implementation is one response-budget constant plus focused contract tests and evidence/document alignment; no red-zone, architecture, API, persistence, or security checkpoint is triggered.

**Discovery:**
- `_compact_history` in `app/mcp/server.py` is the shared packaging seam; the current search budget is 2,000 characters.
- The installed service was healthy at inventory start (`/health`, `/status`, `/debug/queue/health`; embedding provider OK and queue clean).
- The current report explicitly recommends keeping 2,000 characters, so accepted trial evidence must reconcile that claim rather than leaving docs/code drift.
- Prior comparison and reserved holdout identifiers are available in ignored study artifacts and must be excluded without opening holdout content.

**Material assumptions:**
1. The fixed 15 frozen-source cases provide at least three answerable or partial opportunities for packaging to improve. Disproof: pre-variant gold classification finds fewer than three possibly improvable cases. Action: REJECT and close without replacement sampling.
2. Shared-source/query deduplication is adequate for a local paired decision despite residual work/thread dependence. Disproof: ambiguity audit finds duplicated task substance that can change the decision. Action: mark affected cases ungradable, report the reduced set, and apply the same stop rule without replacement.
3. Changing only the shared response budget preserves ranking, visibility, identity, and expansion behavior. Disproof: contract or parity checks show semantic drift. Action: reject and close.
4. Separate blinded contexts per case/variant support paired downstream grading after gold is frozen. Disproof: leakage, answer-cap failure, or scorer ambiguity. Action: stop or exclude the affected pair under the frozen rules; never retune.

**Plan:**
1. Create the isolated branch/worktree and this Work Record; obtain clean-context risk classification.
2. Create one consistent paired SQLite snapshot with the repository helper; inventory eligible events after prior-sample/holdout exclusion and connected-component deduplication.
3. Return the count, pressure/fitting split, source/gold volume, and revised token estimate to the architect; the architect approved the fixed audit and paired trial.
4. If approved, freeze task selection and full-source gold, validate the answer cap, generate paired contexts, grade independently, and score the predeclared rule without tuning.
5. Only if the rule passes, apply the one-line budget change, add focused contract coverage, align report/roadmap, run the required tests and smart review, then open (but do not merge/install) a PR.

**Verification plan:**
- Selection separation → inventory and harness assertions prove fixed IDs, prior/holdout exclusion, source-disjoint anchors, and explicitly report residual work/thread dependence.
- Gold freeze and leakage → packet assertions prove no variant output reaches gold; classifications, critical facts, partial-case obligations, negative-neighborhood audits, ungradable exclusions, and answer-cap fit are frozen before trial cards.
- Trial limits and cost → per-card logs enforce one blinded search response, only emitted source handles, at most three cumulative expansions, 1,200-character answers, exact serialized retrieval characters, and an enforcing 175k/25k model ledger using exact o200k payload counts, repeated-context accounting, framing reserves, per-dispatch refusal, and result reconciliation.
- Caller contract → focused presentation tests plus registered MCP-over-HTTP broad/exact-work search → delivered lookup ID → expansion E2E cover fitting byte parity, empty/default/max/over-budget Unicode, dropped results, permission/scope failures, historical warnings, and unchanged accessibility state.
- Review quality → clean-context smart review covers harness fidelity before execution and correctness/evidence/redline/workflow after implementation.

**Plan review:**
Architect approved the fixed 15-case pre-execution plan on 2026-09-10: partitioned full-source gold, ambiguity-only independent audit, separate-context paired journeys, fixed ship rule, and a 175k input / 25k output model cap. Pre-edit risk classification: Elevated/Moderate; `app/mcp/server.py` watched; no special checkpoint; docs conflict must be reconciled. Clean-context review blocked the first harness and prescribed production-shaped inputs, no gold leakage, cumulative emitted-handle expansion limits, full evidence-universe auditing, explicit partial/ungradable rules, a model-cost ledger, and MCP-over-HTTP E2E. These corrections are required before gold/trial execution or production edit. The corrected harness protects all prior development and holdout events plus prior comparison-query events, redacts and excludes overlapping fixed cases, requires complete expansion-neighborhood logs for partial/negative gold, and enforces the model cap before every dispatch. A second clean-context smart review passed after protection was extended through all retrievable prior expansion neighborhoods and ledger overruns were made persistent/blocking; the lossless gold-neighborhood audit fits at 60,267/61,000 input tokens.

**Approvals:**
User approved architect-assigned work and PR creation. Architect approved the fixed gold audit and one paired trial, followed by the predeclared ship/reject path. Production edit is conditional on a passing trial; merge and install remain unapproved.

**Exceptions:**
—

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

Feasibility froze 15 source-disjoint-anchor components (8 pressure, 7 fitting). Six overlapped the protected prior-development/holdout/comparison/request/source/expansion universe and were classified ungradable before variants, redacted, excluded, and not replaced. Gold for the remaining nine was 6 answerable, 1 partial, and 2 negative. Among eight pressure cases, three were protected/ungradable and two were negative; exactly three answerable/partial pressure cases could improve, leaving no margin against the fixed threshold.

Ten of 18 journey outputs were produced, but zero valid pairs completed. The only case with both variants dispatched was invalidated when its fitting 4,000-character candidate consumed one persisted expansion but lost the second to a Windows stdout Unicode encoding error. After the helper was set to UTF-8, a pressure-case 2,000-character baseline still received no readable output even though the harness persisted a 2,400-character expansion without error; the cause is unknown at the tool-output transport boundary, and its candidate mate was not dispatched. The remaining seven cases had only one variant dispatched. These failures are not established Pallium Relay defects.

The paired phase used 24,076/25,000 input tokens, leaving 924, below the affected journeys' 2,353- and 3,545-token reservations; the fixed protocol also prohibited reruns. Invalidation of one of exactly three possible-improvement pairs made the operational ship rule unreachable, but with no valid pair this is not a downstream effect estimate. Decision: **DO NOT SHIP / NOT VALIDATED**. Production remains at 2,000; every quality, baseline-loss, safety, negative-regression, retrieval-text, and caller-contract gate is unmeasured.

Explicit experiment-payload usage was 144,083/175,000 input and 12,483/25,000 output. The final review used gpt-6-astra high despite the Sol-only constraint, and a broad suite ran despite the no-redundant-runs constraint. Both deviations are recorded; neither validates the incomplete experiment, and neither is repeated for this prose correction. The broad suite reached 1,115 passed, 2 skipped, 1 xfailed, and 3 failed; sequential `--lf -n 0` passed one and reproduced two unrelated integration-state failures. PR #160 preserves and supersedes closed PR #159; neither was merged.

## Result review

The earlier clean-context gpt-6-astra high review passed the then-current arithmetic and documentation scope, but its “REJECT” wording overstated the experiment result. The maximum-two calculation is only the predeclared operational stop rule after an invalidated improvement opportunity; it is not evidence that 4,000 regressed or failed any measured gate. This factual correction supersedes that label. No additional model review or broad test run is authorized or needed for the prose-only correction.
