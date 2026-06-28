---
id: add-injection-policy-abstention
title: Injection policy abstention — narrow delivery, type-gated proactivity, deterministic on-demand
status: shipped
priority: high
commitment: committed
milestone: Done
shipped_at: 2026-06-27
---

## Summary

Replace today's broadly-proactive injection with a per-type policy gated
on the injected-block result `score`. Types whose feedback shows
separable score distributions (`constraint_memory`, `decision`) stay
proactive with thresholds. Types whose scores don't separate
(`investigation_outcome`, `thread_summary`, `fact_summary`) become
on-demand or trigger-driven. `task_checkpoint` switches to an
event-trigger model (session resumption + path/branch match) rather
than score-thresholded proactive.

## Why

Five months of self-rated injection feedback shows base precision
~44%, dominated by topically-similar-but-question-irrelevant misses
("off-topic in the moment"). Multiple shipped mechanism iterations did
not move this number. Score separability analysis shows ~half the
memory types cannot reach 70% precision under any threshold. The
right next move is delivery-policy abstention, not another mechanism.

## Spec

[`docs/specs/2026-06-27-injection-policy-abstention.md`](../../docs/specs/2026-06-27-injection-policy-abstention.md)

## Phases

- [x] Phase 0 — analysis snapshot committed
      (`evals/injection_policy_2026_06/analyze.py`,
      `snapshot_2026-06-27.json`)
- [x] Phase 0.5 — `candidate_scores_json` extended with result `score`
- [x] Phase 1 — chronological holdout threshold validation
      (`holdout_2026-06-27.json`); no type met ≥70% on held-out tail —
      consistent with "abstention discipline" framing.
- [x] Phase 2a — approximate historical decision-simulation replay
      (`decision_replay_2026-06-27.json`); 51.38% precision on
      routing_score confirms the field-choice claim
- [ ] Phase 2b — exact prospective replay (requires fresh data window
      with the new `score` field)
- [x] Phase 3a — config schema + selection-path gate for proactive
      types; default config bit-exact no-op
- [x] Phase 4 — deterministic triggers in Claude Code integration
      (PostToolUse failure + retry, SessionStart orientation, pre-
      compact, user_prompt_submit, user_explicit). Codex parity
      shipped in follow-up.
- [x] Phase 3b — demote weak types: documented as opt-in
      commented-out block in `pallium.example.toml`. Default behavior
      unchanged.
- [x] Phase 5a — `memory_usage_audit` table + populator API surface
- [x] Phase 5b — populator hook in claude-code/codex stop hooks +
      Phase 5b match-text source-of-truth follow-up
      (2026-06-28: shared `build_memory_match_text` via
      `MemoryExpandResponse.match_text` to fix per-type undercount)
- [ ] Phase 6 — 4-week measurement window (infrastructure shipped at
      `evals/injection_policy_2026_06/phase6_measurement.py`; awaits
      live-data accumulation)

## Outstanding

Phase 2b and Phase 6 are measurement windows that need fresh live data;
all infrastructure is in place. No further code work scheduled until
that data accumulates and the decision matrix from the runbook
([`docs/runbooks/2026-06-27-injection-policy-phase6.md`](../../docs/runbooks/2026-06-27-injection-policy-phase6.md))
triggers the next decision.
