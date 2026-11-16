---
id: harden-runtime-lifecycle-and-delivery-evidence
title: Harden runtime lifecycle and delivery evidence
status: queued
priority: medium
commitment: committed
milestone: pallium-relay
lane: stabilization-safety
---

## Summary

Turn the November 8–15, 2026 reading reports into a bounded compatibility and
regression follow-up. Start after the local OpenCode wake incident is resolved;
this item must not expand or block that fix. Queueing this feature does not
authorize execution, runtime upgrades or live-environment changes.

## Why

Vendor releases describe lost reports during compaction, queued input entering
running turns, interrupted-session replay, identity changes and idle reports
while descendant work continues. These are useful failure classes to check,
not proof that Pallium has the same defects. Research also supports judging
orchestration by verified outcomes and cost, not worker count or token spend.

## In Scope

- Inventory existing contracts, caller-surface tests and qualified runtime versions
  first. Reuse completed activation-capability and delivery-trace work; add only
  concrete uncovered behavior, not another registry, status model or harness.
- Keep delivery/queue admission, native execution, descendant activity, accepted
  task completion and searchable history separate. Preserve unknown and uncertain
  outcomes. Neither admission, idle, ACK nor searchable text proves task success.
  Do not turn these dimensions into one linear status enum or invent unsupported
  runtime signals.
- Extend existing E2E journeys where coverage is missing: queue versus steer while
  busy; compaction with an unanswered report; restart after submission but before
  confirmation/ACK; retained pending reports; interrupted-input resume; late
  cancellation affecting a newer turn; idle with active descendants; and eventual
  settlement without loss, duplicate admission, replay or duplicate ACK.
- Verify exact recipient/session/container and available account/profile bindings
  across restart, resume, worktree changes and handoff. Missing or changed identity
  must not silently fall back to another recipient or account. Include negative,
  ambiguous, repeated-operation and Unicode cases through the caller's surface.
- Assess OpenCode 2.3 background-agent/descendant semantics against the supported
  plugin API. Keep pinned 2.2.7 evidence distinct from any later qualification.
  Assess Codex Cloud receipts separately from local Desktop support; retain stable
  submission identity and uncertainty without blind retry.
- Perform a separate version/applicability review of Claude Code's OAuth redirect,
  account-bound background-session and permission fixes. Use release/security
  evidence, not real credentials or live fault injection. Record affected, fixed
  or unknown status and propose any necessary maintenance through normal approval.
- Use existing task evidence to assess verified requirements, integrated outcomes,
  elapsed time, human interventions and cost. Separate orchestration quality from
  implementation results; do not build a new metrics system or rank productivity
  by tokens, messages or commits alone.

## Out of Scope

- Reimplementing [OC-1 recovery](fix-opencode-plugin-reliability.md), completed
  [activation capabilities](add-relay-activation-capability-contract.md) or
  [delivery traces](add-relay-delivery-trace.md). Reconcile any overlap with
  [lifecycle hardening](add-relay-retention-and-lifecycle-hardening.md).
- Spawning or supervising agents, expanding the team topology, a scheduler,
  general task-completion inference, or a new persistent proof ledger.
- Automatic upgrades, credential/account changes, service restarts, live repair,
  or claiming a local Desktop cold-wake API from Cloud implementation details.

## Done When

- Each follow-up above maps to existing verified coverage, a tested bounded fix,
  or an explicit supported-API/security blocker in the owning implementation
  record. No vendor release note alone is recorded as a Pallium regression.
- New behavior has caller-surface E2E coverage of its boundaries, errors, races,
  identity/scope isolation and full lifecycle. Existing protected contracts and
  no-replay/uncertainty guarantees remain intact.
- Runtime/platform qualification and remaining unknowns are documented separately
  from source changes, merge and installed delivery. OpenCode 2.3 qualification,
  if pursued, does not inherit the 2.2.7 result.

## Notes

Sources checked on 2026-11-15:

- [WorkflowArena](https://arxiv.org/abs/2611.12856): orchestration matters, but model
  and harness effects limit conclusions about this particular team topology.
- [The AI Era's Lines of Code?](https://arxiv.org/abs/2611.13396): observational
  token-spend study; resource consumption is not an outcome-value measure.
- [Claude Code 2.1.321](https://github.com/anthropics/claude-code/releases/tag/v2.1.321)
  and [2.1.323](https://github.com/anthropics/claude-code/releases/tag/v2.1.323):
  compaction, queued-input, restart, identity and security fixes. Applicability to
  installed versions remains unassessed; no credential incident is established.
- [OpenCode 2.3.0](https://github.com/anomalyco/opencode/releases/tag/v2.3.0):
  background subagents, descendant-aware idle reports and restart behavior.
- [Codex CLI 0.169.0](https://github.com/openai/codex/releases/tag/rust-v0.169.0)
  and [Cloud receipt PR #59746](https://github.com/openai/codex/pull/59746):
  searchable history, handoff recovery and typed Cloud admission receipts.
