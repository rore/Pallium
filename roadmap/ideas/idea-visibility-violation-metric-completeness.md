---
id: idea-visibility-violation-metric-completeness
title: "Zero visibility violations" metric must cover same-container privacy breaches
status: queued
priority: medium
commitment: uncommitted
---

## Summary

The visibility-violation rollup mainly recognizes cross-container exposure and forgotten-source
exposure. It does not fully represent private-under-public exposure, actor-A-private-to-actor-B,
expansion authorization mismatches, or source-visibility differing from query-visibility. So the
dashboard could report **zero violations while a same-container privacy breach occurred** — exactly the
class `fix-source-expansion-visibility-enforcement` addresses. A hard vNext invariant (visibility
violations = 0) is only trustworthy if the metric can see all violation classes.

## Why

The Phase-0 invariant (scope.md: "visibility violations = 0, reported with attempted-disallowed-access
counts/types") is undermined if the detector's categories are incomplete. Same-container private leaks
via expansion are currently invisible to it.

## In Scope

- Persist sufficient query context on every exposure event: query actor, query visibility, active
  container, source owner, source visibility, authorization decision + policy version, and exposure
  surface (search / injection / expansion).
- Compute the violation metric with the **same authorization policy as retrieval**, ideally via a shared
  pure decision function, so metric and enforcement cannot drift.

## Out of Scope

- The enforcement fix itself (`fix-source-expansion-visibility-enforcement`) — this ticket is the
  measurement half; they should land together.

## Done When

1. Violation-detection matrix increments the correct category for: wrong container, forgotten source, private-under-public query, actor-A-private-to-actor-B, unauthorized expansion neighbor, revoked shared access.
2. False-positive protection: authorized cases (owner→own private, public→public, authorized shared, admin) are never flagged.
3. Dashboard integrity: total = sum of non-overlapping categories (or overlaps documented); unclassifiable events reported as unknown, not safe; missing query-actor/visibility raises a data-quality warning; the metric cannot show a confident zero when required attribution fields are absent.

## Notes

External-review register item 9 (Medium, safety). Pairs with
`fix-source-expansion-visibility-enforcement` and `fix-lookup-and-expansion-active-attribution` (needs
the attribution fields). Related: `add-raw-history-governance`.
