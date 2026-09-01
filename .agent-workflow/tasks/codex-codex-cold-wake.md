<!-- agent-workflow:start -->
**Outcome:** After an exact Codex Relay delivery is durably persisted, Pallium attempts a hidden, headless `codex exec --profile pallium-relay resume <session> - --json`; only an active-writer structured failure falls back to `codex queue`, while every other wake failure leaves the durable message for normal-turn delivery.

**Target:** Codex Relay MCP wake adapter and its installed `pallium-relay` profile.

**Scope:** The existing exact-Codex wake caller and directly required Codex profile/install support, their focused caller-surface E2E coverage, and this Work Record. Preserve the target worktree's unrelated `uv.lock` change.

**Constraints:** Persist before wake; exact Codex deliveries only; reuse delivery_id/idempotency; no shell command construction, visible window, broad approval bypass, scheduler/batching/wake-id/schema work, Claude/OpenCode work, or unrelated cleanup. Do not edit or commit `uv.lock`.

**Completion criteria:** Exec success sends no queue notification; structured active-writer failure queues once; every other exec failure queues nothing; duplicates/non-Codex/persistence failure never wake; hook delivery can reply; fallback remains normal-turn-safe; a real unloaded `relaydev` wake replies through Relay without an app ping or visible window.

**Risk:** Elevated

**Complexity:** Moderate

**Reason:** The intended MCP adapter is a gray `app/**` runtime surface with process launch and profile/tool-approval behavior. No red-zone or persistence/API change is intended; exact pre-edit redline remains required.

**Discovery:** The requested worktree already exists on `codex/codex-cold-wake` and has only an unrelated dirty `uv.lock`. The only wake call is `pallium_relay_send → _wake_exact_codex_delivery`, after `relay_send` returns persisted deliveries; replies do not wake. The current helper already uses vector argv, suppressed stdio, `CREATE_NO_WINDOW`, an exact selector, and one returned Codex delivery. The installed CLI accepts `codex exec --profile pallium-relay resume <session> - --json`; the user config already has the Pallium stdio MCP entry, but no profile file. Pre-edit redline is GRAY/Elevated, no checkpoint or boundary violation.

**Material assumptions:** The bundled Codex CLI supports the required headless `exec resume` invocation and emits a reliable active-writer signal; feature-test before relying on it, otherwise stop. Existing profile/config support can require the Pallium MCP server and narrowly allow only Relay send/reply; otherwise stop rather than inventing a broad approval bypass. Persisted delivery metadata exposes the exact session and durable identity needed for idempotent wake behavior; otherwise stop before adding a new state model.

**Plan:** (1) Extend the existing Codex setup helper only enough to create/remove an idempotent non-default `pallium-relay` profile that reuses the existing Pallium MCP definition, requires it, retains the default approval prompt, and allows only the real Relay send/reply tools; feature-test the profile parser first. (2) Replace the one post-persist exact-Codex wake helper: run hidden `codex exec --profile pallium-relay resume <session> - --json` with a static notification on stdin; parse structured output; invoke the existing hidden queue fallback once only for a positively identified active writer. (3) Carry the returned delivery_id/idempotency through that single helper without adding state. (4) Add focused caller-surface E2E for each required exec, duplicate, target, persistence, hook/reply, fallback, and invisible-window outcome. (5) Run the real unloaded `relaydev` no-ping wake/reply gate. Stop if the profile parser/CLI cannot provide narrow required-tool configuration or if active-writer cannot be positively identified.

**Verification plan:** Feature-test the bundled CLI/profile compatibility before implementation. When each explicit exec outcome is simulated, the adapter shall make the permitted fallback decision -> focused MCP caller-surface E2E. When the target is unloaded, an exact persisted Relay delivery shall wake `relaydev` and yield a Relay reply without an app ping or visible window -> real dogfood gate.

**Plan review:** Pre-edit redline and caller trace complete. Architect plan checkpoint pending via Relay before guarded edits.

**Approvals:** Not required at this risk level; the user has explicitly authorized the bounded architect direction.

**Exceptions:** —

**State:** Blocked
<!-- agent-workflow:end -->

## Implementation

- 2026-09-01: Work Record created before code. Branch `codex/codex-cold-wake`; preserve the pre-existing `uv.lock` modification. Redline classified the intended app paths GRAY/Elevated with no boundary violation; caller trace and CLI help feature check completed. Architect plan checkpoint is next; no guarded edit has started.
