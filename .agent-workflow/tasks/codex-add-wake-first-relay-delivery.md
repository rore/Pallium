<!-- agent-workflow:start -->
**Outcome:**
Codex exact-session wake is qualified or rejected with reproducible, sanitized evidence for all seven Phase 0 cases; no production wake behavior is added.

**Target:**
Pallium Relay exact-session wake Phase 0.

**Scope:**
Codex live-Windows qualification traces under untracked `.local/`, this Work Record, and only evidence-backed updates to `docs/designs/017-relay-wake-phase0.md`, `tests/relay/wake/fixtures/codex/`, and their deterministic tests.

**Constraints:**
Target only existing session `01a039d6-68de-7210-bfbf-78a0b15df139` via `codex queue --thread`; this Work Record authorizes Codex only, and any Claude probe requires an explicit scope amendment and fresh review. Do not self-trigger the target; coordinate each manager action with `codex:@relayarch`. Do not close the addressed task; missing/closed UUID probes must be non-destructive. Do not change production core, adapters, dashboard, API, schema, OpenCode, or passive Relay. Keep raw traces and tokens out of Git. Use only `scripts/restart-service.ps1` for service restart, with health checks.

**Completion criteria:**
For each of the seven Phase 0 cases, the exact existing Codex session has a sanitized result and raw local trace that proves pass, fail, or blocker without substituting an App Server, clone, resumed replacement, or managed session. Every attempted admission uses a unique `PHASE0` marker and is proven only by its model-visible appearance in this exact task plus the manager's task-history observation; a consolidated architect checkpoint records the resulting go/no-go before any production wake work.

**Risk:**
Elevated

**Complexity:**
Moderate

**Reason:**
The intended tracked outputs are blue-zone Work Record, documentation, tests, and fixtures, but the live qualification writes into an existing user-owned Codex session. Risk is raised for externally triggered turn safety; seven lifecycle cases and restart/ambiguity evidence make complexity Moderate.

**Discovery:**
`docs/designs/017-relay-wake-phase0.md` is active and supersedes 016. It identifies `codex queue --thread <THREAD_ID>` as the only candidate Codex surface and requires all seven cases: exact live-session identity, idle attribution, busy non-steering, correlated admission, unavailable states, restart recovery, and ambiguous-response retry. Existing Codex fixture slots and deterministic contract tests already exist. The architect brief prohibits App Server, clones/resumed replacements, managed substitutes, production wake code, and OpenCode; raw traces belong only in `.local/`. Clean-context architect review independently confirmed installed Codex CLI 0.149.1 exposes `queue --thread/--message` and requires unique markers, manager-observed history correlation, and architect-owned external trigger timing.

**Material assumptions:**
The current session remains a live, exact Codex TUI target and its hook can observe the attributed queued delivery; a trace showing a replacement process, missing correlated admission, or active-turn steering invalidates the candidate mechanism and the task stops with a passive-only/blocker verdict. `codex:@relayarch` will coordinate safe external trigger timing; without that coordination no live trigger is sent. Restart and ambiguous-response evidence must not replace or close the addressed task or invent an admission signal; inability to prove either safely is a valid BLOCKED/FAIL outcome.

**Plan:**
1. Capture sanitized preflight evidence for the installed Codex version, `codex queue` public syntax, current exact session identity, and passive Relay baseline in `.local/phase0-probes/`.
2. For every attempted live delivery, generate a unique `PHASE0` marker. Before the idle case, send `READY-IDLE <marker>` through Relay, ping the architect task, then stop/idle; the architect alone runs `codex queue --thread 01a039d6-68de-7210-bfbf-78a0b15df139`.
3. Treat queue write/CLI exit only as transport. Mark admission only when that marker appears model-visible in this exact task and the architect confirms it in manager task history.
4. Before the busy case, send `READY-BUSY <marker>` and ping the architect; the architect starts the controlled 30-second read-only turn and queues only while it is active. Record whether the marker starts a distinct subsequent turn without steering the active turn.
5. Run missing/closed/permission/unavailable probes non-destructively. For restart, use only `scripts/restart-service.ps1` and verify `/health`, `/status`, and `/debug/queue/health`; if restart or ambiguous-response behavior cannot be proven without replacing/closing the addressed task or inventing admission, record BLOCKED/FAIL with exact evidence.
6. Sanitize evidence, update the Phase 0 decision record and existing deterministic Codex fixtures/tests only when supported by traces, send the consolidated result/blocker checkpoint, and await architect go/no-go. Stop before production wake implementation.

Key conventions: retain passive Relay as fallback; queue transport acknowledgement is not admission; use a unique `PHASE0` marker per attempt; never commit secrets, tokens, raw traces, or a claimed pass without marker-correlated exact-session evidence.
Target files: `.agent-workflow/tasks/codex-add-wake-first-relay-delivery.md`; later, only if evidence warrants it, `docs/designs/017-relay-wake-phase0.md`, `tests/relay/wake/fixtures/codex/*.json`, `tests/test_relay_wake_fixtures.py`, and `tests/test_relay_wake_contract.py`.
Stop conditions: any non-exact target, active-turn steering, missing correlated admission, unavailable/permission failure, ambiguous result without safe idempotency proof, failed health check after restart, or unavailable architect trigger coordination.

**Verification plan:**
- When Codex case 1 runs, the session shall be the injected exact ID rather than a replacement → recorded process/session trace plus addressed-session observation.
- When cases 2–4 run, idle/busy behavior shall preserve attribution and prove admission only through a unique marker correlated in exact-task model context and manager history → raw trace plus sanitized fixture/result.
- When cases 5–7 run, each unavailable/restart/ambiguous outcome shall retain passive Relay fallback without an unsafe retry → service health records, queue/event traces, and decision table.
- When tracked evidence changes, deterministic fixtures and their focused tests shall agree with the sanitized outcome → `pytest tests/test_relay_wake_fixtures.py tests/test_relay_wake_contract.py`.
- When the qualification ends, no production wake surface shall be changed → `git diff --check` and path review against the recorded scope.

**Plan review:**
Clean-context architect review approved through Relay reply `relay-reply-57a90ba446e232440448e710aa04ff6382438e23ae94267fbefb77fd9c95b705` on 2026-08-27. Required notes applied: Codex-only scope; unique marker plus task/history admission evidence; architect-owned idle/busy trigger timing; non-destructive UUID probes; and BLOCKED/FAIL rather than unsafe restart/ambiguity substitutions.

**Approvals:**
Not required at this risk level.

**Exceptions:**
—

**State:** Ready to implement
<!-- agent-workflow:end -->

## Implementation

2026-08-27 — Branch created from synced `origin/main` at `0b618235f63e23e202e33280b7dfe30391b41262`. No Phase 0 trigger or production wake implementation has begun. Awaiting the architect’s checkpoint-1 review and trigger-timing coordination.

2026-08-27 — Architect review approved the Codex-only qualification plan with the recorded marker, evidence, and external-timing constraints. State transitioned to `Ready to implement`; only local preflight is permitted until the first `READY-IDLE <marker>` checkpoint.
2026-08-27 — Codex idle case PASS. Architect independently observed queue item `01a044ec-adb3-75a1-9e77-2e5d0031f00a` for exact session `01a039d6-68de-7210-bfbf-78a0b15df139`; unique marker `PHASE0-IDLE-25ba0abf84154a678c6cdf96422baf89` became the next persisted user message and produced a model-visible response in this same task. Queue acceptance was treated only as transport; the task/history correlation establishes admission. Sanitized raw evidence: `.local/phase0-probes/codex-preflight-20260827-233109/idle-verdict.json`.

2026-08-27 — Codex busy case PASS. Architect task-history evidence shows the `BUSY-BASELINE` turn completed at 20:36:57 and a distinct queued-item turn started at 20:37:02 with marker `PHASE0-BUSY-3cfab422ada3422bb7f82fa935ad29e6`; no active-turn steering occurred. A later app-snapshot `interrupted` label is retained as an observability discrepancy, not treated as evidence that erases model-visible admission.
2026-08-27 — Safe remaining probes: nonexistent UUID `00000000-0000-0000-0000-000000000000` was rejected by `codex queue` with no rollout found, without touching the target; `scripts/restart-service.ps1` completed and `/health`, `/status`, and `/debug/queue/health` each returned HTTP 200. Sanitized raw evidence: `.local/phase0-probes/codex-preflight-20260827-233109/safe-probe-verdict.json`.

2026-08-27 — Consolidated Codex Phase 0 verdict (architect-controlled):

| Case | Verdict | Sanitized evidence |
|---|---|---|
| 1. Exact live session | PASS | All manager-triggered queue operations targeted `01a039d6-68de-7210-bfbf-78a0b15df139`; no App Server, clone, resumed replacement, or managed substitute was used. |
| 2. Idle attributed turn | PASS | Queue item `01a044ec-adb3-75a1-9e77-2e5d0031f00a` produced the marker `PHASE0-IDLE-25ba0abf84154a678c6cdf96422baf89` as the next persisted user message and model-visible exact-task turn. |
| 3. Busy non-steering turn | PASS | The controlled baseline completed at 20:36:57; marker `PHASE0-BUSY-3cfab422ada3422bb7f82fa935ad29e6` entered a distinct following turn at 20:37:02, not the active turn. |
| 4. Correlated admission | PASS | Manager exact-rollout/task-history evidence correlated each PASS marker to the addressed task’s persisted user message and model-visible response; queue write alone was never treated as admission. |
| 5. Closed/stale/permission/unavailable | BLOCKED | Unknown UUID was rejected non-destructively (`no rollout found`), proving unavailable handling only. Closing the addressed task or forcing permission denial is out of scope and was not attempted. |
| 6. Pallium restart recovery | PASS | After `scripts/restart-service.ps1`, queue item `01a044f4-841d-75d3-b55e-42c2ccaecb11` produced exact-task turn `01a044f4-aa3f-7f93-bab3-34dc5e7c81cd` with marker `PHASE0-RESTART-065c2ef792e44dbca01b0afa041b28ca`; all required endpoints returned HTTP 200. |
| 7. Ambiguous-response retry | BLOCKED | A forced ambiguous transport response could not be safely produced without manufacturing evidence. Separate duplicate probe failed native idempotency: items `01a044f5-adf2-7300-8ff0-29516413b51e` and `01a044f5-baf2-7660-a7d1-daac66519ef0` produced two distinct target turns with the same marker. |

The Codex exact-session queue mechanism is proven for idle, busy-safe-boundary, correlated admission, and Pallium-restart delivery, but Phase 0 is not fully cleared: case 5 and case 7 remain BLOCKED. Native queue idempotency is explicitly FAIL; any future coordinator must dedupe before invoking `codex queue` using the Pallium delivery/wake-attempt identity. Passive Relay remains unchanged and no production wake implementation was started.

Follow-up observations outside this Phase 0 scope: (1) the app snapshot later labeled the successful busy turn `interrupted`, contradicting persisted/task-history model-visible admission; preserve this observability discrepancy for runtime diagnostics. (2) direct Codex MCP `pallium_relay_receive` lacked a bound session identity in this task, while the installed UserPromptSubmit hook had the correct session context; track `fix-relay-receive-mcp-lifecycle` separately before adapter work.

2026-08-27 — Phase 0 evidence complete to the safe boundary. State transitioned to `Ready for review`; final architecture review requested before any scope amendment or production work.