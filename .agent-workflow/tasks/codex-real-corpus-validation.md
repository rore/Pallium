<!-- agent-workflow:start -->
**Outcome:** Pallium has a budget-capped real-corpus comparison that shows whether historical memory improves subsequent work enough to justify its cost and risk.

**Target:** Pallium.

**Scope:** The existing real-corpus pull evaluator, focused evaluator tests/report artifacts, and the canonical roadmap state for `idea-pull-real-corpus-validation`.

**Constraints:** Production retrieval behavior and live Pallium data remain unchanged; use a scratch database; distinguish downstream-task effect from retrieval metrics; keep model spend bounded; require only one human spot-check.

**Completion criteria:** A balanced real-history sample runs with and without memory under equal conditions, reports quality/harm/tokens/latency plus stale/reversed-decision evidence in plain language, passes focused and workflow checks, and supports a documented proceed/guard/stop product decision.

**Risk:** Routine

**Complexity:** Moderate

**Reason:** Redline classified all intended `evals/**`, `tests/**`, `roadmap/**`, and Work Record paths BLUE with no boundary or contract findings. Moderate because the task combines evaluator behavior, live-model evidence, human-review output, and roadmap closure.

**Discovery:** The evaluator already performs read-only scoped loading, paired with/without answers, deterministic blind judging, privacy-separated reports, and a 20k estimated-input cap. The live DB currently yields 30 valid cases across four requester-session values; 27 contain Unicode history and 18 reuse a source seen in another case. Gaps: five-case random cap, no session balance, no human-readable blinded review sheet, and no focused multi-scenario superseded corpus. The existing contamination harness already accepts an alternate scenario file and repeated seeds, so it should be reused unchanged. Exact provider token usage is unavailable from the provider contract; estimates must remain labelled estimates and real HAI spend measured externally.

**Material assumptions:** The current real corpus contains enough anonymizable cases for a balanced bounded run; disproved if selection cannot cover useful, irrelevant, stale/reversed, duplicate, and Unicode cases, in which case stop and return to sampling design. The configured HAI provider is available; disproved by provider health or model-call failure, in which case retain the reproducible runner and record the external blocker rather than fabricate results.

**Plan:** 1. In `evals/real_corpus_pull_eval.py`, raise the bounded sample to 12, select deterministically by seeded round-robin across requester sessions, expose text-free sampling composition, and optionally write a private blinded Markdown review sheet alongside the existing private JSON. Preserve read-only DB access, visibility filtering, 20k estimate cap, and the downstream-effect claim label. 2. Extend `tests/test_real_corpus_pull_eval.py` for 0/max/over-max, deterministic balanced sampling, Unicode/private review rendering, output-path conflicts, and unchanged DB lifecycle. 3. Add `evals/pull_contamination/scenarios_superseded.json` with the two existing generalized superseded-convention cases and a focused test in `tests/test_pull_contamination.py`; do not modify the harness. 4. Verify locally, snapshot the live DB to a new scratch file, run 12 real cases plus five repetitions of the focused probe, then present the private sheet for one human spot-check. 5. After human labels, record the proceed/guard/stop decision and align `roadmap/board.md` plus the idea file. Stop if fewer than 10 valid real cases survive, the HAI provider fails, the 20k estimate cap stops the run, or the human review is not yet supplied.

**Verification plan:** When the live snapshot has sufficient cases, the evaluator shall select at most 12 with near-even requester-session representation and deterministic seed behavior -> focused sampling tests plus text-free aggregate assertions. When the CLI writes reports, the DB shall remain byte-identical and all raw text shall stay only in explicitly acknowledged private outputs -> CLI lifecycle/privacy tests including Unicode and conflicting paths. When the focused stale probe runs, it shall cover at least two `scope-superseded` scenarios over five repetitions and report per-scenario contamination -> scenario validation test plus real harness artifact. When the experiment completes, it shall report downstream quality/harm, estimated context cost, latency, limitations, and a blinded human worksheet -> aggregate/review assertions and manual spot-check. Workflow and delivery -> `python -m pytest tests/test_real_corpus_pull_eval.py tests/test_pull_contamination.py -q`, full relevant CI, workflow checker, `git diff --check`, PR review-thread resolution.

**Plan review:** Self-review complete: reuses both existing harnesses, adds no production behavior or provider abstraction, and defers the product decision until the required human spot-check rather than treating the model judge as ground truth.

**Approvals:** Not required at this risk level.

**Exceptions:** —

**State:** Blocked
<!-- agent-workflow:end -->

## Implementation

- Establish Context / Assess Risk: task branch created; BLUE redline verdict returned by clean-context read-only review.
- Discovery / Plan: existing evaluator and contamination harness traced end to end; live DB inspected read-only (30 valid cases, four requester-session values). Minimal plan self-reviewed; no production edit or new framework required. `apply_patch` hit the documented machine-local 1385 failure, so the Work Record transition used the allowed narrow deterministic replacement fallback.
- Implement: raised the cap to 12, added seeded requester-session round-robin sampling and text-free composition counts, added a private blinded Markdown worksheet, and added a two-scenario focused superseded corpus without changing the existing harness.
- Live run attempt: a fresh scratch snapshot was created successfully. The private run was blocked before transmission pending explicit approval to send sampled private excerpts through HAI. The synthetic real-provider probe reached HAI but failed 30/30 with HTTP 401 because this Codex terminal lacks `PALLIUM_HAI_API_KEY`; credential-location discovery was also blocked pending explicit approval. No private corpus was sent. Next step: obtain explicit user authorization for both using the existing local credential and transmitting the 12 sampled private cases, then rerun.

## Evidence

- `python -m pytest -q tests/test_real_corpus_pull_eval.py tests/test_pull_contamination.py` -> 45 passed.
- `python scripts/agent-workflow-check.py --repo-root . --slug codex-real-corpus-validation` -> clean after correcting template-only State comment parsing.
- `git diff --check` -> clean.
- Focused superseded dry-run: 30/30 trials completed with zero errors; scripted results are harness validation only, not product evidence.
- Fresh scratch snapshot: `.local/research/real_corpus_validation_snapshots/pallium-20260824T125946Z.db`; live DB never written.
- Real-provider superseded attempt: 30/30 HTTP 401 `MISSING_AUTHORIZATION_HEADER`; no usable product result.
- Private real-corpus attempt: blocked before provider transmission by the environment approval gate; no private data sent.

## Result review

Blocked pending explicit user authorization and subsequent human spot-check; no product recommendation yet.
