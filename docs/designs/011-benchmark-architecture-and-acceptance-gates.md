# Benchmark Architecture And Acceptance Gates

## Goal

Define the benchmark architecture that should govern Pallium's evaluation
program going forward.

This document is the canonical benchmark-architecture reference for Pallium.
It does not replace narrower design documents for specific benchmark families.
It defines the stable structure those narrower benchmark efforts should fit.

## Product Boundary

Pallium is a bounded memory sidecar for thin downstream agents.

The benchmark program should therefore answer:

- did Pallium make the right memory decision?
- did Pallium stay quiet when it should?
- did Pallium return integration-ready carry-forward without semantic cleanup by
  the downstream agent?
- did it avoid stale, wrong-scope, privacy-unsafe, or low-value memory?

The benchmark program should not collapse into generic assistant scoring or
opaque end-to-end answer judging.

It should also treat the benchmark system itself as a product surface with
first-class repo-local objects:

- traces
- datasets
- experiments
- review queues
- replay promotions

Those should remain Pallium-owned artifacts even if external tooling later
helps visualize or run them.

## Generalization Discipline

Real downstream incidents are valuable inputs, but the benchmark program should
translate them into Pallium-native failure classes before they become repo
assets or implementation drivers.

That means:

- replay assets should be scrubbed, generalized, and anonymized before they are
  committed
- benchmark runners and fixtures should validate generalized memory behaviors,
  not product-specific terminology or one-off incident vocabulary
- future work should be named and reasoned about as retrieval policy, routing
  policy, packaging policy, memory-worthiness policy, lifecycle or supersession
  policy, compatibility handling, and benchmark failure families
- downstream incidents are input signals for Pallium, not the benchmark
  architecture's own vocabulary

## Benchmark Lanes

Pallium should organize its benchmark stack into five lanes.

### 1. Contract Lane

This is the primary caller-facing hard gate.

It validates the thin-agent contract:

- should_inject
- decision_reason
- injectable_blocks
- injected block identity and content
- block cap behavior
- same-thread no-value suppression
- consistency between query and query-debug outputs

Default grading:

- deterministic only

### 2. Trace Lane

This is the primary internal-decision hard gate.

It validates the decision path that led to the contract result:

- query-family inference
- routing and layer choice
- candidate competition
- freshness ordering
- stale-memory suppression
- wrong-memory and privacy guards
- low-value promotion suppression
- rebuild churn control

Default grading:

- deterministic only

Explainability is part of the product claim, so this lane is not optional.

### 3. Usefulness Lane

This lane answers a narrower question:

Did Pallium's carry-forward help in a bounded, thin-agent-safe way?

It should focus on:

- compactness
- task orientation
- evidence backing
- correct scope
- lack of semantic cleanup burden on the downstream agent

Default grading:

- deterministic when possible
- narrow rubric or pairwise judging only when deterministic checks are
  insufficient

This lane is secondary to contract and trace correctness. It should not become
open-ended answer grading.

### 4. Realism Lane

This lane provides realistic pressure from reviewed scenario sets.

It should include:

- authored product-shaping scenarios
- reviewed public-corpus slices
- external benchmark pressure packs
- replay fixtures promoted from real misses

Its job is to provide messy phrasing, realistic continuation shape, and
non-handcrafted failure pressure without replacing the product boundary.

### 5. Operational Lane

This lane tracks quality-affecting behavior that may not show up as an obvious
correctness miss in a single scenario:

- over-injection rate
- injected block count distribution
- low-value promotion rate
- rebuild churn rate
- stale-memory failure rate
- latency
- provider cost
- benchmark flakiness across repeated runs

Operational signals are not secondary polish. For a memory sidecar, technically
correct but noisy behavior is still a product failure mode.

## Hard Gates vs Tuning Signals

The benchmark program should distinguish hard gates from tuning signals.

### Hard Gates

By default, these should stay green before broader rollout:

- contract-lane correctness
- trace-lane correctness
- zero privacy leaks
- zero wrong-memory selection failures
- zero same-thread no-value overreach failures
- zero low-value promotion failures
- zero thread-rebuild churn failures beyond the accepted bounds

### Tuning Signals

These should guide prioritization and tuning, but do not need to block every
change by default:

- paraphrase and indirect-query success rate
- stale-memory and freshness failure rate
- usefulness-lane scores
- public-corpus pressure results
- external benchmark pressure results
- latency and cost trends

The hard-gate question is whether Pallium is safe and contract-correct. The
tuning question is where Pallium should improve next.

## Dataset Tiers

Every benchmark asset should fit one of three dataset tiers.

### Iteration

Small, fast, high-signal cases used during active tuning.

Purpose:

- catch obvious regressions fast
- support local iteration on routing, packaging, and memory-worthiness changes

### Confidence

Stable reviewed sets used for aggregate metrics and the main confidence report.

Purpose:

- provide trustworthy aggregate rates
- resist accidental drift in what good enough means

### Replay

Promoted misses from live usage or external pressure packs.

Purpose:

- turn observed failures into permanent regressions
- keep the benchmark vocabulary grounded in real misses

The benchmark program should report by lane and by dataset tier rather than
only by runner name.

## Benchmark System Objects

The benchmark architecture should make a few system objects explicit instead of
letting them remain spread across ad hoc runners and output folders.

### Traces

Structured records of benchmark or live-query execution that capture the
decision path, contract output, and operational metadata needed for review.

### Datasets

Reviewed benchmark assets grouped into iteration, confidence, or replay tiers.

### Experiments

Repeatable comparisons of one Pallium version, prompt, or heuristic change
against a chosen dataset slice with lane-aware scoring.

### Review Workflow

A bounded review path for suspicious cases, borderline usefulness checks, and
promotion into replay fixtures.

These should be treated as first-class repo-local benchmark concepts, not just
implementation details hidden inside individual scripts.

## Judging Policy

Deterministic grading should remain the benchmark foundation.

Use LLM judging only when deterministic scoring cannot answer the narrow
question being asked.

If LLM judging is introduced:

- use constrained rubrics or pairwise comparison, not open-ended quality
  judging
- prefer order-swapped comparisons when judging alternatives
- keep outputs structured and reviewable
- escalate uncertain or policy-sensitive cases to human review

The best use for LLM judging in Pallium is likely the usefulness lane, not the
contract or trace lanes.

## External Pressure Packs

External memory benchmarks are part of the realism lane, not the product
acceptance gate.

Their role is to pressure Pallium's core memory engine on failure families that
internal product-shaped suites may under-sample, especially:

- stale-memory handling
- update correctness
- temporal ordering
- long noisy recall
- multi-hop memory use
- incremental memory degradation

Every adopted external slice should map back into Pallium's own failure
taxonomy and, where valuable, should promote misses into Pallium-owned replay
or authored regressions.

External benchmark numbers should be reported separately from thin-agent
acceptance metrics.

Commercial or hosted eval products may be useful design references for how
traces, datasets, experiments, and review workflows can fit together, but they
should not become required dependencies for Pallium's benchmark architecture.

## Live Miss Promotion

The benchmark program should support one repeatable loop:

1. detect a suspicious live miss
2. scrub and generalize it into a bounded miss bundle
3. classify it with Pallium's failure taxonomy
4. promote it into replay assets when it is durable and representative
5. keep it as part of the reviewed regression set

This is the main mechanism for keeping the benchmark program grounded in real
interaction quality without depending on private downstream traffic in the repo.

## Recommended Current Shape

Pallium's current benchmark direction should now be interpreted as:

- contract lane and trace lane are the acceptance foundation
- developer-work and continuation scenarios remain a key realism layer
- low-value and churn behavior is first-class benchmark behavior
- usefulness judging should remain narrow and disciplined
- external benchmark packs are the next complementary pressure layer
- live miss to replay promotion is the next benchmark maturity step after the
  external pressure pack lands

## What This Document Replaces

This document replaces the implicit benchmark architecture that previously had
to be inferred from:

- individual eval runners
- the developer-work continuity benchmark design
- confidence-suite output structure
- roadmap feature prose

Those narrower documents should now align to this benchmark architecture rather
than each defining a separate benchmark philosophy.
