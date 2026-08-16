# pull-contamination-filtering-experiment

Tests the distinctive hypothesis of the vNext pull model: when the agent pulls plausible
but IRRELEVANT/WRONG history, does it filter it out or get contaminated? Uses deterministic
A/B task outcomes (no LLM judge) across three conditions.

<!-- agent-workflow:start -->
**Outcome:**
A rerunnable eval that, per scenario, measures whether plausible-but-wrong pulled history
changes the agent's answer — via a DETERMINISTIC A-vs-B outcome, across three conditions
(no-history baseline / relevant-history control / contaminating-history test). Produces a
contamination rate + control rates with bands. No production behavior change.

**Target:**
Pallium — new eval under `evals/pull_contamination/` (harness + scenarios), mirroring
`evals/history_pull_decision/`. Offline; scratch DB only; never touches production.

**Scope:**
New `evals/pull_contamination/` (harness.py, scenarios.json, __main__.py) + a test under
`tests/`. Reuse the in-process service + agent scaffolding from `evals/history_pull_decision/`.
No change to production retrieval/injection, and no change to the existing decision harness.

**Constraints:**
- **Deterministic outcome detection first** (scan the final answer for scenario-defined
  A-marker vs B-marker); an LLM judge is optional for ambiguous cases only, never the
  primary signal — so judge calibration is NOT a blocker.
- Disable proactive injection **in the experiment arm only** (clean attribution); do not
  change global/production behavior.
- Contamination taxonomy stays REALISTIC (not extreme): same-topic-wrong-subtask,
  old/superseded decision, similar-project-different-convention, related-investigation-
  different-conclusion, benign-irrelevant.
- No internal/product names in committed scenarios/docs (generic engineering situations).
- Scratch DB only; never point `--db` at the live DB.

**Completion criteria:**
Harness runs the 3 conditions over the scenario set, reports contamination rate (test arm
switched to B), baseline A-rate, and control A-rate + citation, deterministically; a test
covers the outcome-detection logic; adversarial-synthetic run produces a first read.

**Risk:** Routine

**Complexity:** Moderate

**Reason:** Net-new eval harness with several parts (3-condition runner, forced-history
seeding, deterministic A/B detection, taxonomy scenarios) → Moderate, so expanded shape.
Risk Routine: `evals/**` is blue; offline, scratch-DB only, no production surface.

**Discovery:**
Mirror `evals/history_pull_decision/harness.py` (InProcessService/TestClient, scratch DB,
seeded history thread, real decision/finalize agent via build_eval_providers) and its
scenario loader. Difference: instead of measuring whether the agent PULLS, we CONTROL which
history is present per condition and measure the FINAL ANSWER's A/B choice. The over-pull
finding (agent pulls readily) means we can rely on the agent pulling the seeded history; to
isolate filtering we ensure the condition's history is what gets returned.

**Material assumptions:**
- ASSUMPTION: tasks can be authored so A is the objectively correct choice from the task
  ALONE (no-history baseline → A), while contaminating history plausibly argues B. DISPROVED
  BY: baseline A-rate not ~1.0 (task not self-determining). ACTION: tighten task wording so
  A is unambiguous without history.
- ASSUMPTION: A/B choice is detectable deterministically from the answer via markers.
  DISPROVED BY: high ambiguous-rate. ACTION: make scenarios require stating the specific
  differing value (e.g. "250ms" vs "500ms"), and fall back to a judge only for residual
  ambiguity.

**Plan:**
1. Scenario schema: `{id, taxonomy_type, current_task, marker_a (correct), marker_b (wrong),
   relevant_history (supports A), contaminating_history (plausibly argues B)}`. Author ~2
   scenarios per taxonomy type (10 total).
2. Harness: for each scenario × seed, run three conditions — (a) no-history, (b) seed
   relevant_history as the retrievable/returned history, (c) seed contaminating_history —
   with proactive injection disabled in-arm. Run the agent to a final answer.
3. Deterministic detection: classify the final answer as chose-A / chose-B / ambiguous by
   marker scan. Metrics: baseline A-rate (cond a), control A-rate + used-history (cond b),
   **contamination rate** = chose-B in cond c (with Wilson bands over scenarios×seeds).
4. Adversarial-synthetic run first; then a second pass validating on real-corpus cases with
   human spot-checking (separate, later — flagged, not in this WR's run).
5. Fold `idea-reconcile-unprompted-pull-direction-signal` note (over-pull already answers
   "unprompted").

**Verification plan:**
- Outcome-detection correctness → unit test over crafted answers (A-only, B-only, ambiguous).
- Deterministic signal, not judge → assert the primary metric derives from marker scan.
- First read → adversarial-synthetic run (seeds 0,1,2) reports baseline/control/contamination
  rates; sanity: baseline A-rate high, control A-rate high, contamination rate is the finding.
- CI: agent-workflow, redline (BLUE), test lanes (new test + no regressions).

**Plan review:** Self (Routine). Design originated from user-relayed peer review; recorded here.

**Approvals:** Not required at this risk level (Routine).

**Exceptions:** —

**State:** Ready to implement
<!-- agent-workflow:end -->

## Implementation

- (pending) build harness + scenarios, deterministic detection, adversarial run.
