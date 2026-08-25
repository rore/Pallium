# Agent Relay R1 — explicit runtime and session relay

Branch: `codex/agent-relay-r1`

<!-- agent-workflow:start -->
**Outcome:**
Claude Code, Codex, and OpenCode agents can explicitly send a bounded message to one registered peer session or all eligible sessions of a named runtime in the same Pallium container, and each recipient receives the attributed message at its next natural turn without semantic-memory involvement.

**Target:**
Pallium repository and its bundled Claude Code, Codex, and OpenCode integrations.

**Scope:**
Add isolated Relay domain and SQLite state; session registration, discovery, alias transfer, send, status, combined turn registration/claim, close, and acknowledgement HTTP/MCP surfaces; next-turn delivery in all three integrations; concise agent guidance; exhaustive public-surface E2E coverage; and roadmap/docs alignment.

**Constraints:**
Relay remains separate from source items, memory, retrieval, embeddings, ranking, and LLM routing. Routing uses only canonical container, claimed actor, fixed runtime, and an explicit runtime/exact-session/alias selector; never title, semantic similarity, or `work_ref`. Runtime sends snapshot current eligible sessions. No spawning, assignment, wake-up, autonomous conversation, arbitrary groups, cross-user trust claim, or live-delivery dependency. Hooks remain fail-open.

**Completion criteria:**
An agent using shipped MCP guidance can discover recipients, name/transfer an alias, send Unicode text, inspect status, and reply through another linked send. Broadcast creates independent delivery rows for currently recent matching sessions; exact ID and alias target one immutable session; queued messages stay pinned across alias transfer; later sessions do not inherit a broadcast. All three runtimes use one bounded register-and-claim call at a model-bound turn, inject an attributed peer block in normal hook/plugin output, and acknowledge only after output emission/mutation succeeds. Public-surface E2E proves routing, lifecycle, lease recovery, expiry, duplicate-safe acknowledgement, scope isolation, bounds, latency, storage unavailability, and zero memory/retrieval side effects.

**Risk:**
High

**Complexity:**
Large

**Reason:**
The change adds schema-as-code persistence and HTTP contracts and crosses three runtime delivery units. Redline requires persistence-review and api-review. The plan avoids `core/service.py`; `core/relay.py` receives explicit trust-boundary review despite the current policy classifying a new core file gray/watch rather than security-red.

**Discovery:**
R0 established Claude Code `UserPromptSubmit`, Codex `UserPromptSubmit`/`additionalContext`, and OpenCode system transform as supported pre-model boundaries. Existing hooks are self-contained and fail open; OpenCode''s queue is process-local, so durable state stays server-side. API may import only core; storage may not import app or add capabilities coupling. SQLite already has retry and `BEGIN IMMEDIATE` patterns. Claude/Codex lack reliable session-end events. Existing hook HTTP calls can wait six seconds inside an eight-second harness deadline, so Relay needs a separate short deadline.

**Material assumptions:**
- Broadcast snapshots non-closed sessions seen within 24 hours. Exact ID/alias may target a registered dormant session, never a closed one.
- R1 retains session rows but hides dormant/closed rows by default. Purge waits for observed scale or UX pain.
- Fixed bounds: runtimes `claude-code|codex|opencode`; 1,500 Unicode code points per message; 24-hour default expiry, accepted 60 seconds–7 days; 25 broadcast recipients; at most 3 complete messages within a 2,000-character Relay turn budget.
- Alias uniqueness is `(container_ref, runtime, alias)`; `replace_existing` affects future sends only. Titles are metadata only.
- Every operation requires nonblank canonical container and claimed actor equality. This is local scoping, not authenticated cross-user authorization.
- Payloads use the existing generic secret redactor before persistence and report whether redaction occurred.
- Close atomically marks the session closed and releases its alias. Pinned deliveries remain unclaimable until expiry or re-registration; re-registration reactivates without restoring the alias.
- `in_reply_to` must exist in the same container/actor scope. Replies to expired messages are allowed; chains have no stored conversation state and only immediate parent IDs.
- IDs/aliases/actors are nonblank, bounded, and reject ASCII controls; session IDs remain otherwise opaque. Payload accepts multiline/astral Unicode but rejects NUL/unsafe controls.
- Delivery means successful context emission/mutation, not reading or downstream use.

**Key conventions:**
- HTTP endpoints: `POST /relay/turn` (atomic refresh/reactivate + bounded claim), `POST /relay/sessions/close`, `GET /relay/sessions`, `POST /relay/sessions/name`, `POST /relay/messages`, `GET /relay/messages/{message_id}`, and `POST /relay/deliveries/ack`.
- HTTP 422 for validation; uniform non-enumerating 404 for unknown/cross-scope entities; 409 for alias/state/stale-claim conflicts and zero-recipient broadcast (with no message row); 501 when storage lacks Relay. Success returns stable IDs and public state.
- Turn returns one claim token per delivery. Ack with the same delivered token is idempotent; stale/different tokens conflict. Lease expiry creates a new claim token; message expiry prevents claim.
- Claude/Codex skip empty, slash, duplicate, and Codex-clear events before claim. All other model-bound prompts, including short prompts, call Relay before the memory length gate. Relay timeout is 750 ms and ack timeout 500 ms. Relay renders first; memory gets the remainder of one 4,000-character combined budget, capped at its existing 2,400 characters. Messages are never truncated.
- OpenCode claims only in `experimental.chat.system.transform` after confirming mutable `output.system`, mutates context, then acknowledges. `chat.message` only supplies/pins scope. `session.deleted` closes best-effort.
- `core/relay.py` holds validation/models/`RelayService` over a narrow structural store contract. `app/dependencies.py` constructs it only when storage exposes Relay; other backends still construct and Relay routes alone return 501.

**Plan:**
1. Invoke the `/agent-workflow` skill to create the Work Record and classify risk, before any code edit.
2. Add the minimal contract in `core/relay.py`; reuse `core.container_ref` and `redaction.redact_sensitive`; keep `PalliumService` unchanged and add no broker/configuration.
3. Add `relay_sessions`, `relay_messages`, and `relay_deliveries` in `storage/sqlite_schema.py`, a `storage/sqlite_relay.py` mixin, and composition in `storage/sqlite.py`. Reuse retry/`BEGIN IMMEDIATE`; do not change `StorageProvider`.
4. Extend `api/schemas.py`, `api/routes.py`, and `app/dependencies.py` with the exact optional service/endpoints/errors. Add `pallium_relay_recipients`, `pallium_relay_name`, `pallium_relay_send`, and `pallium_relay_status` in `app/mcp/{client,server}.py`.
5. Extend Claude/Codex `hooks/{common,user_prompt_submit}.py` and OpenCode `plugins/{pallium-common,pallium}.mjs` with the exact ordering/deadlines/budget. Touch session-start/setup only if proven necessary. Update the three bundled Pallium skills with compact discovery/name/send/reply rules; broadcast requires explicit user intent.
6. Add one focused Relay E2E module plus minimal runtime tests driving real HTTP/MCP and actual hook/plugin entrypoints without LLMs. Cover all input bounds, astral Unicode/control input, selectors/scope/state errors, 0/25/26 fan-out, alias transfer, snapshot membership, exact chain length 3, concurrent claims, three lease cycles, expiry combinations, tokens/ack, timeout/failure, combined budgets, non-Relay storage, and create→close/reactivate lifecycles. Assert public status and no memory/retrieval/provider side effects.
7. Run focused Python/Node suites, import/redline/workflow checks, and full regression. Smoke rendered attribution in installed runtimes where possible; if human-visible presentation cannot be demonstrated, keep R1 incomplete. Update roadmap/docs only to verified results and stop before R2.

**Verification plan:**
- Routing/identity → HTTP/MCP E2E for exact, alias/transfer, broadcast snapshot, later session, cross-container/actor/runtime isolation, and status.
- Durability → concurrent public claims, three-cycle lease recovery, stable IDs, stale-token conflict, idempotent ack, every expiry state, and independent broadcast ack.
- Boundaries/lifecycle → empty/exact/over, multiline/astral/control, invalid enum/entity/state, 0/25/26 fan-out, chain length 3, create→claim→reclaim→ack, create→claim→expire, and close→blocked claim→reactivate/alias release.
- Runtime UX/safety → actual Claude/Codex subprocess hooks and OpenCode events/transforms: short/slash/duplicate/clear ordering, mutable/missing system arrays, print/mutation-before-ack, ack-failure redelivery, daemon failure under harness deadline, attribution/reply metadata, and deterministic Relay-first 4,000-character budget.
- Compatibility/separation → non-Relay fake storage constructs normally and returns 501 only for Relay; Relay creates no source items, memory objects, lookup/audit events, embeddings, processing rows, or provider calls.
- Governance/regression → focused suites, OpenCode Node suite, full pytest, `git diff --check`, import/redline report, and workflow checker for `codex-agent-relay-r1`.

**Plan review:**
Initial clean-context review withheld approval on endpoint/file contracts, hook timing/order, non-SQLite compatibility, trust-boundary validation, close/reactivation, exact lifecycle/Unicode coverage, and combined budgets. Corrected; focused clean-context re-review returned APPROVED with no blocking corrections.

**Approvals:**
Pending reviewed-plan approval.

**Exceptions:**
—

**State:** Blocked
<!-- agent-workflow:end -->

## Plan review

Initial review returned WITHHOLD with seven blockers. The revision adds exact endpoints/files/errors; bounded turn/ack deadlines; model-bound ordering; optional capability/501 behavior; control-safe scope; close/reactivation/alias release; exact chain/astral/lifecycle coverage; and a deterministic combined context budget. Focused clean-context re-review returned APPROVED with no blocking corrections.

## Implementation

Not started; guarded edits wait for reviewed-plan approval.

## Evidence

R0 baselines: 100 Python hook/integration tests and 36 OpenCode plugin tests passed before R1 planning. `apply_patch` later hit documented Windows error 1385; this Work Record revision used one narrow deterministic replacement.

## Result review

Pending.
