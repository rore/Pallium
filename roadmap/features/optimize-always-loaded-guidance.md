---
id: optimize-always-loaded-guidance
title: Optimize always-loaded agent guidance
status: active
priority: high
commitment: committed
milestone: integration-quality
lane: agent-integration
---

## Summary

Reduce Pallium's generated always-loaded agent guidance without losing the triggers
and safeguards agents need to discover and safely use Relay, Session History,
optional derived memory, and optional work associations. Reuse the existing
`pallium-memory` skill and references for procedures that do not belong in every
task's context.

## Why

The current guidance grew through valid corrective slices, but repeated procedures
now compete with the user's context budget. Moving text blindly is unsafe: identity,
scope, privacy, hook-delivery ownership, stale-delivery handling, and search-choice
rules prevent concrete failures and cannot depend on an unreliable on-demand load.
The change therefore needs a measured directive-by-directive split and behavior
evidence, not an arbitrary token target.

## In Scope

- generated global/project Pallium blocks for Codex, Claude Code, and OpenCode
- existing `pallium-memory` skills, references, tool descriptions, hooks, and
  installer/update paths only where they own duplicated guidance
- a compact inventory mapping every essential directive from current location to
  retained location and agent discovery path
- deterministic before/after size measurement using the same identified method
- bounded fresh-context behavior checks over mocked or read-only surfaces
- focused generator, install, and update regression coverage

## Out of Scope

- Relay delivery reliability files owned by relaydev
- service, API, storage, retrieval, ranking, or memory behavior changes
- new instruction registries, loaders, evaluation frameworks, or arbitrary targets
- install/restart operations, private-history replay, or private-memory writes
- changing unrelated user cost, style, or session settings outside managed blocks

## Done When

1. A clean-context architecture review approves the exact always-loaded/on-demand
   split, file scope, risks, and behavior oracles before implementation.
2. The same deterministic measurement shows a smaller always-loaded payload for
   every changed runtime without hiding critical safeguards behind skill loading.
3. Nine paired baseline/proposed fresh-context scenarios (18 bounded runs) use
   the same cheapest-capable model, prompt, safe stubs, normally exposed skill
   catalog, and tool metadata without preloading the full skill. Each run has a
   fixed tool-turn cap, records skill loading plus observable outcome, avoids
   duplicate existing work-ref attachment, and is reported as smoke/regression
   evidence rather than statistical proof. Deterministic generated-output
   tests, not these model runs, establish cross-runtime textual parity.
4. Fresh install, update, and generator contracts pass for Codex and Claude Code;
   OpenCode packaging/registration coverage passes; independent result review and CI
   are clean.
5. The Work Record and this roadmap item preserve measured evidence, review findings,
   and any concrete instruction or delivery friction before closure.

## Notes

This general cross-capability integration slice is distinct from
[`investigate-history-navigation-and-on-demand-compression`](investigate-history-navigation-and-on-demand-compression.md),
which owns History result navigation and representation after retrieval. It reuses
the lazy-reference precedent from
[`add-context-conscious-upstream-field-feedback`](add-context-conscious-upstream-field-feedback.md)
and the behavior rationale from
[`add-agent-historical-lookup-exposure`](add-agent-historical-lookup-exposure.md).
