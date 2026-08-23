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

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

- Added an eval-only CLI that requires an explicit scratch DB, exact container, visibility, aggregate output, private review output, and acknowledgement that the review file contains raw private text.
- The loader opens SQLite in read-only mode, samples only non-empty agent-pull events, keeps the exact container boundary, and reuses the production visibility predicate for same-container source eligibility.
- The public-tool representation is bounded to three deduplicated sources at 480 characters each. Oversized queries, answers passed to the judge, sample count, and total estimated model input are bounded.
- Each valid case runs matched WITH/WITHOUT prompts plus a deterministic blind A/B comparison. Aggregate output is text-free; the separate local review output carries raw evidence and a never-publish warning.
- The report labels the result as offline controlled downstream-task-effect and explicitly excludes candidate recovery, injection precision, observed live improvement, a calibrated evaluator, a human spot-check, and an exact tokenizer budget.
- Delegated edits used the documented deterministic IO.File fallback after the machine-local apply_patch/process error.

## Evidence

- 13 focused network-free tests pass, including the full CLI lifecycle, DB byte preservation, output/sidecar collision rejection, cross-container and mixed-visibility isolation, malformed/missing/forgotten/empty/duplicate/Unicode cases, invalid judge output, provider failure, deterministic/max sampling, oversized queries, answer truncation, and estimated-input-budget stop.
- Module syntax compilation and git diff --check pass.
- Scratch preflight found 8 valid scoped agent-pull cases and deterministically selected 5. Per-case public-shape history is 1,032–1,440 characters (about 258–360 chars/4 estimated tokens).
- No production files changed. The user explicitly approved sending the bounded private pilot corpus to the configured HAI provider; the credential was loaded from Windows Credential Manager into process memory only and was neither printed nor persisted.
- The capped HAI run completed 5/5 paired cases with no failures, using 6,796 estimated input tokens of the 20,000-token ceiling. WITH history won 5/5 comparisons; history was labelled useful in 4 cases, irrelevant in 1, and harmful in 0. Added history averaged 340.6 estimated tokens and WITH-history latency averaged 8.56s versus 3.42s WITHOUT history.
- The result is directional only: one uncalibrated model judge, one draw per case, no human spot-check, and no linked observed work-after. Stored lookup events contain source IDs rather than the exact original excerpts, so the bounded reconstruction may differ from what the agent originally saw. It does not establish broad ROI or complete the parent roadmap item.

## Result review

APPROVE IMPLEMENTATION — clean-context review confirms the scope, privacy boundaries, production visibility reuse, approximate-budget honesty, CLI E2E, and 13-test evidence. The completed pilot supports recording directional evidence only; the parent roadmap item remains open for human spot-checking and the focused superseded-history probe.
