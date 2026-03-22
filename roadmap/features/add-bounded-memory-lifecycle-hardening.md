---
id: add-bounded-memory-lifecycle-hardening
title: Add bounded memory lifecycle hardening
status: queued
priority: high
commitment: committed
milestone: Later
lane: stabilization-safety
---

## Summary

Add the next bounded lifecycle layer for promoted memory so Pallium can handle
stale, superseded, and contradicted structured memory without relying on
append-only accumulation or opaque global reconciliation.

This feature should build on the shipped active-vs-superseded baseline and make
lifecycle trustworthy enough for the current product slice before broader
shared-memory reuse expands.

## Why

Pallium already has strong structure, scoped memory, selective promotion, and
evidence linkage. The biggest remaining trust gap is not "can we store the
memory?" but "can we tell whether it is still current?"

Without a stronger bounded lifecycle layer:

- stale conclusions can continue to surface as if they were current
- contradictions remain visible too late in retrieval and packaging
- resumed work can restart from outdated checkpoints or findings
- later shared-memory and cross-container reuse would amplify stale or false
  memory beyond the local scope where it was first created

The near-term goal is not a universal truth-maintenance system. It is a smaller
and more defensible step: make current-memory trust, supersession, and bounded
contradiction handling explicit enough that Pallium's existing continuity claims
stay reliable over time.

## In Scope

- extend the current lifecycle model beyond `active` vs `superseded` with
  bounded generic signals such as:
  - freshness or staleness influence
  - explicit supersession lineage
  - contradiction or conflict markers
  - bounded trust or confidence downgrade state
- keep lifecycle explainable and evidence-backed rather than hidden inside
  opaque ranking behavior
- make retrieval and packaging prefer current, supported memory by default when
  stale, superseded, or contradicted alternatives exist
- define at least one bounded maintenance or reconciliation path that can
  downgrade or supersede prior structured memory without deleting supporting
  evidence
- expose lifecycle influence in trace and evaluation outputs so runs can answer
  why a memory was suppressed, downgraded, or still considered current
- add deterministic replay and benchmark coverage for:
  - reversed conclusions
  - stale checkpoint or stale finding reuse
  - contradictory structured memory
  - resumed-work continuity after a later correction
- keep package-owned lifecycle policy hooks explicit on top of the generic core
  lifecycle substrate

## Out of Scope

- global contradiction resolution across all memory
- broad ontology or graph management
- opaque "confidence" scoring with no debug surface
- automatic deletion as the main lifecycle mechanism
- cross-container sharing policy or broader scope widening
- turning lifecycle into a package-specific semantic concept in `core/`

## Done When

1. Retrieval no longer surfaces stale, superseded, or contradicted structured
   memory as if it were current by default.
2. Trace and evaluation outputs can explain when lifecycle state changed
   ranking, suppression, or injectability.
3. Pallium has at least one bounded path for superseding or downgrading prior
   memory while preserving lineage and supporting evidence.
4. Deterministic tests cover stale-memory, contradiction, reversed-decision,
   and resumed-work update cases as reusable failure classes.
5. Later shared-memory features can build on this lifecycle contract rather
   than redefining freshness and supersession ad hoc.

## Notes

Dependency and sequencing notes:

- this feature builds on `add-memory-lifecycle-basics`
- this feature should move ahead of `add-explicit-shared-memory-derivation` and
  `add-cross-container-bounded-memory`
- this feature should stay bounded and generic; do not reopen broad router or
  retrieval-substrate redesign inside lifecycle work

Sources: `docs/context/vision.md`,
`docs/designs/009-derived-knowledge-memory-and-lifecycle-signals.md`
