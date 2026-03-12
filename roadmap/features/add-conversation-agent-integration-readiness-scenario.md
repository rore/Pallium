---
id: add-conversation-agent-integration-readiness-scenario
title: Add a conversation-agent integration readiness scenario
status: queued
priority: high
commitment: committed
milestone: Next
---

## Summary

Define one canonical value-testing scenario, plus small control cases, that can be run entirely inside Pallium's existing test bed and evaluation harness without a live downstream runtime. Treat this scenario as the first integration-readiness milestone: when Pallium can show clear resumed-work improvement here and fail closed on mixed-scope memory, it is ready for a thin local downstream integration.

## Why

The project now understands the likely downstream usage shape well enough to begin preparing for integration, but wiring to a live runtime too early risks validating plumbing before value.

Pallium needs a concrete milestone that answers a narrower question first:

Can it preserve enough learned state from a realistic, tool-mediated developer workflow that a later continuation is materially better even without a live downstream agent in the loop, while also avoiding unsafe public/private memory mixing?

If that answer is not yes inside the repo's own realistic scenario harness, live integration will mostly prove transport and adapter behavior rather than product value.

## In Scope

- define one canonical integration-readiness scenario for `agent_conversation_memory`
- keep the scenario generic and open-source friendly rather than naming one internal downstream runtime
- model a realistic developer-work continuation case with:
  - an initial task-oriented request
  - selected intermediate learned state from the agent's work
  - at least one blocker, failed attempt, or missing-auth/tool event
  - a later continuation turn that should benefit from preserved orientation
- require the scenario to compare:
  - baseline behavior using the current lower-level retrieval and current-thread context only
  - memory-enabled behavior using the intended continuity slice
- define a small no-value or low-value control case where Pallium should add little because current context is already sufficient
- define at least one scope guard case where public and private memory are both present and Pallium must fail closed rather than leak or blend them
- make the scenario explicitly usable as the gate for saying Pallium is ready for a thin local downstream integration

## Out of Scope

- wiring to a live downstream runtime
- proving transport, webhook, or local daemon behavior
- broad benchmark coverage for every downstream use case
- replacing the broader work-resumption benchmark slice
- requiring private downstream traffic or internal production traces
- treating descriptive refs alone as a privacy model without explicit scope enforcement

## Done When

1. The roadmap and repo define one canonical continuation scenario that can be run without a live downstream agent.
2. The scenario includes:
   - a positive-value work-resumption case
   - a no-value or low-value control case
   - a mixed-scope guard case
3. The positive-value case only passes when Pallium can carry forward:
   - current task orientation
   - key findings so far
   - blocker or failed-attempt state
   - next-step guidance
   - evidence and freshness
4. The mixed-scope guard case only passes when Pallium fails closed and does not mix or leak memory across incompatible scopes.
5. The milestone is explicit that passing this scenario means Pallium is ready for thin local integration testing, while failing it means the missing value slice is still inside Pallium rather than in adapter work.

## Notes

Suggested canonical positive-value scenario:

1. A developer asks the conversation agent to find what the team is working on in a topic area.
2. The agent gathers some context, finds partial evidence, then hits a tool or auth blocker.
3. A later continuation asks the agent to resume or continue the same work.
4. Without Pallium, the continuation should tend to restart the investigation or lose orientation.
5. With Pallium, the continuation should immediately recover:
   - what the task is
   - what was already learned
   - what failed
   - what should be tried next

Suggested control case:

1. A same-thread continuation where the immediate context already contains the needed state.
2. Pallium should add little or nothing beyond current-thread context.

Suggested scope guard case:

1. A public-memory thread and a private-memory thread both touch a similar topic.
2. A continuation in one scope must not retrieve or blend memory from the other scope unless an explicit later shared-memory path exists.

This milestone is intentionally narrower than the full work-resumption benchmark. Its purpose is to define the first point where the project can responsibly say "value is ready to test in a live downstream integration" rather than only "the adapter could be wired."
