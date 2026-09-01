<!-- agent-workflow:start -->
**Outcome:** After an exact Codex Relay delivery is durably persisted, Pallium attempts a hidden, headless `codex exec --profile pallium-relay resume <session> - --json`; only an active-writer structured failure falls back to `codex queue`, while every other wake failure leaves the durable message for normal-turn delivery.

**Target:** Durable shared Relay-send wake scheduler and its installed `pallium-relay` Codex profile.

**Scope:** The shared `RelayService.send` post-persistence path, removal of its MCP-only wake wrapper, directly required Codex profile/install support, and focused HTTP plus MCP caller-surface E2E coverage. Preserve the target worktree's unrelated `uv.lock` change.

**Constraints:** Persist before wake; exact Codex deliveries only; reuse delivery_id/idempotency; no shell command construction, visible window, broad approval bypass, scheduler/batching/wake-id/schema work, Claude/OpenCode work, or unrelated cleanup. Do not edit or commit `uv.lock`.

**Completion criteria:** Exec success sends no queue notification; structured active-writer failure queues once; every other exec failure queues nothing; duplicates/non-Codex/persistence failure never wake; hook delivery can reply; fallback remains normal-turn-safe; a real unloaded `relaydev` wake replies through Relay without an app ping or visible window.

**Risk:** Elevated

**Complexity:** Moderate

**Reason:** The correction moves hidden process scheduling into the shared `core/relay.py` service after durable storage commits, so both HTTP and MCP callers share one decision. This expands the prior gray app-only scope and requires a refreshed pre-edit redline and clean-context review; no schema, API contract, or permission broadening is intended.

**Discovery:** The requested worktree already exists on `codex/codex-cold-wake` and has only an unrelated dirty `uv.lock`. HTTP `/relay/messages` and MCP `pallium_relay_send` both route to `RelayService.send`, which calls durable `store.relay_send`; the existing wake exists only afterward in the MCP caller and therefore misses HTTP. Replies do not wake. The current helper already uses vector argv, suppressed stdio, `CREATE_NO_WINDOW`, an exact selector, and one returned Codex delivery. The installed CLI accepts `codex exec --profile pallium-relay resume <session> - --json`; the user config already has the Pallium stdio MCP entry, but no profile file. The architect reports active-writer as stderr phrase plus code `-32600` before JSONL; feature-test and parse it strictly before reliance. Prior app-only redline was GRAY/Elevated; refreshed classification now covers the shared core path.

**Material assumptions:** The bundled Codex CLI supports the required headless `exec resume` invocation and emits a reliable active-writer signal (reported code `-32600` plus a stable stderr phrase before JSONL); feature-test and strictly classify before relying on it, otherwise stop. Existing profile/config support can require the Pallium MCP server and narrowly allow only Relay send/reply with default approval behavior; otherwise stop rather than inventing a broad approval bypass. The shared service can schedule a supervised child after `store.relay_send` returns without delaying the request, and persisted delivery metadata exposes the exact session and delivery id for in-process dedupe; otherwise stop before adding new durable state.

**Plan:** (1) Refresh redline for `core/relay.py` plus directly required app/profile paths, then obtain a clean-context review of this corrected plan. (2) Extend the existing Codex setup helper only enough to create/remove an idempotent non-default `pallium-relay` profile that reuses the actual Pallium MCP definition, requires it, retains the default approval prompt, and allows only `pallium_relay_send` and `pallium_relay_reply`; live feature-test parser compatibility first. (3) Move the exact-Codex post-persistence decision to `RelayService.send`: after `store.relay_send` returns, schedule one hidden supervised child using the persisted delivery id only for in-process dedupe. The child drains stdout/stderr, runs vector-argv `codex exec --profile pallium-relay resume <session> - --json` with the static notice on stdin, and queues once only for positively classified active-writer output; success/start, timeout, malformed output, or any other failure queue nothing. (4) Remove the MCP-only scheduling call so MCP remains a caller. (5) Add focused HTTP/shared-send and MCP caller-surface E2E for every named result, duplicate/non-Codex/persistence guard, hook/reply/fallback, no visible window, and immediate return. (6) Run the real unloaded `relaydev` no-ping wake/reply gate. Stop if the profile parser/CLI cannot provide narrow required-tool configuration or if active-writer cannot be positively identified.

**Verification plan:** Feature-test the bundled CLI/profile compatibility before implementation. HTTP and MCP callers shall both persist first and return promptly while one shared child makes each permitted simulated exec/fallback decision -> focused caller-surface E2E. When the target is unloaded, an exact persisted Relay delivery shall wake `relaydev` and yield a Relay reply without an app ping or visible window -> real dogfood gate.

**Plan review:** The app-only plan checkpoint was superseded by the architect's shared-service correction. Refresh redline and obtain a new clean-context review before guarded edits.

**Approvals:** Not required at this risk level; the user has explicitly authorized the bounded architect direction.

**Exceptions:** —

**State:** Blocked or returned to planning
<!-- agent-workflow:end -->

## Implementation

- 2026-09-01: Work Record created before code. Branch `codex/codex-cold-wake`; preserve the pre-existing `uv.lock` modification. Redline classified the original app paths GRAY/Elevated with no boundary violation; caller trace and CLI help feature check completed.
- 2026-09-01: Architect correction: wake scheduling must move from MCP into `RelayService.send` after durable persistence so HTTP and MCP share it. Returned to planning: refreshed redline and clean-context review are required before guarded edits. User asked that architect replies receive a manual session ping until the automatic wake is proven; the final no-ping dogfood gate remains manual-ping-free.
