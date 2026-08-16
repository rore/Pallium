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

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

Built the offline filtering harness under `evals/pull_contamination/`:

- `harness.py` — runner + metrics + CLI. Per scenario × seed × condition it
  **forces** the condition's history into the agent's context (no pull decision)
  to isolate the FILTERING hypothesis. History is presented the same way a real
  pull result would be: rendered via `history_pull_decision.agent._render_results`
  behind a FINALIZE/AFTER-style system prompt. `classify_answer` is the primary
  deterministic signal (case-insensitive regex marker scan → chose_A / chose_B /
  ambiguous). `references_history` is a documented lexical-overlap PROXY for the
  control's used-history metric. Metrics: `baseline_choose_A_rate`,
  `control_choose_A_rate`, `control_used_history_rate`, `contamination_rate`
  (chose_B in the test arm — headline), and per-condition ambiguous rates, each
  with a Wilson 95% band (imported `_wilson_95` from
  `historical_lookup_measurement`, not reimplemented). CLI: `--scenarios`,
  `--seeds` (default 0,1,2), `--dry-run` (scripted stub, no network),
  `--cache-dir`, `--no-eval-cache`, `--output`.
- `scenarios.json` — 10 scenarios, 2 per taxonomy type (same-topic-wrong-subtask,
  old-superseded-decision, similar-project-different-convention,
  related-investigation-different-conclusion, benign-irrelevant). Each task pins
  A from the task text alone; contaminating_history plausibly argues B. Invariants
  (tested): marker_a matches relevant_history and NOT contaminating_history;
  marker_b does NOT match relevant_history. Benign scenarios are true negative
  controls (contaminating text matches neither marker). No internal/product names.
- `__init__.py`, `__main__.py` (delegates to `harness.main`).
- `tests/test_pull_contamination.py` — 14 fast, network-free unit tests over the
  A/B detection (A-only→chose_A, B-only→chose_B, both/neither→ambiguous, regex +
  word-boundary + ms markers), the used-history proxy, scenario invariants, metric
  shaping (empty-safe + Wilson bands), and a full scripted dry-run chain.

**Design deviation from the mirror plan:** the harness does NOT use
`InProcessService`/a scratch DB. Because the refined design FORCES history into
the prompt (rather than measuring a pull), no retrieval/service/DB is needed — the
experiment reduces to an LLM call per condition, which keeps production surfaces
untouched by construction and removes the DB-lifecycle machinery entirely.

**Validation (parent to run the real LLM pass):**
- `pytest tests/test_pull_contamination.py -x -q` → 14 passed.
- `python -m evals.pull_contamination.harness --dry-run --seeds 0,1,2` completes
  and prints metrics. Scripted stub simulates a maximally-contaminatable agent
  (echoes the salient guidance), giving the expected wiring demonstration:
  baseline_choose_A=1.000, control_choose_A=1.000, control_used_history=1.000,
  contamination_rate=0.800 (24/30 = the 8 non-benign scenarios chose_B),
  ambiguous[contaminating]=0.200 (the 2 benign scenarios), 0 errors. Dry-run
  values are scripted placeholders; the real LLM pass is left to the parent.

## Evidence (real LLM pass)

Real adversarial-synthetic run (seeds/repetitions 0,1,2; 10 scenarios × 3 conditions = 90
trials; `.local/research/pull_contamination_run_v2.json`), AFTER the CodeRabbit fixes
(opaque trial tag — no condition-label leak; retry markers cover number+word forms):

| metric | rate | 95% band |
|---|---|---|
| baseline chose A (no history) | 1.000 (30/30) | [0.89, 1.00] |
| control chose A (relevant history) | 0.900 (27/30) | [0.74, 0.97] |
| **contamination (chose B, wrong history)** | **0.000 (0/30)** | **[0.00, 0.11]** |
| ambiguous (contaminating arm) | 0.033 (1/30) | [0.01, 0.17] |
| control_used_history (proxy) | 0.333 | [0.19, 0.51] |

**0% hard contamination — robust to the confound.** The first pass (v1) leaked the
condition label into the model prompt (`cond=contaminating_history`); CodeRabbit flagged it.
After switching to an OPAQUE trial tag so the model cannot tell which history is wrong,
contamination stayed **0/30** — so the result was not an artifact of the leak. The marker
fix (number+word forms) also collapsed the false-ambiguous rate (20% → 3%), confirming
those were correct A-choices (agent named B only to reject it).

**Honest scope / caveats:**
- Tests the EXPLICIT-TASK case (the task text pins A). 0% contamination is
  necessary-not-sufficient — it shows the agent won't override a clear instruction, not that
  it filters when the task is ambiguous and history is the main signal. That harder case is
  the next experiment.
- n=30/condition (10 scenarios × 3 repetitions), single model, synthetic. Upper Wilson
  bound 11.4% — can't rule out low-single-digit contamination.
- "seeds" are REPETITION indices (cache-key variation for independent draws), not provider
  sampling seeds; CIs are over scenario × repetition.
- `control_used_history_rate` is a lexical-overlap proxy and low (0.33) — expected, since
  the task already states A.
- FOLLOW-UP: the marker rule is still conservative (both markers → ambiguous); a richer
  detector could distinguish "adopted B" from "named B to reject."

Verdict: **preliminary GREEN for agent-in-the-loop filtering in the explicit-task case,
robust to the label-leak confound** — supports proceeding with the pivot; the
ambiguous-task + real-corpus passes remain.

