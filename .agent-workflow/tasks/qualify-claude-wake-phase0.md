<!-- agent-workflow:start -->
**Outcome:**
Claude Code exact-session wake Phase 0 has a reviewed, reproducible non-triggering plan and sanitized local preflight for the existing `claude-code:@relaydev` session; no production wake behavior is added.

**Target:**
Pallium Relay Claude Code exact-session wake Phase 0 on native Windows.

**Scope:**
This Work Record and evidence-backed reconciliation of `docs/designs/017-relay-wake-phase0.md`; local untracked, sanitized preflight observations only.

**Constraints:**
Target only architect-specified existing session `93fa25ba-b5a2-4037-837d-a171e4401023` through `claude-code:@relaydev`. Do not send a live message, open or write the target pipe, create/replace/resume a Claude session, print/persist/commit `CLAUDE_CODE_MESSAGING_TOKEN` or pipe paths, or change production core, adapters, API, schema, dashboard, OpenCode, installer, or coordinator. The architect owns any future external-trigger timing.

**Completion criteria:**
Before any live trigger, the Work Record records all seven Phase 0 cases, the installed Claude version and safe Path A preflight, the exact identity/admission evidence required, and a Relay checkpoint states the remaining architect-controlled trigger coordination.

**Risk:**
Elevated

**Complexity:**
Moderate

**Reason:**
Pre-edit redline is BLUE for the Work Record and design record, but the task qualifies an external, user-owned Claude session and an undocumented credential boundary. Moderate uncertainty spans seven lifecycle cases and exact-session identity without recording secrets.

**Discovery:**
`docs/designs/017-relay-wake-phase0.md` is the active Phase 0 record. It identifies Claude Path A as an undocumented own-child token seam requiring live evidence and `Stop` rather than `UserPromptSubmit` exit as the idle boundary. Non-triggering preflight confirmed Claude Code `2.1.246`, existing `SessionStart` and `Stop` hook sources, Pallium settings presence, and `/health`, `/status`, and `/debug/queue/health` (HTTP 200); it did not access any token, pipe, session registry, or target. `claude --help` did not advertise `--channels`, so Path B/C is not preflight-confirmed for this installed CLI. Pallium reports `claude-code:@relaydev` / `93fa25ba-b5a2-4037-837d-a171e4401023` as `recent`, last seen `2026-08-27T17:27:44Z`; this is not proof of an active target. The architect supplied the only permitted identity and forbids all live triggering at this checkpoint. Pre-edit redline classified the two intended tracked files BLUE with no boundary or checkpoint findings.

**Material assumptions:**
The architect-specified alias is currently only `recent`, last seen `2026-08-27T17:27:44Z`; it must be proven active and mapped to immutable session ID `93fa25ba-b5a2-4037-837d-a171e4401023` by a future architect-controlled observation. Absence, staleness, inactivity, or replacement invalidates Path A and stops the task. A preflight can inspect installed versions, hook configuration shape, and Pallium health without reading or exposing any token or connecting to the target pipe; any need to do otherwise stops the task. Path A remains unsupported until a model-visible, exact-session admission is correlated by a unique marker and the target session's `Stop` hook. Before any Path A probe, a separate reviewed integration/probe task must implement an audited loopback-only credential registration/probe path that transfers the target credential directly without model context, command arguments, stdout/stderr, files, Relay, or logs; it must use a user-present disposable target. That path does not exist in this task.

**Plan:**
1. Record this Claude-only Phase 0 plan and classify its documentation scope before any probe.
2. Run only non-triggering preflight: verify installed Claude version and public local integration/hook shape, confirm Pallium health, and confirm that the planned evidence boundary never emits or persists a token or pipe path.
3. Reconcile the existing Claude section of design 017 only with facts established by that safe preflight; retain passive-only status and Path C fallback.
4. Define the evidence/stop conditions for all seven cases: exact live identity; idle attributed turn; busy non-steering or explicit unavailable fallback; correlated `Stop`-hook admission; closed/stale/permission/unavailable; restart recovery; and ambiguous-response retry.
5. Send one consolidated Relay checkpoint to the architect. It must request architect-owned proof that the alias maps to the exact active session, a unique marker and idle/busy timing, and model/history correlation. Do not request a token handoff: Path A is blocked until a separate reviewed integration/probe task provides an audited loopback-only credential registration/probe path that transfers the credential directly without model context, command arguments, stdout/stderr, files, Relay, or logs, using a user-present disposable target. Stop before any live trigger.

Key conventions: `Stop` is the only primary idle/admission boundary; transport or pipe connection is never admission; use a unique marker for every future attempt; keep raw observations untracked and sanitized; preserve durable natural-turn fallback.

Target files: `.agent-workflow/tasks/qualify-claude-wake-phase0.md`; only if safe preflight establishes a correction, `docs/designs/017-relay-wake-phase0.md`.

**Verification plan:**
- When planning begins, the branch shall originate at merged `origin/main` without unrelated changes -> `git rev-parse` comparison and clean status.
- When preflight runs, it shall show the installed Claude version, non-triggering integration shape, and Pallium health without exposing tokens or pipe paths -> redacted command output review plus `/health`, `/status`, and `/debug/queue/health`.
- Before any live trigger, every Phase 0 case shall have an explicit pass condition and a safe stop condition -> Work Record and design-017 review.
- When the checkpoint is sent, it shall name the exact architect-owned identity/timing and the separate audited credential-path security gate, without requesting credential material -> Relay reply and architect task ping.
- When tracked files change, governance shall remain clean -> `git diff --check`, `agent-redline-report`, and `agent-workflow-check`.

**Plan review:**
Clean-context review via Relay delivery `relay-delivery-6e1b2e4d66ea49d5bccd0956ceff09bd` required four bounded documentation/security-gate corrections. They are applied in the pending docs-only correction; final review remains required. No live trigger is authorized by this record.

**Approvals:**
Not required at this risk level.

**Exceptions:**
—

**State:** Blocked
<!-- agent-workflow:end -->

## Phase 0 evidence matrix

| Case | Pass evidence required | Safe stop / fallback at this checkpoint |
|---|---|---|
| 1. Exact live identity | Architect proves `claude-code:@relaydev` maps to active immutable session `93fa25ba-b5a2-4037-837d-a171e4401023`, then a unique marker is observed in that exact task. | Current state is only `recent`, last seen `2026-08-27T17:27:44Z`; do not trigger or contact it. Preserve natural-turn Relay. |
| 2. Idle attributed turn | One architect-timed unique marker produces a distinct exact-session turn and target `Stop`-hook evidence. | No active identity or audited credential path -> no pipe use; leave delivery for natural turn. |
| 3. Busy non-steering | Controlled busy timing proves no active-turn steering; either a distinct later turn is correlated or documented `unavailable` releases fallback. | Never send into an uncontrolled busy target; use natural-turn fallback. |
| 4. Correlated admission | Target `Stop` hook directly reports the unique delivery marker through the approved loopback admission path; pipe/transport acceptance alone is insufficient. | Missing callback or any secret-exposure route -> no ACK and release durable fallback. |
| 5. Closed/stale/permission/unavailable | Each state has a distinct observed reason and no permanent-failure retry. | Do not close, alter permissions, or manufacture a failure; record BLOCKED and retain fallback. |
| 6. Runtime or Pallium restart | An outstanding trigger recovers and an already-admitted delivery remains exactly once, both correlated to target history. | Do not restart or replace the target in this task; leave case BLOCKED and retain fallback. |
| 7. Ambiguous response | A single trigger remains suppressed until admission deadline, then releases fallback once unless runtime idempotency is proven. | Do not manufacture ambiguity or retry Path A; release only natural-turn fallback. |

## Implementation

2026-08-28 — Created from synced `origin/main` commit `e80ef2e3f4b54638b5ec003d15073e2a9d3fe110` on branch `codex/qualify-claude-wake-phase0`. Planning and safe preflight only; waiting to run the recorded non-triggering checks and obtain architect plan review before any external trigger.

2026-08-28 — Non-triggering preflight completed: Claude Code 2.1.246; installed Pallium settings and source SessionStart/Stop hooks present; /health and /status reported healthy with embedding_provider_ok=true; /debug/queue/health returned HTTP 200. No token, pipe, target-session registry, or target contact was accessed. Path A non-child reachability remains UNPROVEN; claude --help did not advertise --channels, so Path B/C needs separate installed-runtime proof. State remains Blocked pending architect plan review and live-trigger coordination.
