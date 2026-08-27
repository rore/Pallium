<!-- agent-workflow:start -->
**Outcome:**
Codex exact-session wake is qualified or rejected with reproducible, sanitized evidence for all seven Phase 0 cases; no production wake behavior is added.

**Target:**
Pallium Relay exact-session wake Phase 0.

**Scope:**
Codex live-Windows qualification traces under untracked `.local/`, this Work Record, and only evidence-backed updates to `docs/designs/017-relay-wake-phase0.md`, `tests/relay/wake/fixtures/codex/`, and their deterministic tests.

**Constraints:**
Target only existing session `01a039d6-68de-7210-bfbf-78a0b15df139` via `codex queue --thread`; run Codex first, Claude only if Codex is conclusive and budget remains; do not change production core, adapters, dashboard, API, schema, OpenCode, or passive Relay. Keep raw traces and tokens out of Git. Use only `scripts/restart-service.ps1` for service restart, with health checks. Coordinate trigger timing with `codex:@relayarch`.

**Completion criteria:**
For each of the seven Phase 0 cases, the exact existing Codex session has a sanitized result and raw local trace that proves pass, fail, or blocker without substituting an App Server, clone, resumed replacement, or managed session; a consolidated architect checkpoint records the resulting go/no-go before any production wake work.

**Risk:**
Elevated

**Complexity:**
Moderate

**Reason:**
The intended tracked outputs are blue-zone Work Record, documentation, tests, and fixtures, but the live qualification writes into an existing user-owned Codex session. Risk is raised for externally triggered turn safety; seven lifecycle cases and restart/ambiguity evidence make complexity Moderate.

**Discovery:**
`docs/designs/017-relay-wake-phase0.md` is active and supersedes 016. It identifies `codex queue --thread <THREAD_ID>` as the only candidate Codex surface and requires all seven cases: exact live-session identity, idle attribution, busy non-steering, correlated admission, unavailable states, restart recovery, and ambiguous-response retry. Existing Codex fixture slots and deterministic contract tests already exist. The architect brief prohibits App Server, clones/resumed replacements, managed substitutes, production wake code, and OpenCode; raw traces belong only in `.local/`.

**Material assumptions:**
The current session remains a live, exact Codex TUI target and its hook can observe the attributed queued delivery; a trace showing a replacement process, missing correlated admission, or active-turn steering invalidates the candidate mechanism and the task stops with a passive-only/blocker verdict. `codex:@relayarch` will coordinate safe external trigger timing; without that coordination no live trigger is sent.

**Plan:**
1. Capture sanitized preflight evidence for the installed Codex version, `codex queue` public syntax, current exact session identity, and passive Relay baseline in `.local/phase0-probes/`.
2. Coordinate each external trigger with `codex:@relayarch`, then run Codex cases 1–7 using only `codex queue --thread 01a039d6-68de-7210-bfbf-78a0b15df139`; observe the addressed session’s own model-bound hook/event for delivery-ID admission rather than treating queue acceptance as success.
3. For restart evidence, restart only through `scripts/restart-service.ps1`, verify `/health`, `/status`, and `/debug/queue/health`, and preserve the same exact-session/no-steering criteria.
4. If and only if Codex is conclusive and budget remains, repeat the seven-case decision matrix for Claude; do not probe OpenCode in this task.
5. Sanitize evidence, update the Phase 0 decision record and existing deterministic Codex fixtures/tests only when supported by traces, send the consolidated result/blocker checkpoint, and await architect go/no-go. Stop before production wake implementation.

Key conventions: retain passive Relay as fallback; queue transport acknowledgement is not admission; never commit secrets, tokens, raw traces, or a claimed pass without the exact delivery-ID correlation.
Target files: `.agent-workflow/tasks/codex-add-wake-first-relay-delivery.md`; later, only if evidence warrants it, `docs/designs/017-relay-wake-phase0.md`, `tests/relay/wake/fixtures/codex/*.json`, `tests/test_relay_wake_fixtures.py`, and `tests/test_relay_wake_contract.py`.
Stop conditions: any non-exact target, active-turn steering, missing correlated admission, unavailable/permission failure, ambiguous result without safe idempotency proof, failed health check after restart, or unavailable architect trigger coordination.

**Verification plan:**
- When Codex case 1 runs, the session shall be the injected exact ID rather than a replacement → recorded process/session trace plus addressed-session observation.
- When cases 2–4 run, idle/busy behavior shall preserve attribution and prove admission only through a delivery-ID-correlated model-bound event → raw trace plus sanitized fixture/result.
- When cases 5–7 run, each unavailable/restart/ambiguous outcome shall retain passive Relay fallback without an unsafe retry → service health records, queue/event traces, and decision table.
- When tracked evidence changes, deterministic fixtures and their focused tests shall agree with the sanitized outcome → `pytest tests/test_relay_wake_fixtures.py tests/test_relay_wake_contract.py`.
- When the qualification ends, no production wake surface shall be changed → `git diff --check` and path review against the recorded scope.

**Plan review:**
Pending clean-context architect review through Relay checkpoint 1.

**Approvals:**
Not required at this risk level.

**Exceptions:**
—

**State:** Blocked
<!-- agent-workflow:end -->

## Implementation

2026-08-27 — Branch created from synced `origin/main` at `0b618235f63e23e202e33280b7dfe30391b41262`. No Phase 0 trigger or production wake implementation has begun. Awaiting the architect’s checkpoint-1 review and trigger-timing coordination.
