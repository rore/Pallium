---
id: idea-cross-user-raw-history-value
title: Scoped cross-user raw-history value
status: queued
priority: medium
commitment: uncommitted
milestone: pallium-vnext-p3
---

## Summary

Test the simplest useful form of shared knowledge first: can scoped historical
work — including raw history — produced by user/agent A materially help user B,
within visibility bounds, in a real multi-user deployment? Validate that value
before building any shared-derived-memory publication machinery.

## Why

The prior Phase-4 plan led with `add-explicit-shared-memory-derivation` and bounded
cross-container derived memory — a mechanism inherited from the older
derived-memory-first architecture. The vNext strategy no longer justifies starting
there. If raw historical lookup is the validated substrate (Phase 1) and derivation
is only a continuously-evaluated layer, then the first shared-knowledge question is a
*value* question: does one user's prior work help another at all? Answer that with
raw history before investing in shared-derived objects.

**But raw history plus current enforcement is not, by itself, a safe cross-user
contract.** Today `core/visibility.py` has no per-user grant: a public candidate
requires `actor_ref is None` (raw source items keep their producer actor, so they
can't ride the public path); a private/unspecified query sees *everything in the
same container regardless of actor* (container-wide, not consented per user); and
`core/filters.py` actor filters exclude another user's raw sources. So this
experiment is gated on an explicit raw-history sharing/authorization contract — a
security mechanism, not a substrate already in hand.

## In Scope (outline — detail only after a real multi-user environment exists)

- **prerequisite:** an explicit raw-history sharing/grant contract (built via the
  reconciled authorization semantics — see `idea-visibility-vocab-reconciliation`)
  covering consent, target audience, revocation, provenance, access audit, and
  fail-closed behavior. This does **not** require a derived shared object, but it
  does require a real sharing mechanism.
- a scoped cross-user lookup: user B searches, and raw history from user A that has
  been *granted* to B (not merely co-located in a container) is eligible
- measure whether cross-user results are materially used by B (post-hoc judge, same
  method as the P0 measurement contract — not an online matcher)
- hard invariant: visibility violations = 0, reported with counts/types of attempted
  disallowed cross-user accesses (fail-closed, enforce-before-ranking)

## Out of Scope

- shared-derived-memory publication (`add-explicit-shared-memory-derivation`) —
  only build it if this experiment or the continuous derived eval shows raw
  cross-user sharing is insufficient
- bounded cross-container derived memory (`add-cross-container-bounded-memory`)
- relying on current container-wide visibility as a stand-in for per-user consent
- assuming cross-user frequency; instrument before investing
- any global/ambient sharing

## Done When

1. An explicit raw-history sharing/grant + revocation contract exists (consent,
   audience, provenance, access audit, fail-closed) on top of reconciled
   authorization semantics.
2. In a real multi-user deployment, user B can receive *granted* prior raw work from
   user A via lookup, with 0 visibility violations (reported with attempted-access
   counts/types).
3. We have a measured answer to "does scoped cross-user history materially help?"
   before committing to shared-derivation mechanism work.

## Notes

Gate: Experiment 4 (requires a genuine multi-user environment — validation-blocked
by design until then). Depends on Phase 1 lookup + the authorization reconciliation
and raw-sharing contract (`idea-visibility-vocab-reconciliation`). This item
precedes, and may obviate, `add-explicit-shared-memory-derivation`.
Execution context: `docs/designs/015-vnext-historical-work-execution.md` (Phase 3).
