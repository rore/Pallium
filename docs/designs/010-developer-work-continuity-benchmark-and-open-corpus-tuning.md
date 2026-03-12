# Developer-Work Continuity Benchmark And Open-Corpus Tuning

## Goal

Define the next evaluation layer needed to tune Pallium for Pelican-like
developer-work continuity without depending on private downstream traffic.

This design is not a single benchmark file. It is a benchmark program that
combines:

- authored resumed-work scenarios
- realistic public conversation data
- task-oriented external pressure tests
- explicit failure-family analysis

The purpose is to make Pallium tunable against the work shape that matters:
interrupted investigation, resumed implementation, blocker recovery, and
cross-session carry-forward of learned state.

## Why Current Evaluation Is Not Enough

Pallium now has several useful evaluation layers:

- recurring-question benchmark
- memory-routing benchmark
- tiered-memory validation benchmark
- work-resumption benchmark
- public-corpus evaluation through WildChat
- complementary public task pressure through WildBench

These are good guardrails, but they still leave a gap.

They make Pallium believable for:

- recurring-question handling
- routing across current memory layers
- bounded resumed-work continuity in authored scenarios
- real interaction phrasing pressure

They do not yet make Pallium fully believable for the broader Pelican-shaped
problem:

- interrupted tool-heavy investigation
- resume after auth or tool failure
- ticket work resumed after a pause
- review and implementation continuity
- deciding when memory should stay quiet
- privacy-safe continuity once mixed public/private memory exists

So the next tuning layer should be a broader developer-work continuity program,
not just more synthetic prompt cases and not just more retrieval architecture.

## Product Question

The benchmark program should answer:

Can Pallium preserve and reuse learned work state well enough that a later
continuation is materially better, while staying bounded, evidence-backed, and
privacy-safe?

That should be the main tuning question before larger retrieval expansion.

## Design Principles

1. Tune for work continuity, not only question answering.
2. Preserve clear failure attribution instead of collapsing all misses into one
   score.
3. Use open corpora to increase realism, not to replace authored product
   scenarios.
4. Keep benchmarks narrow enough to review but broad enough to expose routing,
   packaging, and recall failures.
5. Include strong no-value and wrong-memory guard cases.
6. Do not let benchmark growth turn Pallium into a workflow engine.

## Benchmark Portfolio

The benchmark program should have three layers.

### 1. Canonical Authored Developer-Work Suite

This is the main product-shaping layer.

It should expand the current work-resumption benchmark into a broader suite of
developer-work scenario families:

- resumed investigation after a pause
- debugging resumed from partial findings
- auth or tool failure recovery
- ticket understanding resumed after interruption
- implementation resumed after partial progress
- review feedback carry-forward
- repeated context question phrased differently later
- same-thread no-value continuation
- stale or wrong prior-state trap
- later privacy/mixed-visibility guard cases

Why this layer matters:

- it is the only place where we can encode the exact Pallium value claim
- it keeps the benchmark tied to product semantics instead of only corpus
  convenience
- it can express expected winning memory layer and forbidden behaviors

### 2. Open-Corpus Continuation Pack

This layer should mine and review real public interaction data for continuation
and follow-up shape.

Primary source:

- WildChat as the realism corpus

Purpose:

- messy continuation phrasing
- later-turn follow-ups
- no-value continuation cases
- paraphrased resumed-work prompts

This layer should produce reviewed slices, not raw benchmarking over the whole
corpus.

### 3. External Task Pressure Pack

This layer should pressure-test Pallium against realistic user-task prompts that
are not authored in the repo.

Primary source:

- WildBench as the task-oriented pressure benchmark

Purpose:

- realistic prompt/task phrasing
- paraphrase pressure
- harder retrieval and routing acceptance checks

This layer is best used as an acceptance benchmark for changes already justified
by the authored suite and continuation pack.

## Scenario Taxonomy

The canonical authored suite should classify scenarios by work shape, not just
by prompt wording.

Recommended scenario families:

### Investigation Continuity

- prior findings should orient the continuation
- prior failed hypotheses should not be repeated blindly
- evidence should remain visible when needed

### Blocker Recovery

- a prior blocker or failed attempt should carry forward
- the continuation should know what failed
- the next useful step should not restart from zero

### Implementation Continuity

- chosen direction should carry forward
- key constraints and rejected paths should survive interruption
- next-step guidance should be compact, not transcript replay

### Review Continuity

- prior objections and accepted constraints should carry forward
- later continuation should not rediscover already-rejected ideas

### Repeated Context Questions

- broad recurring recall may favor `pattern_memory`
- repeated-answer carry-forward may favor `continuity_memory`
- resumed-work state may favor `task_checkpoint`

### No-Value Continuation

- current thread already contains enough state
- Pallium should add little or nothing

### Wrong-Memory Guards

- same topic, wrong thread
- stale checkpoint
- broad pattern memory where exact evidence should win
- later privacy/mixed-visibility trap

## Per-Scenario Labels

Each reviewed scenario should include explicit labels.

Recommended labels:

- `scenario_family`
- `should_memory_help`
- `expected_intent`
- `expected_primary_layer`
- `acceptable_fallback_layers`
- `forbidden_layers`
- `must_preserve`
- `must_not_introduce`
- `expected_gap_target` when a scenario is designed to expose a missing slice

Recommended `must_preserve` values:

- `task_orientation`
- `key_findings`
- `blocker_state`
- `preserved_progress`
- `next_step_guidance`
- `evidence`
- `freshness`

Recommended `must_not_introduce` values:

- `wrong_thread_state`
- `stale_state`
- `unsupported_recommendation`
- `higher_level_overreach`
- `privacy_leak`

## Scoring Model

The benchmark should not collapse all behavior into one score.

Recommended score dimensions:

- `memory_helped`
- `primary_layer_correct`
- `intent_correct`
- `task_orientation`
- `key_findings_reused`
- `blocker_state_preserved`
- `preserved_progress`
- `next_step_guidance`
- `evidence_preserved`
- `freshness_preserved`
- `no_value_guard`
- `wrong_memory_guard`

## Failure Taxonomy

The report should explicitly classify failures into families.

Current and recommended failure families:

- `retrieval_recall_failure`
- `routing_layer_choice_failure`
- `result_packaging_evidence_failure`
- `compact_task_state_failure`
- `no_value_overreach_failure`
- `stale_memory_failure`
- `wrong_memory_selection_failure`
- later `privacy_leak_failure`

This is the core of the tuning loop. If Pallium changes, we should know whether
it improved recall, routing, or packaging rather than arguing from anecdotes.

## How Open Data Should Be Used

Open corpora should be used in two distinct ways.

### WildChat

Use WildChat to mine reviewed continuation and paraphrase slices.

Best uses:

- messy follow-up wording
- continuation prompts
- same-thread no-value cases
- later-turn clarification prompts
- loosely resumed-work language such as:
  - "what did we find"
  - "where were we"
  - "what should I do next"
  - "what blocked us"

Recommended workflow:

1. filter candidate conversations
2. build candidate episodes
3. sample continuation-oriented cases
4. review and label them
5. promote representative cases into committed manifests

WildChat should improve realism and paraphrase coverage, not define the whole
benchmark program.

### WildBench

Use WildBench as a complementary acceptance and pressure-test layer.

Best uses:

- realistic external task prompts
- paraphrase pressure
- acceptance testing after routing or retrieval changes

WildBench should not be the main source of resumed-work structure. It is better
for prompt pressure than for task-state continuity semantics.

## Tuning Loop

The benchmark program should support a repeatable tuning loop.

1. Make a narrow Pallium change.
2. Run the authored developer-work suite.
3. Run the reviewed WildChat continuation slice.
4. Run the WildBench pressure slice.
5. Compare failure-family deltas.
6. Only keep the change if it improves the intended failure family without
   increasing overreach or wrong-memory behavior.

This matters especially for:

- routing tweaks
- `task_checkpoint` packaging changes
- result formatting changes
- later vector retrieval
- later hybrid fusion

## What This Should Help Decide

The benchmark program should help answer:

- is routing still the main problem?
- is result packaging still the main problem?
- is lexical recall now the real bottleneck?
- is `task_checkpoint` actually improving developer-work continuity?
- when should Pallium stay quiet?
- after privacy lands, are public/private boundaries holding?

This is the mechanism that should justify later retrieval expansion.

Vector retrieval should move forward only if this benchmark program shows recall
failures are now the dominant limitation after the continuity and privacy slices
land.

## Deliverables For The Future Work

The eventual implementation effort should likely produce:

- one expanded developer-work continuity benchmark suite
- one reviewed WildChat continuation/paraphrase pack
- one bounded WildBench acceptance pack
- shared failure taxonomy and reporting across all three
- guidance dashboards or summaries that show which failure family dominates

## Suggested Sequencing

Recommended sequence after current privacy and integration-readiness work:

1. expand the authored work-resumption suite into a fuller developer-work
   continuity benchmark
2. mine and review WildChat continuation slices
3. connect WildBench as an acceptance pack over the same failure taxonomy
4. use this combined benchmark program to decide whether routing, packaging, or
   retrieval should be tuned next

## Recommendation

Treat this as the benchmark program that should tune Pallium toward Pelican-like
value without requiring private downstream traffic.

It should remain broader than the current work-resumption benchmark, but still
bounded enough to review and reason about.
