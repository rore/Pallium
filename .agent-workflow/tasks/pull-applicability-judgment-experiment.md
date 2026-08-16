# pull-applicability-judgment-experiment

Phase 3 of the pull-contamination experiment. Phases 1-2 found no contamination but never
stressed filtering (baseline was cue-determined, ~0.90 A). This phase tests the CORE pull
proposition per the sharpened review: can historical context supply knowledge the current task
CANNOT reconstruct (an arbitrary project-specific convention), while the agent still reasons
correctly about whether that knowledge APPLIES here (scope/provenance judgment)?

<!-- agent-workflow:start -->
**Outcome:**
A rerunnable eval over scenarios where (a) the correct convention A is ARBITRARY — not inferable
from best practice, so the no-history baseline is genuinely uncertain; (b) the task carries subtle
SCOPE/PROVENANCE cues (e.g. checkout-v2 vs v1, Project Y vs X) sufficient to judge whether a given
history applies, but NOT enough to reconstruct the convention; (c) relevant history gives the
correct in-scope convention (A); (d) contaminating history gives a REAL convention from a DIFFERENT
scope (B). Measures: baseline uncertainty, relevant_lift (applicable history should improve
materially), and contamination_harm (non-applicable history should be REJECTED, not adopted). This
finally tests applicability judgment, not impossible truth detection. No production behaviour change.

**Target:**
Pallium — `evals/pull_contamination/`. New `scenarios_applicability.json`; a small harness tweak so
the decision-first detector is primary for ANY non-explicit case; extend tests.

**Scope:**
- NEW `evals/pull_contamination/scenarios_applicability.json` (`case: "applicability-judgment"`),
  10 scenarios across scope-difference types (version, project, subsystem, superseded/older-state,
  environment).
- `evals/pull_contamination/harness.py` — generalise the CLI "primary detector" label so leading
  is primary for any case != "explicit-task" (currently hardcoded to "ambiguous-task"). No metric
  logic change.
- `tests/test_pull_contamination.py` — invariants for the applicability set + the primary-label rule.

**Constraints:**
- Deterministic marker scan stays primary (both detectors reported); no LLM judge as a gate.
- The convention must be genuinely arbitrary (no strong best-practice default), so baseline is not
  pinned. The task must contain the SCOPE cue but not the convention value.
- Do NOT assert a pinned baseline for this set.
- No production retrieval/injection change; offline; scratch only; no internal/product names.
- Backward compatible: explicit + ambiguous sets and their tests keep passing.

**Completion criteria:**
Harness runs the 3 conditions over the applicability set and reports baseline / relevant_lift /
contamination_harm with bands under the decision-first detector; tests cover the applicability
invariants + the primary-label rule; one real LLM pass yields a first read of (1) baseline
uncertainty, (2) whether applicable history materially lifts A, (3) whether non-applicable
(different-scope) history is rejected or adopted (the contamination/applicability signal).

**Risk:** Routine

**Complexity:** Moderate

**Reason:** `evals/**` + `tests/**` + `.agent-workflow/**` + `roadmap/**` all blue (offline,
scratch-only, no production surface) → Routine. Judgment-heavy scenario authoring (arbitrary
convention + scope provenance, baseline must stay unpinned) + a small harness tweak + tests →
Moderate, so expanded shape.

**Discovery:**
Harness already scenario-file-agnostic and emits both detectors + the differential (relevant_lift,
contamination_harm). The ambiguous pass proved the decision-first detector is the correct instrument
(strict over-counts ambiguity from comparative prose). The only harness gap is cosmetic: the CLI
labels the leading detector "PRIMARY for ambiguous-task" via a hardcoded case check; generalise to
"primary for any non-explicit case". This set differs from phase 2 in the MECHANISM of A's
correctness: not "cues imply A" (which let the agent reconstruct A and pinned the baseline) but "A
is arbitrary and only history carries it" — so baseline should finally be uncertain and history has
room to be decisive. Contamination here = adopting a convention from a demonstrably DIFFERENT scope.

**Material assumptions:**
- ASSUMPTION: conventions can be chosen arbitrary enough that the no-history baseline is genuinely
  uncertain (not pinned to A or B by a language/ecosystem default). DISPROVED BY: baseline A-rate or
  B-rate ~1.0. ACTION: pick conventions with no dominant default, or frame the task to state that a
  project-specific convention EXISTS and must be determined (so the no-history agent knows it is
  guessing).
- ASSUMPTION: the task's scope cue is sufficient for a careful agent to judge applicability (reject
  a different-scope convention). DISPROVED BY: relevant and contaminating conditions move the answer
  identically (agent ignores scope). ACTION: that is itself the finding — the hard problem is
  scope/applicability, not retrieval/triggering; report it.
- ASSUMPTION: the A/B convention stays deterministically detectable. Mitigated by the decision-first
  detector already shipped; both detectors reported.

**Plan:**
1. Author `scenarios_applicability.json`: 10 scenarios. Each task names a scope (service/version/
   project/subsystem/environment) and asks for an ARBITRARY convention value without stating it;
   relevant_history gives A scoped to the task's scope (applicable); contaminating_history gives B
   scoped to a DIFFERENT scope (non-applicable but real). marker_a/marker_b are the two convention
   values. Add `case: "applicability-judgment"`.
2. Harness: generalise the primary-detector label (leading primary when case != "explicit-task").
3. Tests: applicability invariants (marker containment; scope labels present in task + both
   histories) + the primary-label rule. Do NOT assert a pinned baseline.
4. Adversarial clean-context review of the set BEFORE the LLM run (catch baseline leaks / scope that
   is too obvious or too absent), then a real pass (seeds 0,1,2 → 30/condition).
5. Interpret: strong relevant_lift + low contamination_harm = pull proposition validated (stop
   synthetic, go real-corpus). High contamination_harm = the real hard problem is scope/applicability.

**Verification plan:**
- Applicability invariants → unit test for marker containment + scope labels in task and both histories, 10 scenarios across 5 scope types.
- Primary-label rule → unit test (leading primary for non-explicit case; strict primary for explicit).
- Backward compatibility → explicit + ambiguous tests still pass.
- First read → real LLM pass reports baseline (expect uncertain), relevant_lift (expect materially
  positive — the discriminating result phases 1-2 could not produce), contamination_harm.
- CI: agent-workflow, redline (BLUE), test lanes.

**Plan review:** Self (Routine). Design from the user-relayed sharpened review (applicability
judgment via scope/provenance, not impossible truth detection). Recorded here.

**Approvals:** Not required at this risk level (Routine).

**Exceptions:** —

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

- `scenarios_applicability.json` — 10 scenarios, 2 per scope type (scope-version, scope-project,
  scope-subsystem, scope-superseded, scope-client). `case: "applicability-judgment"`. Each task
  names its own scope and asks for an arbitrary convention value without stating it; relevant_history
  gives A scoped to the task's scope (applicable); contaminating_history gives B scoped to a
  different scope (non-applicable but real). Invariant added over prior sets: the task text itself
  must classify `ambiguous` (names both options, resolves neither) so the baseline is genuinely
  uncertain.
- `harness.py` — generalised the primary-detector rule: leading detector is primary for ANY case !=
  "explicit-task" (was hardcoded to "ambiguous-task"); added an applicability-judgment `case_note`.
  No metric-logic change.
- `tests/test_pull_contamination.py` — +4 tests (29 total): applicability case label,
  taxonomy/shape, marker + scope invariants (incl. task-is-ambiguous), and the primary-label rule.

**Validation (parent runs the real LLM pass):**
- `pytest tests/test_pull_contamination.py -q` → 29 passed.
- `--dry-run --scenarios scenarios_applicability.json` → 0 errors; label reads
  "[PRIMARY for applicability-judgment]"; differential bands render.

**State note:** adversarial scenario review + real LLM pass are the remaining gates.

## Evidence (real LLM pass)

Real pass (seeds/reps 0,1,2; 10 scenarios × 3 conditions = 90 trials;
`.local/research/pull_contamination_applicability_run.json`), decision-first detector (primary):

| metric | value | 95% band |
|---|---|---|
| baseline chose A | 0.433 | [0.27, 0.61] |
| relevant chose A | 1.000 | [0.89, 1.00] |
| **relevant_lift (A: rel−base)** | **+0.567** | **[+0.36, +0.73] — excludes 0** |
| contamination chose B | 0.500 | [0.33, 0.67] |
| **contamination_harm (B: cont−base)** | **−0.067** | **[−0.30, +0.18] — includes 0** |

**Two findings, one clean and one nuanced:**

1. **The core pull proposition is VALIDATED.** For the first time the baseline is genuinely split
   (0.43 A — the convention is arbitrary and unknowable without history), and APPLICABLE (in-scope)
   history reliably supplies it: relevant went **3/3 to the correct answer in all 10 scenarios**,
   lifting A from 0.43 → 1.00 (relevant_lift +0.57, excludes 0). History provides otherwise-
   unavailable knowledge and the agent uses it — the discriminating result phases 1–2 could not
   produce (there baseline was cue-determined, so history had no room to move the answer).

2. **Applicability/scope judgment WORKS ON AVERAGE BUT IS IMPERFECT AND TYPE-DEPENDENT.** Aggregate
   contamination_harm ≈ 0, but that is a NET of real per-scenario structure (harm = contaminating B
   − baseline B, n=3/arm):
   - `branch-naming-prefix` (**scope-superseded**): harm **+3** — baseline 3/3 CORRECT (feat/) →
     contaminating 3/3 WRONG (feature/). A plausible out-of-scope "earlier standard" FLIPPED a
     correct answer to wrong every time. Clean contamination.
   - `checkout-json-key-casing` (scope-version): harm +1 (mild).
   - `harbor`, `billing`, `marketing`: harm **−2** each — seeing "another scope does B" pushed the
     agent AWAY from B (it used the out-of-scope signal as evidence NOT to apply it). Genuine
     scope-reasoning.
   - Remainder: harm 0 (baseline already at that value, or agent rejected the out-of-scope value).

**Interpretation for the pivot:** the reviewer's either/or ("works → real-corpus; fails → the hard
problem is scope/applicability") resolves to BOTH. The pull VALUE is real and strong; the RISK is
real but concentrated in superseded/older-state conventions, where plausible out-of-scope history
can flip a correct answer to wrong. The agent's scope-reasoning is inconsistent, not absent.

**Honest scope / caveats:**
- n=30/condition (10 scenarios × 3 reps), single model, synthetic; "seeds" are repetition indices,
  not provider sampling seeds; CIs over scenario × repetition. Per-scenario n=3 → the branch-naming
  +3 is a striking SIGNAL, not a calibrated rate.
- `control_used_history_rate` (lexical proxy) is ~0.03 and uninformative here — the +0.57 lift is the
  real evidence history was used.
- The strong, uniform relevant_lift is the robust headline; the superseded-contamination edge is the
  actionable finding for real-corpus validation to confirm.

Verdict: **core pull proposition validated (applicable history materially and reliably helps);
scope/applicability is the real hard edge, concentrated in superseded conventions.** Recommend
proceeding to real-corpus validation with a targeted watch on superseded/older-state scope.

**State:** Ready for review
