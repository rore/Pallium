# Agent Relay R1 — explicit runtime and session relay

Branch: `codex/agent-relay-r1`

<!-- agent-workflow:start -->
**Outcome:**
Claude Code, Codex, and OpenCode agents can explicitly send a bounded message to one registered peer session or all eligible sessions of a named runtime in the same Pallium container, and each recipient receives the attributed message at its next natural turn without semantic-memory involvement.

**Target:**
Pallium repository and its bundled Claude Code, Codex, and OpenCode integrations.

**Scope:**
Add isolated Relay domain and SQLite state; session registration, discovery, alias transfer, send, status, claim, and acknowledgement HTTP/MCP surfaces; next-turn delivery in all three integrations; concise agent guidance; exhaustive public-surface E2E coverage; and roadmap/docs alignment.

**Constraints:**
Relay must remain separate from source items, memory, retrieval, embeddings, ranking, and LLM routing. Routing uses only canonical container, claimed actor, fixed runtime, and an explicit runtime/exact-session/alias selector; never title, semantic similarity, or `work_ref`. Runtime-wide sends snapshot currently eligible sessions. No spawning, assignment, wake-up, autonomous conversation, arbitrary groups, cross-user trust claim, or live-delivery dependency. Preserve hook fail-open behavior and existing memory context budgets.

**Completion criteria:**
An agent using the shipped MCP guidance can discover recipients, optionally assign or explicitly transfer a runtime-scoped alias, send Unicode text, inspect status, and reply by sending another linked message. Runtime broadcast creates independent delivery rows for all currently recent matching sessions; exact ID and alias target one immutable session; queued messages remain pinned across alias transfer; later-created sessions do not inherit a broadcast. Claude Code, Codex, and OpenCode register and claim at their supported turn boundary, inject an attributed peer block visible in their normal hook/plugin output, and acknowledge only successful injection. Lease recovery, expiry, duplicate-safe acknowledgement, scope isolation, bounds, lifecycle, failures, and zero memory/retrieval side effects are proven through caller-surface E2E tests.

**Risk:**
High

**Complexity:**
Large

**Reason:**
The change adds schema-as-code persistence and HTTP contracts and crosses three runtime delivery units. Redline requires persistence-review and api-review; using the existing service boundary also requires architecture-review.

**Discovery:**
R0 established supported pre-model boundaries: Claude Code `UserPromptSubmit`, Codex `UserPromptSubmit` with `additionalContext`, and OpenCode `chat.message` plus system transform. The repository has no Relay implementation. Existing hooks are intentionally self-contained and fail open; OpenCode's queue is process-local, so durable state must remain server-side. API routes may import only core; storage may not import app or add capabilities coupling. Existing SQLite retry and `BEGIN IMMEDIATE` patterns can be reused. Mutable harness titles are not safe routing identities. Claude and Codex lack a reliable session-end event, so permanent deletion cannot be inferred.

**Material assumptions:**
- Runtime-wide delivery snapshots sessions seen within the preceding 24 hours and not explicitly closed; disprove with real use showing legitimate recipients are routinely older, then change the single constant based on measurements.
- Exact ID and alias sends may target a registered dormant session but never a closed one; disprove if dormant mailboxes create meaningful stale noise, then restrict them without changing immutable delivery identity.
- Session rows may accumulate in R1 but default discovery hides dormant/closed rows; explicit close and re-registration handle lifecycle. Add purge only after observed scale or UX pain, not speculatively.
- Fixed R1 bounds are sufficient: runtime enum `claude-code|codex|opencode`, 2,000 Unicode characters per message, 24-hour default expiry with a 60-second to 7-day accepted range, 25 broadcast recipients, and 3 claimed messages per turn. Disprove through real use metrics, then revise constants rather than add configuration prematurely.
- Alias uniqueness is `(container_ref, runtime, alias)`; explicit `replace_existing` transfers it for future sends while existing deliveries stay pinned. Duplicate harness titles remain harmless metadata.
- Claimed actor equality is required for registration, discovery, sending, and delivery inside a container. This is local scoping, not authenticated cross-user authorization; evidence of multi-user use stops R1 expansion pending an auth contract.
- Payloads pass through the existing generic secret redactor before persistence and report that redaction occurred. If users require exact secret-bearing transport, that is a separate explicit security decision.
- Delivery means successful hook/plugin context injection, not reading or downstream use; true read receipts remain out of scope.

**Plan:**
1. Invoke the `/agent-workflow` skill to create the Work Record and classify risk, before any code edit.
2. Define the smallest Relay contract in `core/relay.py` and expose it through the existing `PalliumService`: opaque immutable session IDs; fixed runtime/selector grammar; bounded/redacted message input; alias transfer; snapshot fan-out; linked replies; stable message/delivery/claim IDs; and explicit errors. Avoid generalized ports, brokers, managers, or configuration.
3. Add three SQLite tables (`relay_sessions`, `relay_messages`, `relay_deliveries`) and the minimum indexes/constraints. Reuse the current retry and `BEGIN IMMEDIATE` patterns for atomic selector resolution, independent fan-out rows, lease claim/reclaim, expiry, stale-token rejection, and idempotent acknowledgement. Keep records outside all memory tables and processing queues.
4. Add thin Pydantic/HTTP endpoints for register/close/list/name, send/status, claim, and acknowledge; add four agent-facing MCP tools: `pallium_relay_recipients`, `pallium_relay_name`, `pallium_relay_send`, and `pallium_relay_status`. Received blocks expose peer provenance, message ID, timestamp, and reply ID and clearly have lower authority than user instructions.
5. Extend the existing self-contained Claude/Codex hooks and OpenCode plugin to refresh registration, claim before memory short-prompt gates, inject at the R0 boundary, and acknowledge after successful output mutation. Inject a compact Relay scope marker so agents can send/reply; guidance permits proactive exact/alias sends for concrete findings and requires explicit user intent for runtime-wide broadcast.
6. Add one focused Relay E2E module plus minimal runtime tests that drive real HTTP/MCP and actual hook/plugin entrypoints without external LLMs. Cover empty/exact/over bounds, Unicode/control input, invalid selectors/enums/entities/state/scope, zero and max/over-max fan-out, alias conflict/transfer, registration/reactivation/close, snapshot membership, reply chains over two, concurrent claims, lease recovery, expiry combinations, wrong/stale tokens, repeated ack, daemon failure, and create-to-close lifecycle. Assert observable status plus no source-item, retrieval-audit, embedding, or processing side effects.
7. Run focused Python and Node suites, import/redline/workflow checks, then the full regression suite. Perform a three-runtime local smoke of the rendered/injected attribution where installed harnesses permit it; if human-visible presentation cannot be demonstrated, keep R1 incomplete and report the adapter gap. Update roadmap/docs only to the verified result, obtain clean-context result review, and stop before any R2 capability.

**Verification plan:**
- Deterministic routing and immutable identity → HTTP/MCP E2E for exact, alias, transfer, broadcast snapshot, later session, cross-container/actor/runtime isolation, and status readback.
- Safe durable delivery → concurrent public claim tests, lease expiry and three-cycle recovery, stable IDs, stale-token conflict, idempotent ack, message expiry in every state, and independent broadcast acknowledgements.
- Complete input/lifecycle contract → caller-surface empty/max/over-max, Unicode/control, invalid enum/entity/state, zero/max fan-out, register/reactivate/close, linked reply chain, and full create-to-close tests.
- Runtime UX → actual Claude and Codex hook entrypoint subprocess tests and OpenCode plugin event/transform tests, with attributed blocks, reply metadata, one-delivery behavior, bounded context, and fail-open daemon errors; local installed-harness smoke where possible.
- Separation invariant → E2E assertions that Relay creates no source items, memory objects, lookup/audit events, embeddings, or semantic-processing rows and invokes no provider.
- Regression/governance → focused Relay and integration suites, OpenCode Node suite, full pytest, `git diff --check`, import-linter/redline report, and `agent-workflow-check` for `codex-agent-relay-r1`.

**Plan review:**
Pending clean-context review.

**Approvals:**
Pending reviewed-plan approval.

**Exceptions:**
—

**State:** Blocked
<!-- agent-workflow:end -->

## Plan review

Pending.

## Implementation

Not started; guarded edits wait for reviewed-plan approval.

## Evidence

R0 integration baselines: 100 Python hook/integration tests and 36 OpenCode plugin tests passed before R1 planning.

## Result review

Pending.
