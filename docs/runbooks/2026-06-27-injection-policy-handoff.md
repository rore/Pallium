# Injection-Policy Abstention — Implementation Handoff

**Branch:** `feat/injection-policy-abstention`
**Spec:** [docs/specs/2026-06-27-injection-policy-abstention.md](docs/specs/2026-06-27-injection-policy-abstention.md)
**Roadmap card:** [roadmap/features/add-injection-policy-abstention.md](roadmap/features/add-injection-policy-abstention.md)
**Date:** 2026-06-27

## Status — what shipped, what didn't

| Phase | Commit | Status |
|---|---|---|
| 0   | `2733da3` | shipped: analysis snapshot + 15 tests + headline numbers committed |
| 0.5 | `a8e178e` | shipped: `score` + `retrieval_source` in `candidate_scores_json` |
| 1   | `5f97156` | shipped: chronological holdout — **no type met ≥70% pass bar** |
| 2a  | `4c99caf` | shipped: approximate historical replay — confirms `routing_score` is the wrong field |
| 3a  | `217cdfa` | shipped: config schema + selection-path gate + audit attribution |
| 3b  | `bcc1765` | shipped: pallium.example.toml commented-out demotion block |
| 4   | `bcc1765` | shipped: trigger_origin plumbing + `post_tool_use.py` hook + gate bypass |
| 5a  | `8859c1c` | shipped: `memory_usage_audit` table + GET/POST endpoints + write-at-injection |
| 5b  | — | DEFERRED: populator hook (heuristic matcher in stop.py) |
| 6   | `21ee896` | shipped: measurement script + runbook (awaits live data) |

**Test outcome:** 2381 pass (118 new in this branch), 1 pre-existing
failure (`test_prompt_variants_legacy_fallback_unaffected`) unchanged
across all commits.

## What this does NOT promise

- **None of the policy is active by default.** Absent
  `[injection.policy]` in `pallium.local.toml`, the gate is a
  bit-exact no-op. To turn it on, copy the commented-out block from
  `pallium.example.toml`.
- **Phase 1 result is the load-bearing finding:** on chronological
  holdout, no memory type meets the spec's original ≥70% precision
  bar. The headline 75% from Phase 0 was selection-on-train
  optimism. Shipping with empty `recommended_final_policy` is the
  honest outcome of the data, not a bug.
- **Phase 4 ships infrastructure, not validated outcomes.** The
  triggers are deployed and tagged in audit logs, but whether they
  produce useful injections requires Phase 6's 4-week window to
  measure. The Phase 4 pass-bar (≥X% trigger fire rate + ≥70%
  precision on at least one trigger) is gated on that data, not
  this commit.
- **Phase 5b populator does not exist yet.** Phase 5a writes
  `memory_usage_audit` rows with `populated_at=NULL`. Until 5b ships
  the heuristic matcher in `stop.py`, Phase 6's `usage_rate` will
  always be `None` and only `rating_precision` will be meaningful.

## Operational next steps (sequence for the owner)

### Step 1 — Verify default behavior on existing installs

```bash
git checkout main
git pull
python -m app.run serve --port 8000
# Smoke test: query an existing thread and verify injection still works.
```

Phase 3a is additive; default config means no behavior change.

### Step 2 — Re-run setup to register the new PostToolUse hook

```bash
python -m app.run setup claude-code
```

This adds `PostToolUse` to `~/.claude/settings.json`. The hook fails
silently if Pallium is not running, so it can't break Claude Code.

### Step 3 — Run Phase 5b populator (when ready)

Phase 5b is small: extend `integrations/claude-code/hooks/stop.py`
per the contract docstring already in that file. Loop:

1. List recent queries in this thread from the last 1–2 turns.
2. `GET /memory-usage-audit?query_audit_log_id=...` for each.
3. For each row with `populated_at IS NULL`, run id_quote OR
   verbatim_snippet ≥ 40 chars against the assistant transcript.
4. `POST /memory-usage-audit/<row_id>` with the result. Idempotent.

There's no architect review for 5b yet; do one before implementing.

### Step 4 — Opt in to the demoted policy on chosen containers

Copy the commented block from `pallium.example.toml` into your
`pallium.local.toml`. Restart the service. The gate now drops
`investigation_outcome` / `thread_summary` / `fact_summary` from
proactive injection, switches `task_checkpoint` to event-trigger
mode, and lets all of them surface via Phase 4 triggers.

### Step 5 — Wait ~4 weeks

Long enough to get ≥30 populated rows per (type, trigger) cell.

### Step 6 — Run Phase 6 measurement

Follow [docs/runbooks/2026-06-27-injection-policy-phase6.md](docs/runbooks/2026-06-27-injection-policy-phase6.md).
Decision matrix maps observed numbers to: hold / tighten / delete
types / disable triggers / debug populator.

## Reproducible artifacts committed

| Artifact | What it backs |
|---|---|
| `evals/injection_policy_2026_06/snapshot_2026-06-27.json` | Spec headline numbers (75% / 92% / 29%) |
| `evals/injection_policy_2026_06/holdout_2026-06-27.json` | Phase 1 chronological-holdout result (no type passed) |
| `evals/injection_policy_2026_06/decision_replay_2026-06-27.json` | Phase 2a approximate replay (51.38% / 44.86%) |

Regenerate any of these by running the corresponding module with
`--output <path>`.

## Files changed (full list)

### Production code
- `app/config.py` — new `InjectionTypePolicy` / `InjectionPolicyConfig` / `InjectionConfig` dataclasses + `_build_injection_config` loader
- `app/dependencies.py` — wires resolved config into `PalliumService`
- `app/cli/setup_claude_code.py` — registers `PostToolUse` hook
- `api/routes.py` — trigger_origin validation, `/memory-usage-audit` endpoints
- `api/schemas.py` — `trigger_origin` on `QueryRequest`, usage-audit schemas
- `core/service.py` — `injection_policy` + `trigger_origin` threading, usage-audit write
- `core/query.py` — `injection_policy` + `trigger_origin` kwargs on `QueryExecutor`
- `core/routing.py` — same kwargs threaded into `_route_query_results`
- `semantic/agent_conversation_memory_routing.py` — same kwargs to `_build_injectable_blocks`
- `semantic/agent_conversation_memory_routing_selection.py` — `_policy_allows_proactive_injection` gate + bypass logic
- `storage/sqlite.py` — `MemoryUsageAuditRecord` storage methods
- `storage/sqlite_schema.py` — `MemoryUsageAuditRecord` declarative class + indexes + `trigger_origin` column on `query_audit_log`

### Integration hooks
- `integrations/claude-code/hooks/session_start.py` — `trigger_origin=session_start_orientation`
- `integrations/claude-code/hooks/user_prompt_submit.py` — `query_trigger_origin=user_prompt_submit`
- `integrations/claude-code/hooks/pre_compact.py` — `trigger_origin=pre_compact`
- `integrations/claude-code/hooks/stop.py` — Phase 5b contract docstring
- `integrations/claude-code/hooks/post_tool_use.py` — **new**: failure + retry-threshold triggers

### Docs + config
- `docs/specs/2026-06-27-injection-policy-abstention.md` — primary spec, updated per-phase
- `docs/runbooks/2026-06-27-injection-policy-phase6.md` — measurement decision runbook
- `pallium.example.toml` — commented-out Phase 3b demotion block
- `roadmap/board.md` — paused list
- `roadmap/features/add-injection-policy-abstention.md` — feature card
- `roadmap/features/add-operational-fact-memory.md` — paused
- `roadmap/features/investigate-thread-level-interest-and-threadless-aggregation.md` — paused

### Evals + tests
- `evals/injection_policy_2026_06/__init__.py`
- `evals/injection_policy_2026_06/README.md`
- `evals/injection_policy_2026_06/analyze.py` — Phase 0
- `evals/injection_policy_2026_06/holdout.py` — Phase 1
- `evals/injection_policy_2026_06/decision_replay.py` — Phase 2a
- `evals/injection_policy_2026_06/phase6_measurement.py` — Phase 6
- `evals/injection_policy_2026_06/snapshot_2026-06-27.json` — Phase 0 baseline
- `evals/injection_policy_2026_06/holdout_2026-06-27.json` — Phase 1 result
- `evals/injection_policy_2026_06/decision_replay_2026-06-27.json` — Phase 2a result
- `tests/test_injection_policy_2026_06_analyze.py` — 15 tests
- `tests/test_injection_policy_2026_06_holdout.py` — 23 tests
- `tests/test_injection_policy_2026_06_decision_replay.py` — 21 tests
- `tests/test_injection_policy_2026_06_phase3a.py` — 28 tests
- `tests/test_injection_policy_2026_06_phase4.py` — 30 tests
- `tests/test_injection_policy_2026_06_phase5.py` — 16 tests
- `tests/test_injection_policy_2026_06_phase6.py` — 9 tests
- `tests/test_claude_code_hooks/test_post_tool_use.py` — 12 tests
- `tests/test_query_audit_log.py` — extended for Phase 0.5 fields

## Working-environment notes

- All commands ran via the workaround documented in
  [.local/working/python-runbook.md](.local/working/python-runbook.md)
  (Windows security blocks the uv stub launcher).
- Progress log: [.local/working/injection-policy-progress.md](.local/working/injection-policy-progress.md).
- Both are gitignored (under `.local/`).

## Pre-existing test failure

`tests/test_config.py::test_prompt_variants_legacy_fallback_unaffected`
fails identically on `main` (pre-Phase 0) and on every Phase commit
in this branch. The failure is environmental (likely an env var
bleeding through). Not caused by this work.

## What to do if Phase 6 says the abstention thesis was wrong

Roll back is one TOML edit:

```toml
# remove the [injection.policy.*] blocks from pallium.local.toml,
# restart the service. The gate becomes a no-op again.
```

No production-code rollback needed. Phase 3a's no-op-when-empty
property is the safety net.
