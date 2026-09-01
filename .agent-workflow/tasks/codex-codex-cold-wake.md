<!-- agent-workflow:start -->
**Outcome:** After an exact Codex Relay delivery is durably persisted, Pallium attempts a hidden, headless `codex exec --profile pallium-relay resume <session> - --json`; only an active-writer structured failure falls back to `codex queue`, while every other wake failure leaves the durable message for normal-turn delivery.

**Target:** Codex Relay MCP wake adapter and its installed `pallium-relay` profile.

**Scope:** The existing exact-Codex wake caller and directly required Codex profile/install support, their focused caller-surface E2E coverage, and this Work Record. Preserve the target worktree's unrelated `uv.lock` change.

**Constraints:** Persist before wake; exact Codex deliveries only; reuse delivery_id/idempotency; no shell command construction, visible window, broad approval bypass, scheduler/batching/wake-id/schema work, Claude/OpenCode work, or unrelated cleanup. Do not edit or commit `uv.lock`.

**Completion criteria:** Exec success sends no queue notification; structured active-writer failure queues once; every other exec failure queues nothing; duplicates/non-Codex/persistence failure never wake; hook delivery can reply; fallback remains normal-turn-safe; a real unloaded `relaydev` wake replies through Relay without an app ping or visible window.

**Risk:** Elevated

**Complexity:** Moderate

**Reason:** The intended MCP adapter is a gray `app/**` runtime surface with process launch and profile/tool-approval behavior. No red-zone or persistence/API change is intended; exact pre-edit redline remains required.

**Discovery:** The requested worktree already exists on `codex/codex-cold-wake` and has only an unrelated dirty `uv.lock`. The current `app/mcp/server.py` owns `_wake_exact_codex_delivery` after persisted MCP send; all callers and current Codex integration/profile support still need tracing before a guarded edit.

**Material assumptions:** The bundled Codex CLI supports the required headless `exec resume` invocation and emits a reliable active-writer signal; feature-test before relying on it, otherwise stop. Existing profile/config support can require the Pallium MCP server and narrowly allow only Relay send/reply; otherwise stop rather than inventing a broad approval bypass. Persisted delivery metadata exposes the exact session and durable identity needed for idempotent wake behavior; otherwise stop before adding a new state model.

**Plan:** Create and commit this Work Record, obtain independent pre-edit redline classification, trace all wake/send/reply/profile callers, then send one concise Relay plan checkpoint and pause. After that checkpoint and required review, implement only the smallest shared exact-Codex post-persist wake helper and its focused caller-surface E2E tests.

**Verification plan:** Feature-test the bundled CLI/profile compatibility before implementation. When each explicit exec outcome is simulated, the adapter shall make the permitted fallback decision -> focused MCP caller-surface E2E. When the target is unloaded, an exact persisted Relay delivery shall wake `relaydev` and yield a Relay reply without an app ping or visible window -> real dogfood gate.

**Plan review:** Pending pre-edit redline, caller trace, and architect plan checkpoint.

**Approvals:** Not required at this risk level; the user has explicitly authorized the bounded architect direction.

**Exceptions:** —

**State:** Blocked
<!-- agent-workflow:end -->

## Implementation

- 2026-09-01: Work Record created before code. Branch `codex/codex-cold-wake`; preserve the pre-existing `uv.lock` modification. Next: redline classification and full caller trace, then one architect plan checkpoint before guarded edits.
