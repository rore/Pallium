# pull-contamination-ambiguous-task-variant

Second phase of the pull-contamination experiment. The explicit-task pass (PR #31) showed 0%
contamination — but only proved the agent won't override a task that itself pins the answer.
This variant removes that crutch: the task is genuinely ambiguous, history is the main signal,
and we measure whether the agent distinguishes useful history from misleading history.

<!-- agent-workflow:start -->
**Outcome:**
A rerunnable eval that, on AMBIGUOUS tasks (the task text does NOT pin the answer; situational
cues favour approach A but do not state it), measures three things across the same three
conditions: (1) is the no-history baseline genuinely uncertain (not pinned to A), (2) does
relevant history lift the A-rate above baseline, (3) does plausible-but-wrong history lift the
B-rate above baseline (contamination). The differential comparisons — relevant_lift and
contamination_harm, each with a confidence band — are the headline. No production behaviour change.

**Target:**
Pallium — `evals/pull_contamination/`. New `scenarios_ambiguous.json`; generalise
`harness.py` metrics with a differential block; extend `tests/test_pull_contamination.py`.

**Scope:**
- NEW `evals/pull_contamination/scenarios_ambiguous.json` — 10 ambiguous-task scenarios.
- `evals/pull_contamination/harness.py` — add a `differential` metric block (relevant_lift,
  contamination_harm) with a difference-of-proportions band; thread an optional scenarios-file
  `case` label into the report + CLI. NO change to condition wiring, forced-history seeding, or
  the deterministic A/B detection.
- `tests/test_pull_contamination.py` — invariants for the ambiguous set + differential math tests.

**Constraints:**
- Deterministic marker scan stays the primary signal; no LLM judge as a gate.
- Do NOT assert the baseline chooses A for the ambiguous set — genuine baseline uncertainty is
  the design goal, and asserting A would defeat the experiment.
- No change to production retrieval/injection; offline; no service/DB (history forced into prompt).
- No internal/product/company names in scenarios.
- Backward compatible: the existing explicit-task scenarios.json + its tests keep passing.

**Completion criteria:**
Harness runs the 3 conditions over the ambiguous set and reports relevant_lift and
contamination_harm with bands (plus per-condition A/B/ambiguous rates); tests cover the
ambiguous scenario invariants and the differential math; one adversarial-synthetic real-LLM pass
produces a first read of baseline spread + lift + contamination-harm.

**Risk:** Routine

**Complexity:** Moderate

**Reason:** `evals/**` + `tests/**` + `.agent-workflow/**` are all blue (offline, scratch-only,
no production surface) → Routine. Judgment-heavy scenario authoring (baseline must be genuinely
un-pinned) + a metric generalisation + tests spanning two scenario sets → Moderate, so expanded shape.

**Discovery:**
`harness.py` is already condition- and scenario-file-agnostic: `--scenarios` selects the set,
`compute_metrics` already emits a `per_condition` breakdown with choose_A/choose_B/ambiguous +
Wilson bands. So the ambiguous variant needs (a) a new scenario file and (b) DIFFERENTIAL metrics
(deltas between conditions), which the current output only implies. `_wilson_95` is imported from
`historical_lookup_measurement`; a Newcombe (method 10) difference-of-proportions band composes
cleanly from two Wilson intervals with no new dependency. The explicit set's benign-irrelevant
type is dropped here — every ambiguous contaminating_history genuinely argues B (matches marker_b).

**Material assumptions:**
- ASSUMPTION: tasks can be authored so A is the defensible best-fit given situational cues, yet
  NOT stated as a rule, so the no-history baseline is genuinely split (not ~1.0 A and not ~1.0 B).
  DISPROVED BY: baseline choose_A_rate ~1.0 (task still self-pins) or ~0.0 (cues point at B).
  ACTION: soften the situational cue / rebalance the two options so baseline spreads.
- ASSUMPTION: history exerts measurable causal influence — relevant_lift > 0 and
  contamination_harm interpretable. DISPROVED BY: relevant_lift band includes 0 AND
  contamination_harm band includes 0 (history moves nothing → scenarios too weak or agent ignores
  all history). ACTION: strengthen history specificity, or report the null honestly.
- ASSUMPTION: the A/B choice stays deterministically detectable on ambiguous tasks.
  DISPROVED BY: high ambiguous-rate across conditions. ACTION: force a concrete stated value
  (named option / number) as the explicit set does.

**Plan:**
1. Author `scenarios_ambiguous.json`: 10 scenarios, 2 per type — two-reasonable-patterns,
   old-decision-pre-architecture-change, similar-subsystem-different-constraint,
   investigation-not-transferable, user-preference-non-universal. Each: task states a SITUATION
   (cues favour A) and forces a concrete A-vs-B choice without naming the answer; relevant_history
   argues A (matches marker_a, not marker_b); contaminating_history argues B (matches marker_b, not
   marker_a). Add a top-level `"case": "ambiguous-task"`.
2. Harness metrics: add `_diff_with_band` (Newcombe method-10 difference of two proportions from
   Wilson intervals) and a `differential` block — `relevant_lift` = A_rate(relevant) −
   A_rate(baseline); `contamination_harm` = B_rate(contaminating) − B_rate(baseline). Thread an
   optional `case` label from the scenarios file into the report + a printed line. Keys ADDED only
   (backward compatible).
3. Tests: ambiguous scenario invariants (marker_a matches relevant & not contaminating; marker_b
   matches contaminating & not relevant; 5 types × 2), and differential-math unit tests
   (sign + band + empty-safe). Do NOT assert baseline=A for the ambiguous set.
4. Real adversarial-synthetic pass (seeds 0,1,2 → 30/condition); record baseline spread,
   relevant_lift, contamination_harm with bands. Real-corpus validation stays a later, separate WR.

**Verification plan:**
- Differential math → unit tests over crafted trials (positive lift, positive harm, empty-safe,
  band composition sane).
- Ambiguous scenario invariants → unit test over the loaded set (marker containment; 5×2 taxonomy).
- Deterministic-signal-not-judge → primary metric still derives from marker scan (unchanged).
- Backward compatibility → existing explicit-set tests still pass; explicit run still reports.
- First read → real LLM pass reports baseline choose_A (expect NOT ~1.0), relevant_lift,
  contamination_harm with Wilson/Newcombe bands.
- CI: agent-workflow, redline (BLUE), test lanes.

**Plan review:** Self (Routine). Design authored from the user's relayed hard-case spec (ambiguous
task; three conditions; measure contamination-vs-baseline, relevant-helps, wrong-hurts). Recorded here.

**Approvals:** Not required at this risk level (Routine).

**Exceptions:** —

**State:** Ready to implement
<!-- agent-workflow:end -->

## Implementation

- `scenarios_ambiguous.json` — 10 ambiguous-task scenarios, 2 per type (two-reasonable-patterns,
  old-decision-pre-architecture-change, similar-subsystem-different-constraint,
  investigation-not-transferable, user-preference-non-universal). Top-level `"case":
  "ambiguous-task"`. Each task states a SITUATION (cues favour A) and forces a concrete A-vs-B
  choice without stating the answer.
- **Clean-context adversarial design review** (delegated to a general-purpose subagent, read-only,
  before the LLM run) caught the dominant failure mode: 4 tasks embedded the *textbook trigger
  keyword* for A directly in the task text, which pins the baseline and collapses the scenario back
  to the explicit-task case. Fixed per the reviewer's pattern — keep the situational cue, delete
  the clause stating A's mechanism/justification — on: service-integration-style (dropped "must not
  block"/"delay acceptable"), session-storage (dropped "no sticky sessions"), read-after-write
  (softened "ALWAYS…no visible staleness" → "generally expect…right away"), logging-format (dropped
  "indexes structured fields"). Also re-keyed batch-processing-parallelism OFF magic-number markers
  (`\b500\b`/`\b8\b` would miss correct-direction answers naming other numbers) ONTO concept markers,
  and lightly softened concurrency-locking. id-generation-strategy-distributed was flagged the gold
  template (genuinely-split baseline). Marker invariants re-verified after every edit.
- `harness.py` — added `_diff_with_band` (Newcombe method-10 difference of two proportions, composed
  from the two Wilson intervals — no new dependency, paired-arms caveat documented) and a
  `differential` metrics block: `relevant_lift` = A_rate(relevant) − A_rate(baseline),
  `contamination_harm` = B_rate(contaminating) − B_rate(baseline). Added `load_case` + threaded the
  `case` label into the report/CLI with a case-aware honesty note and a `_fmt_diff` printer. Keys
  ADDED only — the explicit set + its tests are untouched.
- `tests/test_pull_contamination.py` — +7 tests (23 total): ambiguous case label, ambiguous
  taxonomy/shape, ambiguous four-way marker invariants (every contaminating_history argues B here),
  and differential math (empty-safe, sign + zero-exclusion, directional block).

**Validation (parent runs the real LLM pass):**
- `pytest tests/test_pull_contamination.py -x -q` → 23 passed.
- `--dry-run --scenarios scenarios_ambiguous.json` completes, 0 errors; differential bands render
  with the `*excludes 0*` flag. (Dry-run baseline reads ambiguous because the stub echoes the task,
  which names both options; the real agent picks one — stub artifact, not a signal.)

**State note:** real adversarial-synthetic LLM pass is the remaining gate before Ready for review.
