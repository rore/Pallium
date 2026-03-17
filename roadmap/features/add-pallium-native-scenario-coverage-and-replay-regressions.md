---
id: add-pallium-native-scenario-coverage-and-replay-regressions
title: Pallium-native scenario coverage and replay regressions
status: queued
priority: high
commitment: committed
milestone: Next
lane: stabilization-safety
---

## Summary

Expand Pallium's direct test surface so most memory-quality validation can run
inside Pallium itself without relying on a downstream agent as the primary
diagnostic surface.

This feature makes repo-local scenario and replay coverage broader, more
product-shaped, and easier to use for regression gating:

- more direct ingest/query/query-debug scenario coverage
- more replayable multi-turn memory cases for real interaction patterns
- stronger assertions on routing, packaging, suppression, and carry-forward
  strength
- clearer separation between Pallium-native debugging and downstream end-to-end
  validation

## Why

Pallium's product boundary is the thin-agent memory-decision contract.

That means most bugs in:

- ingest correctness
- memory creation
- query routing
- packaging quality
- suppression behavior
- freshness and scope handling
- contradiction and stale-memory behavior

should be testable and debuggable directly inside Pallium.

Today the downstream agent is still doing too much work as a debugging surface
for these problems. That creates avoidable ambiguity because a live downstream
run mixes:

- Pallium behavior
- model behavior
- hook and ingest timing
- session timing
- tool/runtime effects
- downstream prompt behavior

This feature shifts the primary validation surface back where it belongs:
Pallium-native scenarios, replay fixtures, and direct query-debug inspection.

It also becomes the main safety rail while the new stabilization architecture
lands. Intent resolution, typed envelopes, constraints, and subject anchors all
need deterministic regression coverage that expresses generic failure classes
instead of one-off wording fixes.

## In Scope

- expand direct `/items`, `/query`, and `/query/debug` scenario coverage for
  memory-product behavior
- add more multi-turn authored fixtures for:
  - fresh-thread cross-thread recall
  - resumed-session continuation
  - same-thread no-value suppression
  - constraint carry-forward
  - sharp-vs-generic competition
  - stale vs fresh memory selection
  - wrong-thread and scope guards
  - noisy duplicate-question contamination
- add more direct replay-style tests that reproduce live misses without any
  downstream agent in the loop
- make returned result ids, selected layer, query family, suppression reasons,
  and injected block text/types first-class assertions where appropriate
- extend scenario helpers so they can model realistic container/thread/session
  transitions and contamination-after-query flows
- make it easy to promote a real miss into a Pallium-native regression fixture
  even before the full live replay pipeline is built
- keep test fixtures anonymized and generic rather than downstream-specific
- align new scenarios with the benchmark architecture so they can be classified
  as iteration, confidence, or replay assets over time
- add failure-class coverage for the stabilization lane, including at least:
  - intent misclassification
  - wrong-kind selection
  - wrong-subject contamination
  - constraint-compatibility failure
  - stale or superseded memory winning incorrectly

## Out of Scope

- replacing the downstream integration checks entirely
- turning this feature into a second interactive harness
- committing private downstream transcripts or provider outputs into repo
  fixtures
- broadening the test surface into generic assistant-answer scoring unrelated to
  Pallium's memory contract

## Done When

1. Most routing, packaging, suppression, and carry-forward bugs can be
   reproduced directly inside Pallium with repo-local scenarios.
2. Multi-turn Pallium-native regressions cover the key memory-product flows that
   previously required downstream-agent runs for diagnosis.
3. Scenario helpers make thread/session/container transitions and replay-style
   contamination cases straightforward to express.
4. Direct tests assert on the thin-agent contract and routing/debug trace, not
   only on broad output success.
5. New scenario assets stay anonymized and are clearly usable as iteration,
   confidence, or replay material.
6. Each stabilization feature can land with a corresponding deterministic
   regression surface rather than relying on live debugging only.

## Notes

Recommended sequencing:

1. keep benchmark architecture formalization first so lane and tier vocabulary
   is stable
2. keep this feature active in parallel with bounded intent resolution and the
   write-time envelope lane so architecture changes have immediate regression
   protection
3. use the shipped direct exploratory harness as a feeder and verifier for
   candidate replay scenarios

Implementation defaults:

- prefer extending existing API, routing, and benchmark fixtures over building a
  second scenario framework
- keep scenarios repo-local and deterministic by default
- express failure classes generically rather than encoding downstream-specific
  nouns or phrasing into fixtures
- use downstream-agent runs only as downstream proof after Pallium-native
  coverage has the issue pinned down

