---
id: idea-visibility-violation-metric-completeness
title: Visibility-policy-filtering metric must cover same-container leaks (enforceable filtering, not authenticated privacy)
status: queued
priority: low
commitment: uncommitted
---

> **Scope correction 2026-08-18.** Pallium is trusted-local with NO authentication layer, so this metric
> must claim **enforceable policy filtering** (cross-container, forgotten-source, public-vs-private-scope
> filtering — the classes `fix-source-expansion-visibility-enforcement` actually enforces), NOT
> *authenticated privacy* between actors. Drop "actor-A-private-to-actor-B" as a violation class: without
> authenticated identity there is no boundary to violate, and the current read model intentionally shows
> a container's own turns. Priority lowered to low — the real enforcement (expansion visibility) already
> shipped in #39; this is metric-coverage hygiene, not a safety gap.

## Summary

The visibility-policy-filtering rollup mainly recognizes cross-container exposure and forgotten-source
exposure. It does not fully represent private-under-public exposure or source-visibility differing from
query-visibility. So the dashboard could report **zero filtering failures while a same-container
public-vs-private leak occurred** — exactly the class `fix-source-expansion-visibility-enforcement`
addresses. The invariant is only trustworthy if the metric sees all *enforceable* filtering classes.

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
