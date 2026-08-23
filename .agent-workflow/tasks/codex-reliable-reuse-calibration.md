# Reliable reuse calibration

Branch: `codex/reliable-reuse-calibration`

<!-- agent-workflow:start -->
**Outcome:**
Pallium's reuse checker reliably supplies verifiable shared evidence, and the dashboard reflects the newest complete calibration attempt rather than an older passing report.

**Target:**
Pallium repository.

**Scope:**
Reuse-judge prompt/output handling, calibration report publication, focused evaluator/dashboard tests, the calibration roadmap card, and this Work Record.

**Constraints:**
Do not weaken evidence-span validation, tune the maintained reference fixture, change production retrieval/ranking, expose private history, or describe reference-set stability as proof that Pallium helped real work. A failed completed calibration must remain visible as failed.

**Completion criteria:**
The deterministic suite rejects unsupported evidence and accepts valid shared evidence; a cache-disabled two-group reference run has no missing/failed events and all three agreement gates meet κ≥0.70; the canonical dashboard report is replaced by that newest run whether it passes or fails; the live dashboard shows the same verdict after the VBS-backed service restarts.

**Risk:**
Routine

**Complexity:**
Moderate

**Reason:**
Redline classified all intended eval, test, roadmap, and optional dashboard paths blue with no boundary or checkpoint findings. Complexity is moderate because prompt behavior, report publication, multi-seed external evaluation, and live dashboard agreement must all align.

**Discovery:**
The canonical dashboard report is the older 15:34 passing run (κ=0.75, N=12). A newer 16:53 post-enforcement run failed: 16/72 calls violated evidence-span validation, so the roadmap correctly reopened calibration while the dashboard remained stale. Fixture incorporation cases all contain short exact shared spans, while the rubric permits near-verbatim classification but did not clearly require one contiguous exact substring for `evidence_span`. The validator is intentionally fail-closed. The runner already writes pass and fail results to the dashboard's fixed canonical path by default; the stale state came from overriding `--output` on the newer run.

**Material assumptions:**
RESOLVED: the HAI credential is stored in Windows Credential Manager as hai-cli:proxy-api-key and is UTF-8. With explicit user approval it was read into process memory only, used with bearer auth for synthetic calibration, never printed or persisted, and cleared after each run.

**Plan:**
Clarify only the prompt/schema wording so `evidence_span` is one short contiguous exact substring present on both sides, preferring a distinctive value/name and falling back to `influence` when none exists; do not alter `_judge_once` or the fixture. Add prompt-contract coverage and a CLI regression proving a failed completed run overwrites an existing passing report at `DEFAULT_OUTPUT_PATH`; run focused tests; run the full cache-disabled two-group calibration without `--output` so it publishes canonically; update roadmap evidence and verify the restarted live dashboard. Target files: `evals/historical_lookup_judge.py`, `tests/test_historical_lookup_judge.py`, `tests/test_reuse_judge_calibration.py`, the calibration roadmap card, and this Work Record. Stop if success would require weakening validation or editing the reference fixture.

**Verification plan:**
Prompt requires one exact shared span without weakening validation → focused historical-lookup judge tests.
Failed completed run replaces an older passing canonical report → calibration CLI regression using patched DEFAULT_OUTPUT_PATH.
Two groups complete with zero failures/missing and all κ≥0.70 → cache-disabled 72-call synthetic calibration report.
Canonical and live dashboard verdict agree → report metadata plus VBS-backed restart and HTTP checks.
Repository workflow remains clean → agent-workflow/redline checks and CI.

**Plan review:**
Clean-context agent review approved the minimal prompt-only repair and existing canonical publication path. It required an explicit no-`--output` regression proving a failed run replaces an older passing canonical report; incorporated above.

**Approvals:**
Not required at this risk level.

**Exceptions:**
—

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

- Context/risk: current dashboard/report drift confirmed from aggregate local metadata. Clean-context redline review classified the intended scope blue with no checkpoint; `app/dashboard.py` is watch-only if touched. The referenced repository-local agent-redline skill file was absent, so classification used the checked-in policy and reporter.
- Discovery/plan: the exact shared spans already exist in every synthetic incorporation case. The approved implementation is limited to prompt/schema wording, two focused test files, the roadmap result, and this record; no dashboard loader, validator, fixture, production retrieval, or persistence edit is planned.
- Implementation: clarified only the evidence-span prompt and bumped its provenance to v6; added prompt-contract and default-canonical-overwrite regressions. The validator and fixture are unchanged. The approved Credential Manager key was used process-only for cache-disabled synthetic calibration. The final canonical run passed all gates, and the VBS-backed service now serves that report.

## Evidence

- Focused offline suite: 55 passed.
- Cache-disabled two-group run: group A kappa 1.0 (N=12), group B kappa 1.0 (N=12), mutual kappa 1.0 (N=12), zero failed or missing events.
- Canonical report: .local/research/reuse_judge_calibration.json, prompt v6, reference_set_passed=true.
- Restarted service: /health ok, /status embedding_provider_ok=true; live dashboard API serves prompt v6, pass=true, N=12, zero failures.

## Result review

Clean-context final review: APPROVE, no actionable findings. It confirmed the change is prompt-only, the fail-closed validator and fixture are unchanged, focused regressions cover the output contract and canonical overwrite, aggregate evidence supports only the stated reference-set claim, and no credential material appears in the diff.
