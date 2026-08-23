# Validation

This page summarizes the validation surface for Pallium.

The validation model is now organized by explicit benchmark lanes and dataset
tiers instead of only by historical runner names.

## Benchmark Lanes

Pallium's benchmark program uses five lanes:

- `contract`: thin-agent memory contract correctness, including query contract,
  packaging contract, and boundary discipline
- `trace`: routing, retrieval, and decision-trace correctness for the memory
  path that was chosen
- `usefulness`: narrow deterministic checks for whether memory should help in
  the current product slice
- `realism`: reviewed pressure from messier follow-ups and public-corpus slices
  that should influence tuning without replacing the hard gate
- `operational`: low-value promotion, rebuild churn, over-injection, and other
  drift signals the repo can measure defensibly today

`contract` and `trace` are the hard-gate acceptance lanes.

`usefulness`, `realism`, and `operational` are tuning or pressure lanes. They
matter for prioritization and tuning, but they do not replace the acceptance
gate for the thin-agent memory contract and decision trace.

## Dataset Tiers

Benchmark assets are also classified into three dataset tiers:

- `iteration`: fast, local tuning slices used during development
- `confidence`: reviewed assets that make up the current repo-local confidence
  gate
- `replay`: replay-style assets promoted from real or exploratory misses into
  durable regression inputs

Replay is now first-class in both the reporting model and the local tooling,
although replay coverage is still much smaller than the authored confidence
packs.

## Current Benchmark Mapping

The current benchmark suites map into the architecture as follows:

- `memory_routing`: lane focus `trace`, tier `confidence`, contributes to hard
  gate coverage for both `contract` and `trace`
- `work_resumption`: lane focus `realism`, tier `confidence`, contributes to
  `contract`, `trace`, `usefulness`, `realism`, and `operational`
- reviewed `public_corpus` slices: lane focus `realism`, tier `confidence`,
  contribute to `contract`, `trace`, `usefulness`, `realism`, and `operational`
- `low_value_churn`: lane focus `operational`, tier `confidence`, contributes to
  `trace` and `operational`
- `recurring_question`: lane focus `usefulness`, tier `iteration`, contributes
  to `usefulness` and `realism`

This keeps the deterministic core centered on the current product claim:
conversation continuity, resumed work, scoped recall, and thin-agent memory
behavior.

## Eval Toolbox

Before proposing or building a new eval, check whether one of these already
fits. The repo has 80+ scripts under `evals/`; the table below is the
short list of tools that map to common questions during development.

All entries are deterministic on the inputs they consume unless noted.
"Replay" means reads from the live SQLite DB or `query_audit_log`
snapshots and applies a rule — no LLM in the harness itself.

| Question / intent | Tool | Determinism | Cost |
|---|---|---|---|
| Would gating rule X have changed past injections on real threads? | `evals/anchor_probe/thread_replay.py --rule {R1..R7,baseline}` | Replay, no LLM | Seconds |
| Add a new gating rule and replay it | Add `rule_X` in `evals/anchor_probe/replay_harness.py`, register in `thread_replay.RULES` | Replay, no LLM | 10 LOC |
| Pass/fail on real-data scenarios with no LLM judge | `evals/live_value_scenarios/runner.py` | Structural assertions | Seconds, needs running service |
| 4-check + skip-pressure pipeline on rated slice | `evals/validation_runner.py` | Replay on rated cases | Seconds |
| Sweep injection-gate thresholds against audit data | `evals/injection_precision_eval.py` | Audit replay | Seconds |
| Replay full injection decisions under counterfactual rules | `evals/injection_replay_simulation.py` | Audit replay | Seconds |
| End-to-end realistic agent conversations | `evals/agent_conversation_runner.py` | Scenario-driven, runs through TestClient | Minutes |
| Task-checkpoint resumption (paraphrased / noisy variants) | `evals/work_resumption_benchmark.py` | Scenario-driven | Minutes |
| Recurring-question recall (did the same answer surface again) | `evals/recurring_question/` (scenarios.json + runner) | Scenario-driven | Minutes |
| Canonical milestone scenario (positive / no-value / scope-guard) | `evals/integration_readiness_scenario.py` | Scenario-driven | Minutes |
| Counterfactual hypothesis on real audit data ("would prompt X have helped?") | `evals/anchor_probe/counterfactual_*.py` template family | LLM-judge with seed; not deterministic, judge variance ~20pp | Minutes |
| LoCoMo / LongMemEval end-to-end accuracy | `evals/locomo_benchmark.py` / `evals/longmemeval_benchmark.py` | LLM-judge, stochastic | Hours, expensive |
| Exploratory QA invariant scenarios (generated) | `evals/generated_exploratory/invariant_runner.py` | Scenario-driven | Minutes |
| Fact consolidation retrieval quality | `evals/fact_consolidation_eval.py` | Scenario-driven | Minutes |
| Low-value promotion / churn drift | `evals/low_value_churn_benchmark.py` | Scenario-driven | Minutes |
| Routing decision quality | `evals/memory_routing_benchmark.py` | Scenario-driven | Minutes |
| Derivation coverage + fidelity, source-episode-first ("did an episode produce a faithful derived object at all, and how faithful?") | `evals/derivation_fidelity` | Coverage = replay, no LLM; fidelity = LLM-judge, N independent samples (stochastic) | Minutes |
| RAW/DERIVED/HYBRID retrieval + representation, replay-based ("on a real lookup, did the relevant source vs derived object get recovered, and is the derived text a correct answer surface vs the RAW turns — at equal token budget?") | `evals/raw_derived_hybrid` | Candidate-recovery = evidence-link replay, no LLM; representation = LLM-judge, N independent samples (stochastic); context cost = deterministic equal-token-budget | Minutes |

### When to reach for which

- **Building a new gating or filter rule** → start in `anchor_probe/replay_harness.py`. Add a `rule_X` function, plug into `thread_replay.RULES`, run against real threads. No production change, no LLM, fast iteration.
- **Asking "would prompt change Y catch noise?"** → use the `anchor_probe/counterfactual_*.py` template family. These call the production Sonnet judge; expect ~20pp variance across seeds, so run ≥3 seeds and report consensus.
- **Validating that a known good scenario still passes** → `live_value_scenarios/runner.py`. Categories: `constraint_carry_forward`, `investigation_continuation`, `analysis_handoff`, `decision_recall`, `negative_no_inject`. Structural pass/fail only.
- **Pre-ship checks on a routing or extraction change** → `validation_runner.py` runs the 4-check + skip-pressure pipeline on the rated slice. This is the production-data validation gate.
- **End-to-end accuracy comparison vs the field** → `locomo_benchmark.py` / `longmemeval_benchmark.py`. Expensive, judge-driven, not for fast iteration.

### Anti-patterns

- **Don't write a new "deterministic eval slice" before checking whether `live_value_scenarios` or `thread_replay` already fits.** Both shipped 2026-05-27 and cover most "would change X have helped on real data" shapes.
- **Don't trust single-seed judge calls on small samples.** ~20pp variance is real (see `lessons.md`); use ≥3 seeds and a consensus rule, or pick a deterministic-replay tool instead.
- **Don't conflate retrieval recall with end-to-end accuracy.** R@5 of 95% on LongMemEval-S is session-id-in-top-5, not QA. Pick the metric that matches the claim.

## Reuse Judge Reference-Set Validation

The reuse judge is checked against a maintained single-author reference set and
against a second independent seed group. This is a regression and stability
signal, not proof of objective correctness or independent human agreement.

- **Reference fixture:** evals/fixtures/reuse_gold/gold_lookups.json contains 12
  synthetic lookups: 4 incorporation, 4 influence, and 4 none.
- **Runner:** python -m evals.reuse_judge_calibration --seed-groups
  "0,1,2;3,4,5" seeds two scratch databases, disables the evaluation cache, and
  judges the same ordered cases with both disjoint groups.
- **Report:** records prompt id/version, each group-vs-reference kappa, confusion
  matrix, per-class precision/recall/support, mutual group kappa, comparison N,
  and missing/failed event IDs.
- **Sole live threshold:** GOLD_KAPPA_THRESHOLD = 0.70. The reference-set check
  passes only when both group-vs-reference kappas and mutual kappa meet 0.70,
  every expected event is compared, and neither group has a missing/all-failed
  event. Failed checks keep rung rates visibly uncalibrated.

### Historical evidence

- 2026-08-14, old rubric, seeds 0/1/2: judge-vs-reference κ=0.50 (N=12,
  no judge failures), seed-vs-seed κ=1.0. The judge collapsed all four influence
  cases upward to incorporation. The former live gate was 0.60; this result also
  fails the current 0.70 gate.
- After the incorporation/influence rubric was aligned, a provisional rerun
  produced κ=0.75 (N=12, no failures), with two of four influence cases
  recovered and seed-vs-seed κ=1.0. This is historical single-group evidence,
  not completion of the current two-group reference-set gate.
- 2026-08-23, current prompt, cache disabled: the two-group reference-set gate
  **passed**. Group A (seeds 0/1/2) κ=0.750, N=12; group B (3/4/5) κ=0.875,
  N=12; mutual group κ=0.870, N=12; zero judge failures. All three comparisons
  exceed the 0.70 threshold. This confirms repeatable agreement with the
  maintained examples, not independent human correctness.

### Honesty limitations

- N=12 yields a wide kappa uncertainty range.
- The labels and scenarios are single-author and synthetic; there is no
  human-human agreement baseline and the distribution may differ from real
  lookup traffic.
- Passing protects against known regressions and unstable judge runs. It does
  not establish that the reference labels are objectively correct.
- The fixture must not be tuned merely to force a pass.

## Confidence Gate

The developer-work confidence report now rolls up by lane and tier first.

The current confidence gate is defined by:

- hard-gate coverage for `contract` and `trace` must be present before the gate can go green
- hard-gate status for `contract`
- hard-gate status for `trace`
- reviewed `confidence`-tier coverage from `memory_routing`,
  `work_resumption`, reviewed public-corpus slices, and `low_value_churn`

The same report also separates:

- realism pressure from acceptance failures
- replay-tier pressure from current hard-gate status
- operational drift from correctness failures
- dominant tuning bottlenecks from dominant failing benchmark lanes

Read the hard-gate fields first. Scenario totals and realism counts are not a
replacement for `hard_gate_passed` or `confidence_gate_passed`.

## Operational Metrics Surfaced Today

Current reporting surfaces operational signals only where the repo already has
defensible data:

- injected block count distribution
- no-value overreach rate
- stale-memory failure rate
- wrong-memory selection failure rate
- low-value promotion failure rate
- thread rebuild churn failure rate
- live exploratory drift metrics such as:
  - injection rate
  - sharp miss rate
  - fallback rate
  - rebuild rate
  - generic-summary win rate

The repo does not yet treat latency, provider cost, or broad flakiness as
formal benchmark metrics by default.

## Live Improvement Support

Pallium now also has a bounded live-improvement loop for local exploratory work.

Current shipped pieces:

- drift metrics emitted by the live exploratory runner
- shadow comparison for routing override experiments
- replay promotion tooling that converts captured exploratory runs into replay
  scenario skeletons

This does not replace the benchmark program. It helps turn real misses into
reviewable, rerunnable assets faster.

## What Remains Uncertain

The main remaining uncertainties are:

- how broad replay coverage should become as more live misses are promoted
- how far resumed-work packaging generalizes across broader downstream traffic
- where realism pressure should trigger new authored scenarios versus better
  deterministic checks
- whether lexical retrieval remains sufficient or whether retrieval itself
  becomes the next hard bottleneck

## Why This Matters

The validation surface is part of how Pallium is developed:

- acceptance stays anchored to the thin-agent memory contract and trace
- realism pressure can inform tuning without redefining the product target
- replay now has both a reserved place in the model and an initial promotion
  workflow in tooling
- operational drift is visible instead of being buried under correctness totals
