---
id: add-reviewed-open-corpus-continuation-pack-expansion
title: Expand reviewed open-corpus continuation packs
status: done
priority: high
commitment: committed
milestone: Done
---

## Summary

Expand the reviewed WildChat and WildBench continuation packs so Pallium is tuned against a broader set of realistic resumed-work, paraphrase, no-value, stale-memory, and wrong-memory cases without losing deterministic regression behavior.

## Why

The current public-corpus layer is now useful for tuning, but it is still small enough that benchmark wording and reviewed-case selection can dominate the signal. Pallium needs a larger reviewed continuation pack to become trustworthy for real interaction hardening.

A bigger deterministic pack will not replace real downstream validation, but it will make routing, packaging, and recall failures much easier to distinguish before live integration.

## In Scope

- expand reviewed WildChat continuation and paraphrase cases
- expand the reviewed WildBench developer continuation pack
- add more cases for:
  - resumed-work paraphrases
  - blocker and next-step follow-ups
  - exact evidence follow-ups
  - no-value same-thread continuations
  - stale-memory guards
  - wrong-memory guards
  - privacy-sensitive topic collisions when appropriate fixtures exist
- keep the canonical packs reviewed and deterministic
- keep the shared continuity failure taxonomy aligned with the authored suites
- use exploratory mining only to generate candidates, not canonical benchmark randomness

## Out of Scope

- committing large raw public datasets into the repo
- replacing the authored developer-work continuity suite
- turning the corpus tooling into a generic data platform
- randomizing the canonical benchmark on every run
- claiming public-corpus realism is a substitute for real downstream integration

## Done When

1. The reviewed WildChat and WildBench continuation packs are materially larger than the current small seed sets.
2. The expanded packs cover resumed-work paraphrases, stronger no-value cases, and at least one stale or wrong-memory guard family.
3. The canonical benchmark remains deterministic and reviewable.
4. The expanded packs make it easier to tell whether the next bottleneck is routing, packaging, or retrieval recall.

## Notes

Randomized or heuristic mining is useful only in the exploratory candidate-generation loop. Promoted benchmark cases should remain reviewed and fixed once committed.
