---
id: add-first-class-constraint-policy-lane
title: First-class constraint and policy compatibility lane
status: done
priority: high
commitment: committed
milestone: Done
lane: stabilization-semantics
---

## Summary

Turn hard constraints and operational prohibitions into a dedicated typed memory
lane with explicit compatibility checks, instead of treating them as generic
sentences inside summaries and checkpoints.

This feature was shipped and then its scope was corrected by the constraint
boundary decision (2026-03-22). The constraint_policy routing lane and
compatibility engine were removed (~1000 lines). Pallium now remembers and
returns constraints; enforcement is the consuming agent's job.

## Outcome

The constraint_policy lane was built, shipped, and then removed as part of the
cue-free control plane work. The boundary correction concluded that:

- Pallium is a memory sidecar — it stores and returns constraints, it does not
  enforce them
- Constraint compatibility evaluation belongs in the consuming agent, not in the
  recall layer
- The constraint compatibility engine added complexity (~1000 lines) without
  matching the product boundary
- Constraint memories now route through `residual_recall` alongside other memory
  types

The typed constraint extraction at write time (constraint_candidates with
action_class, polarity, target_anchor) remains in the extraction schema for
consuming agents to use. What was removed is query-time constraint compatibility
evaluation and the dedicated `constraint_policy` routing lane.

## Why (original)

This was originally the highest-pain stability gap.

The existing heuristic path kept creating variants of the same bug class:

- a hard constraint was remembered textually but not enforced semantically
- contradictory next steps survived because the conflict check was token-based
- newer lower-quality structured memory could still poison later recall

The boundary correction recognized that enforcement was being placed in the wrong
layer. The consuming agent has the execution context to evaluate constraint
compatibility; Pallium's job is to surface the constraint reliably.

## Done When (revised)

1. ~~Hard constraints are represented as a dedicated typed lane rather than only
   free-text memory content.~~ Typed constraint fields exist in extraction output.
2. ~~Query-time packaging excludes or demotes incompatible state using typed
   compatibility checks.~~ Removed — enforcement is the consumer's job.
3. ~~Write-time reconciliation prevents active structured memory from preserving
   both the hard constraint and contradictory next-step guidance.~~ Removed.
4. Constraint recall queries surface constraint memories through normal retrieval
   and residual_recall routing.
5. ~~Debug trace can explain which constraint was active and why a candidate was
   deemed compatible or incompatible.~~ Removed — no compatibility engine.
6. Constraint extraction stays generic and typed at write time.
7. Ordinary queries stay on the deterministic hot path.

## Notes

The original implementation defaults and sequencing notes are now historical.
The constraint boundary correction decision is recorded in
`docs/context/decisions.md` (2026-03-22).

