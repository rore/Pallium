---
id: fix-relay-claim-before-context-emission
title: Prevent claimed Relay messages disappearing during hook timeouts
status: active
priority: high
commitment: committed
milestone: pallium-relay
lane: defect
---

## Summary

Fix the natural-turn integrations so a Relay delivery cannot be claimed, hidden
behind its lease, and then omitted from the model context when later memory work or
the hook process fails. This is a blocking correctness fix before wake-first Relay.

## Observed Failure

In a live cross-runtime review exchange, two replies were claimed by the Codex
session in one `/relay/turn` call. The user started two natural turns, but neither
message appeared and neither claim was acknowledged. Both were recoverable only
after the 60-second claim lease expired.

The Claude Code and Codex hooks currently claim Relay before calling the slower
`/item-and-query` memory path, then emit combined context and acknowledge Relay at
the end. An 8-second hook timeout or process failure in that interval produces the
observed invisible-lease window. OpenCode has a related claim-to-model-transform
window whose restart/failure behavior must also be verified.

## Contract

Explicit Relay delivery must not depend on memory retrieval succeeding or
finishing within the hook deadline. After a natural-turn attempt, every selected
delivery must be either visibly attached and acknowledged exactly once, or remain
immediately eligible for a later claim. It must not become temporarily invisible
because unrelated enrichment failed.

Fix the shared ordering/lifecycle boundary rather than increasing timeouts. Keep
Relay attribution, complete-message rendering, character budgets, scope isolation,
and existing claim-token authorization intact.

## In Scope

- Claude Code and Codex claim, render, emission, memory retrieval, and ack ordering
- the analogous OpenCode claim-to-model-transform and restart window
- safe handling of emission failure, acknowledgement failure, timeout, and process
  interruption without silent loss or duplicate visible delivery
- local integration installers if deployed hook files or configuration change
- operational evidence that distinguishes pending, claimed, delivered, and lease
  recovery during this failure class

## Out of Scope

- wake-first delivery or runtime activation adapters
- changing the claim lease merely to hide the race
- weakening acknowledgement to mean transport acceptance
- coupling Relay success to memory-query success

## Required E2E

Drive the same hook/plugin and HTTP surfaces used by callers and verify state
through Relay status or storage-backed public reads. Cover:

- delayed, failed, and timed-out `/item-and-query` after Relay is available
- interruption at each claim-to-emission and emission-to-ack boundary
- one and multiple deliveries near the rendering budget
- acknowledgement failure followed by exactly-once visible recovery
- Unicode payloads and malformed/non-renderable delivery handling
- expired delivery, lease expiry, and an immediate following natural turn
- Claude Code, Codex, and OpenCode lifecycle behavior

## Done When

1. The live reproduction no longer produces an invisible claimed delivery.
2. Relay remains visible and exactly-once when memory retrieval is slow or fails.
3. Every supported integration passes the failure-boundary E2E matrix through its
   real caller surface.
4. Updated local integrations are installed and a cross-session smoke test passes.
5. A clean-context review finds no remaining loss, duplication, or authorization
   gap, and the roadmap item records the verified result.

## Notes

Keep this fix in its own agent-workflow task and PR. Do not mix it into the
feasibility-only wake Phase 0 PR.