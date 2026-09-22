---
id: validate-relay-dependency-workflows
title: Publish Relay workflow examples and public positioning
status: paused
priority: medium
commitment: uncommitted
milestone: pallium-relay
lane: documentation
---

## Summary

Preserve the strongest practical Relay workflows as a source for future
outward-facing documentation, examples, and positioning. This item does not gate
Relay development and does not require a synthetic validation program.

The stable id and filename are retained because other roadmap items already link
to this scenario catalog.

## Current decision (2026-09-22)

Routine Pallium development already dogfoods targeted dependency handoffs, blocked
questions and replies, and bounded review/remediation exchanges. The core product
hypothesis is therefore no longer unknown enough to justify building artificial
fixture projects or running a separate paid-model validation campaign.

Keep this item paused until outward-facing Relay documentation or examples are
prioritized. Resume it only to turn real, supportable evidence into clear examples,
or when a specific public claim needs evidence that current dogfood does not
provide.

Concrete Relay failures still become focused anonymized regressions in the owning
reliability item. Do not wait for this documentation item before fixing them or
shipping another Relay capability.

## Evidence boundary

Existing runtime tests, delivery traces, and installed witnesses establish the
supported transport behavior. Real dogfood can illustrate how people use that
behavior. Neither source proves that Relay saves time or that cross-model review
improves quality.

Only publish claims supported by the cited evidence. If stronger value claims are
desired later, define the smallest measurement needed for that claim at that time;
do not pre-build a general workflow evaluation framework.

## Scenario catalog

### Unexpected dependency or discovery

One agent discovers a contract, compatibility fact, blocker, or completion that
changes another agent's work and sends one targeted message. The example should
show correct recipient selection, visible attribution, safe busy handling, and
next-turn fallback without routine status broadcast.

### Blocked decision round trip

A worker asks a named decision owner a bounded question, ends its turn if useful,
and later resumes from the delivery-derived reply. The example should show that
Pallium routes and wakes; it does not poll, guess the decision, or hold an LLM call
open.

### Cross-model review and correction

A builder sends an exact artifact reference and review lens to a different runtime
or model family. The reviewer returns a concrete finding, the builder corrects it,
and any second pass is another explicit Relay action. Pallium does not own or
continue the review loop.

## Work when resumed

1. Select a small number of real, non-sensitive Relay runs that already demonstrate
   the intended workflow.
2. Anonymize the task, identifiers, and payloads while preserving the behavior that
   makes the example useful.
3. Re-run only when current evidence is incomplete or the supported runtime behavior
   has materially changed.
4. Publish concise examples and guidance covering recipient selection, attribution,
   wake and fallback behavior, expiry, cost, permissions, and when not to send.
5. Separate transport correctness from workflow value and state limitations plainly.

## Out of scope

- new Relay transport, wake, reply, routing, or orchestration behavior
- synthetic fixture repositories created only to prove these workflows exist
- a new scenario runner, workflow engine, agent manager, or automated review loop
- repeating the complete runtime/platform reliability matrix
- claiming time savings or quality improvement without dedicated evidence
- routine progress broadcast, semantic recipient inference, or unbounded agent chat

## Done when

1. The selected outward-facing examples are based on current real behavior and omit
   private incident data.
2. Public guidance explains when to send, when not to send, safe busy handling,
   next-turn fallback, replies, costs, and permission boundaries.
3. Every behavioral and value claim links to appropriate evidence and states its
   limit.
4. The roadmap and public Relay documentation agree on the supported scope.
