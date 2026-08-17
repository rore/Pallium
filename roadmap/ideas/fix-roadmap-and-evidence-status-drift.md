---
id: fix-roadmap-and-evidence-status-drift
title: Roadmap and evidence status drift
status: queued
priority: low
commitment: uncommitted
---

## Summary

Delivery-clarity cleanup surfaced by the external review. P1 "Reuse Measurement" reads as empty even
though unresolved P1-critical work sits in Ideas; some schema commentary says expansion is not persisted
as a lookup-related event while implementation now persists expansion telemetry; the continuity report
duplicates a caveat section; lifecycle/shared-memory terminology is inconsistent between roadmap scope
and board placement. None break execution, but together they can make the org treat P1 as finished
prematurely.

## Why

"Implemented", "experimentally promising", and "validated" are being conflated. Honest status is a
precondition for the reviewer's core ask: prove Pallium retrieves selectively enough to be net-positive.

## In Scope

- Populate P1 "Reuse Measurement" with the reopened measurement/validation tickets; keep P2/P3 explicitly gated on their outcomes.
- Reconcile public API/schema commentary with persisted behavior (expansion telemetry).
- De-duplicate the continuity report caveat; align lifecycle/shared-memory terminology.
- Establish three distinct statuses: Implemented / Experimentally promising / Validated.

## Out of Scope

- The code fixes themselves (their own tickets).

## Done When

1. Every shipped claim links to the measurement or test that supports it.
2. Every eval states whether it measures candidate recovery, injection precision, or downstream effect.
3. Roadmap status agrees with implementation and evidence status; public API/schema commentary matches persisted behavior.
4. A docs check or review test catches stale field/event-model descriptions.

## Notes

External-review register item 14 (Low–Medium). Related: `idea-measurement-contract-honesty`.
