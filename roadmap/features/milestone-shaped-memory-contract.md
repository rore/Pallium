---
id: milestone-shaped-memory-contract
title: Milestone — Ship a shaped memory contract
status: paused
priority: high
commitment: committed
milestone: Now
started_at: 2026-07-01
---

## Summary

Six-week milestone to move Pallium from "accumulating mechanisms" to
"shipping a coherent, evaluable memory shape." Attacks three real gaps
(no explicit interaction contract, no shipped operational-memory object,
no narrow testable target) and one anti-pattern (retrieval-as-success
feedback). Runs a simplification pass alongside — every PR either removes
code or shows why it can't — bounded by the rule that Pallium working
comes first.

## Spec

[`docs/specs/2026-07-01-milestone-shaped-memory-contract.md`](../../docs/specs/2026-07-01-milestone-shaped-memory-contract.md)

## Workstreams

- **W1** — Finish delivery-side fix (abstention Phase 2b + Phase 6) — ⏳ awaiting fresh data window (~2026-07-05).
- **W2** — Narrow target: Claude Code sessions on this repo, five named scenarios with runnable evals — ✅ shipped.
- **W3** — Explicit memory-write MCP tools (`remember` / `correct` / `supersede` / `forget` / `record_outcome`) — ✅ shipped.
- **W4** — Ship operational memory as on-demand object (unpause `add-operational-fact-memory`) — ✅ **shipped 2026-07-01** across 5 PRs (a0ef64c → b5bf26e).
- **W5** — Shadow-test typed one-pass extraction; per-type go/no-go — ⏳ 4 of 5 PRs shipped 2026-07-01 (foundation + extractor + wiring + comparison eval). PR 5 (per-type promotion) contingent on ≥2 weeks of shadow-populated live data.
- **W6** — Two enforceable invariants in `docs/context/lessons.md` — ✅ shipped.
- **W7** — Simplification pass (rolling; `semantic/` ≤10k lines, routing ≤5 files, no no-default config knobs) — ⏳ Phase 1 in progress.

## Milestone Acceptance

1. All five narrow-target scenarios pass at ≥ baseline precision.
2. Abstention delivers ≥70% precision on remaining proactive types on
   held-out data.
3. Explicit memory tools live in both integrations.
4. Operational memory shipped on-demand; zero proactive injections.
5. Typed-extraction go/no-go published per memory type; losing paths
   deleted where shadow won.
6. `semantic/` ≤10k lines, routing ≤5 files. Zero new no-default config
   knobs.
7. Engineering-discipline compliance on every merged PR: architect
   review before, code review after, defensive-programming checklist,
   full-suite regression sweep clean, rollback plan documented.

If (1) and (2) don't land, the milestone did not succeed regardless of
simplification numbers. If (7) slips, the milestone did not succeed
regardless of what shipped.

## Related

- Resumes: `add-operational-fact-memory` (W4)
- Continues: `add-injection-policy-abstention` (W1, Phases 2b + 6)
- New: `add-explicit-memory-write-tools` (W3), `add-narrow-target-claude-code-scenarios` (W2), `add-typed-extraction-shadow` (W5)
