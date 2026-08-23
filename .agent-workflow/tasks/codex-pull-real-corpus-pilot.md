# Real-corpus historical-pull pilot

Branch: `codex/pull-real-corpus-pilot`

<!-- agent-workflow:start -->
**Outcome:**
A budget-capped offline pilot compares answers with and without actual Pallium historical-pull results from a scratch snapshot and reports whether the retrieved context appears helpful, harmful, or neutral.

**Target:**
Pallium repository.

**Scope:**
A read-only eval runner under `evals/`, network-free tests, a local uncommitted run artifact, and roadmap evidence/status alignment.

**Constraints:**
Never mutate or copy the live database; require an explicit scratch DB path. Never commit private query, source, or generated answer text. Cap the default pilot at five non-empty `agent_pull` cases and one paired run per case. Reuse configured providers and eval cache. Do not change production retrieval, API, storage, or authorization. Every metric must say it is offline controlled downstream-task-effect, not observed live improvement, candidate recovery, or injection precision.

**Completion criteria:**
The CLI deterministically samples real non-empty historical-pull events, reconstructs only their exposed non-forgotten source text, runs identical-query WITH and WITHOUT arms plus a blinded comparison, and writes a private local review artifact plus a text-free aggregate report. The report includes wins/losses/ties, relevance labels, added context tokens, latency, failures, corpus attrition, and explicit claim limits. Empty/malformed/missing/forgotten/duplicate/Unicode/max-sample/provider-failure paths are covered. A budget-capped HAI run on the scratch snapshot produces a directional result and the roadmap records what is and is not proven.

**Risk:**
Routine

**Complexity:**
Moderate

**Reason:**
The slice is isolated to offline eval, tests, and roadmap files; it is read-only against an explicit scratch DB and changes no production behavior. Moderate complexity covers privacy-safe dual outputs, paired provider calls, blinding, and corpus attrition.

**Discovery:**
The scratch snapshot has 8,328 source turns and 39 lookup events, but only nine query-bearing non-empty lookups and eight non-empty `agent_pull` lookups. Historical-pull events have no linked work-after turns, so passive telemetry cannot prove benefit. Existing contamination and continuity harnesses provide paired-arm, cache, token-cost, and reporting patterns; provider construction already lives in `evals.eval_common`.

**Material assumptions:**
A five-case, one-run controlled pilot is enough to decide whether a larger study is worth its cost, but not enough for broad ROI. Disprove if fewer than three valid non-empty agent-pull cases survive forgotten/missing-source filtering, or if the comparison judge fails on more than one case; in either case report the data gap and stop without a product recommendation.

**Plan:**
Add one small real-corpus runner that loads and validates historical-pull episodes, hashes public case identifiers, generates matched WITH/WITHOUT answers, randomizes answer ordering for the judge, and separates text-free aggregate output from an explicitly local review file. Reuse `build_eval_providers`, `CachedLLMProvider`, and deterministic character/4 token estimation. Add focused tests using a temporary SQLite corpus and scripted providers. Run the five-case cached HAI pilot, review the local cases for obvious evaluator failures, update the roadmap evidence, and close through PR.

**Verification plan:**
Valid paired lifecycle and privacy-safe report → temporary-DB runner/CLI E2E test. Empty, malformed, missing, forgotten, duplicate, Unicode, max-sample, and provider-error behavior → focused tests. No raw private text in aggregate output → recursive secret-sentinel assertion. Claim seam and budget cap → report contract assertions. Real feasibility → cached five-case scratch run with non-secret aggregate evidence only. Repository integrity → focused pytest, diff check, workflow gate, CI, and clean-context review.

**Plan review:**
Clean-context budget-feasibility review completed before implementation. It recommended an 8–12 case pilot; discovery found only eight usable non-empty agent-pull events, so the budget-aware first run is capped at five cases and one paired run. Production changes were explicitly rejected.

**Approvals:**
Not required at this risk level. The user explicitly authorized the budget-aware next slice and confirmed the local HAI configuration is available.

**Exceptions:**
—

**State:** Ready to implement
<!-- agent-workflow:end -->

## Implementation

Pending.

## Evidence

Pending.

## Result review

Pending.
