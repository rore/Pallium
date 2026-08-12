---
id: idea-cross-context-work-continuity
title: Work continuity across sessions and agents
status: queued
priority: medium
commitment: uncommitted
milestone: pallium-vnext-p2
---

## Summary

Make continuing work from another context easy enough to reduce the manual
"summarize this so I can give it to the other session" / "go read that transcript"
ritual, while preserving correct understanding of the prior work. Covers
same-agent new session, parallel sessions, and Claude↔Codex handoff.

## Why

Cross-session transfer is common in the corpus but orchestrated manually today.
Two concrete gaps: (1) each new session mints a fresh `thread_ref`, so the
`resumed_session` fast-path doesn't fire for genuinely new sessions — cross-session
continuity leans entirely on container-scoped retrieval + work_ref affinity; and
(2) cross-agent continuity is only an emergent side effect of shared
`container_ref`/`actor_ref` — `agent_ref` is stored but is not a routing/handoff
dimension and there is no explicit handoff packaging.

## In Scope (outline — detail after Experiment 1)

Test the simplest form first, and only invest in mechanism if it beats the manual
baseline:

- **First (validate the value):** a source session is *identified* by the user or
  agent (no automatic session-identity solving); Pallium retrieves and packages that
  session's relevant work; the receiving session continues from it. Measure against
  the manual baselines (paste-a-summary / read-the-transcript) on user-orchestration
  cost and correctness of understanding.
- **Only if that wins (invest in mechanism):** stable work/session correlation
  across `session_id`s so resumption ranking spans sessions automatically; make
  `agent_ref` a first-class handoff dimension (Claude↔Codex); richer explicit
  continuation packaging.
- build on shipped `work_refs`, `task_checkpoint`, `resumed_session`

## Out of Scope

- cross-*user* sharing (Phase 4 — visibility-bounded)
- assuming cross-agent frequency; instrument before investing heavily there
- proactive injection beyond high-confidence resumption

## Done When

1. A new session in the same work continues with prior progress/blockers/next-step
   without the user re-explaining.
2. Pallium-supported continuation beats the manual baselines (summary / pointer /
   raw transcript) on user-orchestration cost while preserving correct
   understanding.

## Notes

Gate: Experiment 2. Depends on Phase 1 (lookup/expand); independent of the
continuous derived eval. Sequence within the item: prove the value of
identified-source handoff before building automatic session correlation or
`agent_ref` routing — don't start by solving session identity.
Execution context: `docs/designs/015-vnext-historical-work-execution.md` (Phase 2).
Related shipped work: `add-work-ref-cross-surface-continuity`, design 013.
