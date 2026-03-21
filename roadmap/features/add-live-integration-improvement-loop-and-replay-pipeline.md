---
id: add-live-integration-improvement-loop-and-replay-pipeline
title: Live miss capture and replay promotion loop
status: done
priority: high
commitment: committed
milestone: Later
lane: integration-feedback
---

## Scope Trim (applied before implementation)

The following items from the original In Scope list are **deferred** to a future slice:

- **Automatic suspicious-case detectors** — Pallium already produces `sharp_candidate_diagnostics`
  and full routing trace at query time. Cases detectable post-hoc with a heuristic should become
  hot-path routing fixes, not review-inbox entries. Building a detector layer on top of data that
  the system already has at decision time adds process where code fixes are needed. Deferred until
  the hot path is stable enough that residual misses are genuinely ambiguous.

- **Bounded review-inbox export** — Follows from the above. Without confirmed suspicious-case
  detectors there is no well-defined inbox to populate. Deferred with the detectors.

What remains in this slice: drift metrics aggregation, shadow comparison via injectable routing
overrides, and replay promotion workflow (scenario generation for the existing benchmark runner).
Benchmark-tier `DatasetTier.REPLAY` accounting is deferred to a follow-on chunk.

## Summary

Add a productized live-improvement loop for Pallium so real integration traffic
can be turned into privacy-safe miss bundles, reviewed efficiently, and
promoted into the benchmark program instead of remaining anecdotal debugging.

The goal is to make Pallium continuously improvable once real integration
traffic exists and the core stabilization architecture is trustworthy enough to
capture misses in a durable, reviewable form.

- promote confirmed misses into replay fixtures owned by the benchmark program
- support safe shadow comparison of candidate tuning changes on captured bundles
- surface aggregate drift signals across runs

This feature should make Pallium learn from real integration failures without
moving semantic policy into the downstream agent and without duplicating the
benchmark program's ownership of fixture format, replay execution, or scoring.

## Why

Real integration traffic will expose failures that current prompts, heuristics,
and routing rules do not handle perfectly.

Without an explicit improvement loop, those failures become:

- isolated anecdotes in logs
- one-off prompt changes with weak verification
- repeated regressions because real misses were never preserved as tests

Pallium already has parts of the foundation.

- processing and query debug observability
- retention-safe hot-store behavior
- authored benchmark suites and public-corpus packs
- a growing agent memory-decision benchmark direction

What is still missing is the operational loop that connects those pieces.

- reviewable promotion into replay fixtures
- shadow comparison on captured bundles before rollout
- drift metrics to surface aggregate quality signals

That loop is what turns live integration from ad hoc debugging into systematic
product tuning.

It is no longer the immediate next stability move, however. Pallium first needs
a more stable deterministic hot path for scope, kind, subject, and constraint
handling, with selective semantic escalation only where ambiguity remains, so
captured misses do not mostly reflect known structural weaknesses.

## In Scope

- reuse the benchmark program's existing failure taxonomy and replay-fixture
  vocabulary rather than inventing a second parallel one in production tooling
- add one replay-promotion tool or workflow that turns a live runner scenario
  result into a benchmark-ready scenario skeleton
- replay-promotion skeletons should include at least:
  - prior events (reconstructed from ingested item payloads)
  - current query (text, limit, container_ref, visibility_context)
  - expected injection decision (human-confirmed sentinel by default)
  - expected memory types placeholder
- add operational drift metrics that can be inspected over time
- operational drift metrics should include at least:
  - injection rate
  - sharp miss rate and breakdown by loss stage
  - fallback rate
  - rebuild rate
  - generic-summary win rate vs sharp-memory win rate
- add one simple shadow-comparison path for candidate tuning changes so Pallium
  can compare current vs proposed memory decisions on captured bundles before a
  rollout
- shadow-comparison diffs should include at least:
  - `should_inject`
  - `decision_reason`
  - selected layer
  - fallback applied flag
- expose routing tuning constants as injectable overrides (`RoutingOverrides`)
  so shadow passes can exercise different weights and margins without modifying
  source code; override injection must stay within the semantic layer and the
  harness — not the public API
- keep the improvement loop package-owned where semantics are package-specific;
  generic layers may provide bounded storage/export helpers, but should not own
  `agent_conversation_memory` policy judgments

## Out of Scope

- full production incident-management tooling
- committing private downstream traffic or raw unsanitized captures into the
  repo
- building a broad analytics platform unrelated to Pallium memory quality
- replacing authored benchmark suites with only live replay fixtures
- turning the downstream agent into the miss classifier or semantic triage layer
- online auto-learning or fully automatic prompt rewriting
- owning the benchmark program's replay runner, fixture schema, or scoring
  contract inside this feature

## Done When

1. Engineers can promote a live runner scenario result into a replay scenario
   without manually reconstructing the conversation from logs.
2. The promotion flow targets the benchmark program's existing replay schema and
   failure vocabulary instead of introducing a second fixture format.
3. Changes to routing weights and margins can be shadow-compared on captured
   scenario results before rollout, staying entirely within the harness layer.
4. Drift metrics make it obvious when Pallium is over-promoting low-value
   content, rebuilding too often, over-injecting memory, or over-relying on
   fallback paths.

## Notes

Recommended sequencing:

1. land the write-time memory envelope so the hot path can narrow by kind before
   ranking
2. land first-class constraints and subject/workstream filtering so the main
   current bug classes are captured in typed deterministic form
3. land the bounded query-policy contract and selective semantic ambiguity
   resolution so any model-backed query step is truly selective
4. keep Pallium-native scenario and replay coverage active so failure families
   and replay assets are already stable
5. then add this live-improvement loop so captured misses feed a trustworthy
   replay and shadow-comparison workflow instead of automating unstable
   heuristics

Implementation defaults:

- prefer JSON bundle capture plus explicit promotion manifests over hidden
  SQLite state or manual notebook workflows
- keep capture/export bounded and scope-aware by default
- every promoted scenario should be immediately runnable by the existing
  benchmark runner via `--scenario-file`; `expected_value` requires human
  confirmation before the scenario is treated as a regression gate
- use current observability and debug surfaces as the data source rather than
  inventing a second tracing system first
- `RoutingOverrides` injection must stay within the semantic layer and harness;
  routing tuning knobs must not appear in the public API schema
- `WORK_RESUMPTION_SHARP_CHECKPOINT_THRESHOLD` is defined but has no active
  call site in routing; it is excluded from `RoutingOverrides` intentionally
  until it is wired to a real scoring gate

