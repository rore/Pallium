---
id: add-live-integration-improvement-loop-and-replay-pipeline
title: Live miss capture and replay promotion loop
status: queued
priority: high
commitment: committed
milestone: Next
lane: integration-feedback
---

## Summary

Add a productized live-improvement loop for Pallium so real integration traffic
can be turned into privacy-safe miss bundles, reviewed efficiently, and
promoted into the benchmark program instead of remaining anecdotal debugging.

The goal is to make Pallium continuously improvable once real integration
traffic exists and the core stabilization architecture is trustworthy enough to
capture misses in a durable, reviewable form.

- detect suspicious behavior automatically
- capture the right bounded trace when a miss happens
- route that miss into a review inbox
- promote confirmed misses into replay fixtures owned by the benchmark program
- support safe shadow comparison of candidate tuning changes on captured bundles

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

- automatic suspicious-case detection
- triageable miss bundles
- reviewable promotion into replay fixtures
- shadow comparison on captured bundles before rollout

That loop is what turns live integration from ad hoc debugging into systematic
product tuning.

It is no longer the immediate next stability move, however. Pallium first needs
a more stable deterministic hot path for scope, kind, subject, and constraint
handling, with selective semantic escalation only where ambiguity remains, so
captured misses do not mostly reflect known structural weaknesses.

## In Scope

- reuse the benchmark program's existing failure taxonomy and replay-fixture
  vocabulary rather than inventing a second parallel one in production tooling
- add automatic suspicious-case detectors over live/debug traces
- suspicious-case detectors should cover at least:
  - generic summary selected while sharper active memory exists in scope
  - same-thread continuation with sufficient local context still injecting
  - low-value items creating durable memory
  - low-value-only items scheduling thread rebuilds
  - fresher same-kind conclusions losing to older ones
  - suspiciously high rebuild or supersession churn in a thread
  - `should_inject=true` with weak or fallback-only blocks
  - unexpectedly high semantic-escalation rate on queries that should stay on
    the deterministic hot path
- add a bounded review-inbox export for suspicious cases
- review-inbox exports should capture at least:
  - relevant source items
  - relevant active memory objects
  - query input and runtime context
  - retrieval, routing, and injection trace
  - final returned results and injected blocks
- keep review-inbox export privacy-safe and bounded
- privacy and scope rules for export should include:
  - no raw giant transcript dumps
  - no unrelated rows from outside the current scope
  - support scrubbing and generalization into committed fixtures
- add one replay-promotion tool or workflow that turns a captured miss bundle
  into a benchmark-ready scenario skeleton
- replay-promotion skeletons should include at least:
  - prior events
  - current thread context
  - runtime context
  - expected injection decision
  - expected decision reason
  - expected winning memory kind or injected block
  - forbidden outcomes
  - failure-family label
- add operational drift metrics that can be inspected over time
- operational drift metrics should include at least:
  - durable memories created per source item
  - rebuilds per thread
  - superseded summaries per thread
  - low-value promotion rate
  - injection rate by runtime turn kind
  - average injected block count
  - generic-summary wins vs sharp-memory wins
  - failure-family counts over time
  - semantic-escalation rate over time
- add one simple shadow-comparison path for candidate tuning changes so Pallium
  can compare current vs proposed memory decisions on captured bundles before a
  rollout
- shadow-comparison diffs should include at least:
  - `should_inject`
  - `decision_reason`
  - injected block ids or types
  - whether semantic escalation occurred
- keep the improvement loop package-owned where semantics are package-specific;
  generic layers may provide bounded storage/export helpers and review-inbox
  plumbing, but should not own `agent_conversation_memory` policy judgments

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

1. Pallium can automatically flag suspicious live cases instead of relying only
   on humans reading logs.
2. Suspicious cases can be exported as bounded, privacy-safe miss bundles with
   the data needed to reproduce the issue.
3. Engineers can promote a miss bundle into a replay scenario without manually
   reconstructing the entire conversation from logs.
4. The promotion flow targets the benchmark program's existing replay schema and
   failure vocabulary instead of introducing a second fixture format.
5. Changes to prompts, heuristics, routing, or packaging can be shadow-compared
   on captured bundles before rollout.
6. Drift metrics make it obvious when Pallium is over-promoting low-value
   content, rebuilding too often, over-injecting memory, or over-using semantic
   escalation.
7. The improvement loop reinforces a thin-agent boundary by detecting when the
   downstream agent would otherwise need to compensate semantically.

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
- treat human review as the confirmation step after automatic suspicious-case
  detection, not as the only detection mechanism
- every confirmed live miss should be promotable into a permanent replay
  regression owned by the benchmark program
- use current observability and debug surfaces as the data source rather than
  inventing a second tracing system first
