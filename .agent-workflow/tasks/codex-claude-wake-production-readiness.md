<!-- agent-workflow:start -->
**Outcome:**
Claude Relay `idle_wake` is production-ready on Windows at the qualified Codex hook-delivery reliability bar: exact-session native triggering is verified, hook admission is proven separately, send remains responsive, failures/restarts degrade to observable loss-safe persisted fallback, and a no-ping live round trip succeeds.

**Target:**
Pallium Claude Code Relay wake adapter.

**Scope:**
Claude wake scheduling, native Windows/POSIX transport protocol, exact-session registry handoff, hook-time Relay delivery/recovery, credential-free outcome logging, focused caller-surface/E2E tests, integration documentation, and the canonical wake roadmap. Primary paths: `app/claude_wake.py`, `app/claude_wake_transport.py`, `core/claude_wake.py`, `integrations/claude-code/hooks/*`, `api/routes.py`, and related tests.

**Constraints:**
Preserve persist-first delivery, fail-closed scope/session identity, one-shot verified-idle admission, bounded I/O, durable natural-turn fallback, and secret/message-content redaction. Pallium is trusted-local: loopback registration is an operational handoff, not authorization against a malicious same-user process; remote callers and cross-scope probes still fail closed. Use no wall-clock lease sleeps. Keep cold resume, busy-turn queueing, macOS/Linux qualification, Channels, turn-end notifications, and OpenCode out of this milestone. Use Relay for agent coordination; delegate implementation primarily to `codex:@relaydev` and Claude protocol/runtime validation to `claude-code:@claude_arch`, which may use its own Claude developer internally. A stale recipient registration is not proof an agent exists. Minimize expensive-model work. Preserve unrelated `uv.lock` and `.agent-workflow/.hooks.log` changes.

**Completion criteria:**
1. When Claude native activation is attempted, Pallium shall report only the bounded local transport outcome; model-visible admission shall be established by the existing hook/Relay delivered state. The exact session shall remain bound by the registered socket/pipe plus token, with deterministic accepted-write, disconnect, timeout, partial-write, malformed-input, and Unicode coverage.
2. When Relay sends to a registered Claude session, the public send path shall not wait for the native transport timeout, and duplicate/concurrent sends shall trigger at most one scope-bound idle wake.
3. Every wake attempt shall emit one credential-free structured outcome with session/delivery correlation, latency, and a bounded failure category.
4. When registration is stale, the service restarts, transport fails, or a hook crashes after claim, the delivery shall remain pending or lease-recoverable, never falsely delivered, and shall be injected and ACKed once on the next valid hook. A definitive transport failure shall restore the idle grant only for the unchanged registration generation so a later send may retry; service restart does not promise automatic cold wake. Busy deliveries remain pending until a verified idle boundary.
5. A fresh installed Windows Claude session shall complete SessionStart → busy deferral → Stop idle grant → exact native wake → attributed hook delivery → atomic Relay reply without a manual ping. Duplicate and forced-failure probes shall preserve one-shot behavior; a service-restart probe shall prove persisted fallback and once-only recovery on the next valid hook.
6. Required focused/full gates, service health probes, installed-state verification, Claude architect acceptance, Codex architect review, and PR review threads shall be clean before merge.

**Risk:**
High

**Complexity:**
Moderate

**Reason:**
The change touches a security-sensitive exact-session transport, concurrent admission state, and loss/recovery semantics across service, hooks, and runtime boundaries. Redline classification of the intended Scope paths: `api/routes.py` is a red zone → **api-review** checkpoint (agent-redline-policy.yaml); `core/claude_wake.py`, `app/claude_wake*.py` are `watch` (`core/**`, `app/**`); hooks and tests are blue. The single red path plus the security-sensitive transport and multiple outcomes requiring live Claude Code evidence hold this at High. High is correct: not lower (a red-zone api-review path is in scope), not inflated (no persistence-DDL, no `core/visibility.py`, so no persistence/security checkpoint beyond api-review).

**Discovery:**
Current `main` already persists before wake, validates pending delivery and scope, atomically consumes a one-shot idle grant, claims only at admitted hook execution, and covers deterministic D1→D2→D3 lifecycle behavior. Installed Claude Code 2.1.250 evidence shows `peer_message_status` is an out-of-band control frame sent to the incoming frame's `origin.from`; the current one-way Pallium sender has no return inbox, so a clean write is trigger evidence only and hook/Relay delivery remains the admission proof. Claude's own authenticated `type:user` debug recipe omits `session_id`, matching successful live dogfood; exact targeting is the registered socket/pipe plus token and scope-bound registry entry. Remaining verified gaps: the probe runs inline with a two-second bound, wake outcomes lack structured logs, local transport result naming overstates success, and automatic unattended recovery after crash-between-claim-and-emission is unqualified. Codex UTF-8, MCP scope guidance, multipart guidance, Windows cancellation, and the prior hook lifecycle defects are already fixed and must not be reimplemented.

**Material assumptions:**
- A local bounded transport outcome plus hook/Relay delivered state is sufficient to separate trigger from admission without a Pallium reply inbox. Disproof: Claude architect evidence shows a production-required status cannot be inferred from hook admission; action: return to planning for a bounded authenticated `origin.from` listener rather than reading the write connection.
- The registered socket/pipe, token, runtime/session registry key, and caller scope are the exact-session identity contract for ordinary user frames; no `session_id` field is required. Disproof: Claude architect live evidence shows cross-session ambiguity or receiver rejection without that field; action: widen the transport signature only then.
- A module-local coalesced background worker can preserve one-shot registry semantics: the registry consumes idle atomically at worker execution, restores it after definitive failure only when the registration generation is unchanged, and leaves it consumed after a clean trigger. Disproof: deterministic concurrency/ABA tests show loss or duplication; action: keep the probe inline and replan.
- Production readiness at the current Codex bar requires loss-safe restart/crash fallback, not automatic cold wake: persisted deliveries become lease-eligible and the next valid hook claims/ACKs once. Disproof: live or E2E evidence shows loss, false delivery, cross-scope injection, or duplicate ACK; action: fix the shared hook/Relay lifecycle in this slice.

**Plan:**
1. Claude architect performs or delegates a clean-context redline and plan review against this Work Record and relevant sources; resolve findings before code.
2. Claude architect validates the out-of-band status and socket/token exact-identity contract from Claude Code evidence. `codex:@relaydev` makes transport outcomes truthful without adding a speculative reply listener or `session_id`; stop and replan on contradictory live evidence.
3. `codex:@relaydev` adds a module-local per-session coalesced worker. The registry consumes the idle grant at worker execution and generation-safely restores it only on definitive transport failure. Add one existing-style structured outcome log and deterministic duplicate/concurrency/ABA/error regressions.
4. `codex:@relaydev` traces stale registration, service restart, transport failure, and crash-after-claim paths end to end. Qualify persisted natural-turn recovery and later-send retry without credential persistence, polling, or a general coordinator. Document the trusted-local loopback registration boundary and test remote rejection plus cross-scope fail-closed behavior.
5. Run deterministic caller-surface and lifecycle tests, then update stable integrations, restart only with `scripts/restart-service.ps1`, verify all three health surfaces, and perform the fresh-session Windows no-ping matrix.
6. Claude architect independently validates in Claude Code. Codex architect reviews the complete diff, resolves all PR threads, and merges only after green gates.

**Verification plan:**
- Native local-write/disconnect/timeout/partial/malformed/Unicode outcomes and exact socket/token identity → transport tests with deterministic fakes; hook/Relay caller-surface E2E proves admission separately; no sleeps.
- Responsive send plus one wake under duplicate/concurrent sends → real router callback and registry concurrency tests with bounded events.
- Safe observability → captured-log assertions proving correlation fields and absence of token/payload content.
- Stale/restart/failure/crash recovery → persisted Relay hook/API E2E with deterministic clock/lease control proving no false delivery, generation-safe idle restore after definitive failure, later-send retry, and once-only next-hook injection/ACK; service restart explicitly has no automatic cold-wake claim.
- Fresh installed Windows journey → Claude architect dogfood transcript plus Relay status evidence, including reply, duplicate, restart, and forced failure.
- Repository acceptance → focused suites, full required CI, `agent-workflow`/redline, `git diff --check`, supported service restart, `/health`, `/status`, `/debug/queue/health`, installed integration checks, and resolved PR review threads.

**Plan review:**
2026-09-02 clean-context re-review + independent `claude_arch` validation at `## Plan review`: clean for bounded non-protocol implementation; both reviewers concur. Claude native protocol acceptance (peer_message_status, session_id, frame grammar) and live Windows qualification remain a hard `claude_arch` gate before wire-contract changes or merge.

**Approvals:**
Approved by user 2026-09-02: "ok. so that's the current mission. persist this plan so we don't loose it. use the claude dev for most of the developemtn work. remember budget considerations. use the claude architect when you need to validate and run verifications in claude code. the architect can also use a claude dev it has"

**Exceptions:**
—

**State:** Ready to implement
<!-- agent-workflow:end -->

### Dogfood secret-boundary extension (plan-only)

**Scope amendment:** Extend this High-risk work to the shared Relay secret boundary only: redaction/__init__.py, core/relay.py, app/mcp/server.py, tests/test_redaction_tier_a_and_b.py, and tests/test_relay_mcp_tools.py. No native wake protocol, registration, hook, persistence schema, or integration-local redactor is in scope.

**Discovery amendment:** Dogfood reproduced a false positive: the benign line `session_id: socket/pipe+token+scope` is wholly scrubbed by the YAML/env rule because its prose guard treats one 12+-character technical word as credential evidence. The existing shared helper already owns Tier B entropy and known false-positive shapes. Core Relay stores the sanitized payload before setting redacted=true, but app/mcp/server.py collapses an oversized normal Relay result to delivery counts/states and omits that safe payload.

**Completion-criteria amendment:** The shared YAML/env prose guard must preserve the exact multiword dogfood line and comparable technical prose unless it contains a genuinely secret-like token under the existing entropy and known-false-positive-shape policy. True single-word and multiword credential assignments remain redacted. A redacted Relay send or reply MCP result must return the stored sanitized payload when it fits the 2,000-character budget; otherwise it must return a bounded sanitized preview plus an explicit truncation marker. No original payload or secret span may appear.

**Plan amendment:** Before any runtime edit, invoke agent-workflow for the guarded redaction extension and obtain fresh claude-code:@claude_arch review of this exact contract. Reuse the shared redaction leaf for the smallest prose guard change; do not add Relay or integration-specific rules. Then adjust only the oversized normal Relay serializer to retain the already-sanitized payload or measured safe preview, and add focused tests.

**Verification amendment:** Unit boundaries cover the exact dogfood repro, true single-word and multiword credentials, Unicode, known false-positive shapes, and idempotence. Real MCP pallium_relay_send and atomic pallium_relay_reply E2E cover the repro, true secret, Unicode, exact-fit and over-budget sanitized results, explicit truncation, and idempotent retry. Every result is measured under 2,000 characters and checked for absence of original payload and secret spans.

**Risk amendment:** This is a High-risk secret-boundary extension. Redaction is a guarded path, but current redline policy maps the dedicated security checkpoint only to core/visibility.py; architect review remains mandatory before implementation.
## Implementation

- 2026-09-02: Mission persisted before code. No runtime edits started. User corrected delegation: `codex:@relaydev` is the primary implementation developer; `claude-code:@claude_arch` owns Claude-side validation and may use its own Claude developer. A stale `@paldev` address-book entry was mistakenly treated as an available agent; its pending assignment was superseded and must not be used.
- 2026-09-02: Installed Claude 2.1.250 protocol evidence corrected the initial design before code: `peer_message_status` is sent out-of-band to `origin.from`, not returned on the write connection, and the built-in authenticated user-frame recipe omits `session_id`. The plan now treats native write as trigger evidence and hook/Relay state as admission evidence; no speculative listener or identity field is authorized.
- 2026-09-02: Clean-context review blockers resolved in planning: async failure uses generation-safe idle restoration; restart/hook-crash qualification promises persisted next-hook recovery rather than unsupported automatic cold wake; loopback registration is explicitly within Pallium's trusted-local boundary, with remote and cross-scope fail-closed tests required.

- 2026-09-02: Phase 1 implementation in progress from `fc95271a`. Intended files: `core/claude_wake.py` (generation-safe consume/restore), `app/claude_wake.py` (module-local coalesced worker and credential-free outcome log), `tests/test_claude_wake_dispatch.py` (deterministic caller/concurrency/retry/ABA/log tests), and this Work Record. Native frame/auth/socket protocol surfaces are excluded pending Claude architect acceptance.

- 2026-09-02: Phase 1 implementation completed from `fc95271a`: `core/claude_wake.py` now restores idle only after a definitive failed transport for the same generation; `app/claude_wake.py` coalesces in-flight per-session workers and logs credential-free outcomes. Native frame/auth/socket protocol was not changed.

- 2026-09-02: Phase 1 remediation in progress after review: add an actual `/relay/messages` caller-surface regression, split bounded wake outcome categories by whether transport was attempted, and make thread-start failure log/retry-safe. Structured State remains `Ready to implement` because the workflow permits no `In progress` value; this prose records the overall mission as in progress.

- 2026-09-02: Phase 2 recovery qualification completed: one caller-surface E2E uses a fresh in-memory registry over the persisted Relay store to prove no automatic cold wake/claim after restart, then the next valid `UserPromptSubmit` injects and ACKs once. It also leaves a duplicate message-id as one delivery, simulates crash-after-claim, advances the controlled lease clock, and proves the next hook redelivers/ACKs once with a harmless retry.
- 2026-09-02: Dogfood secret-boundary extension completed after architect CLEAN review: the shared YAML/env prose guard now uses the existing Tier B secret predicate with its prior 12-character assignment floor, preserving technical multiword prose while retaining true-secret redaction. Oversized Relay MCP send/reply results retain only the stored sanitized payload, adding a measured sanitized preview and truncation marker when needed. Core Relay required no change because it already persists the sanitized payload. Existing focused tests already prove remote registration rejection and cross-scope probe/claim failure.

## Evidence

- Mission memory: `d7537934-fd56-4830-8834-7bab372124d8` (supersedes the incorrect developer assignment).
- Roadmap priority: `roadmap/features/add-wake-first-relay-delivery.md`, Claude live Windows qualification first.
- Phase 1 focused verification: `uv run python -m py_compile core/claude_wake.py app/claude_wake.py tests/test_claude_wake_dispatch.py` passed.
- Phase 1 focused verification: `uv run pytest tests/test_claude_wake_dispatch.py tests/test_claude_wake_registration.py -q` passed (65 passed, 2 skipped; two pre-existing Pydantic forward-reference warnings).
- Workflow verification: `uv run python scripts/agent-workflow-check.py --repo-root . --slug codex-claude-wake-production-readiness` passed. `uv run ruff check ...` could not run because Ruff is not installed in the managed environment.

- Phase 1 review remediation: real `POST /relay/messages` returns while an Event-blocked transport remains active; tests cover `trigger_written`, `transport_failed`, `not_eligible`, `worker_error`, and `worker_start_failed` with token/socket/payload absence assertions. `uv run pytest tests/test_claude_wake_dispatch.py tests/test_claude_wake_registration.py -q` passed (68 passed, 2 skipped; three pre-existing Pydantic forward-reference warnings).
- Phase 2 focused verification: `uv run python -m py_compile tests/test_claude_wake_dispatch.py` and `uv run pytest tests/test_claude_wake_dispatch.py tests/test_claude_wake_registration.py tests/test_relay_wake_contract.py -q` passed (72 passed, 2 skipped; three pre-existing Pydantic forward-reference warnings).
- Dogfood redaction/MCP focused verification: `uv run python -m py_compile redaction/__init__.py app/mcp/server.py tests/test_redaction_tier_a_and_b.py tests/test_relay_mcp_tools.py` and `uv run pytest tests/test_redaction_tier_a_and_b.py tests/test_relay_mcp_tools.py -q` passed (98 passed; four pre-existing Pydantic forward-reference warnings). The tests cover the technical-prose repro, the 17-character assignment floor, true secrets, Unicode, sanitized reply output, bounded truncation, and redaction idempotence. `uv run python scripts/agent-workflow-check.py --repo-root . --slug codex-claude-wake-production-readiness` and `git diff --check` passed.

## Plan review

2026-09-02 — `codex:@relaydev` clean-context re-review of `f378b6f2` against the Work Record, wake registry/callback/restart sources, and focused lifecycle tests.

**Verdict: clean for bounded non-protocol implementation; State is Ready to implement.** Risk remains **High / Moderate** and the recorded human approval remains applicable.

1. **Worker-time one-shot/ABA recovery: resolved in plan.** The worker, rather than the caller, atomically consumes idle; definitive failure restores only the unchanged registration generation. Deterministic duplicate, concurrent, and ABA checks are explicitly required. A process/worker loss falls back to the persisted delivery rather than claiming a fabricated retry.
2. **Restart and post-claim recovery: resolved in plan.** The completion criteria now promise only persisted pending/lease recovery on the next valid hook, never automatic cold wake after an in-memory registry restart. The existing hook/Relay lifecycle is the observable recovery path and its once-only E2E is required.
3. **Exact identity: resolved for the declared threat model.** Loopback handoff is explicitly trusted-local; remote registration and cross-scope probe failures remain required tests. This does not claim protection from a malicious same-user local process.
4. **`peer_message_status` and wire identity: still gated, not blocking Phase 1.** Native write remains trigger evidence only. Do not alter auth/frame grammar, socket read behavior, or add `session_id`/a reply listener until `claude-code:@claude_arch` reproduces the installed-version contract. Contradictory Claude evidence returns this task to planning.
5. **Observable coverage: resolved in plan.** The caller-surface, generation-safe retry, restart fallback, claimed-hook lease, and exactly-once next-hook ACK scenarios have explicit deterministic E2E requirements; the existing D1→D3 test is only their baseline.

**Implementation boundary:** Phase 1 may change only the registry/worker dispatch, non-secret outcome logging, and deterministic tests without changing the native wire protocol. Claude architect acceptance remains required before protocol-surface work, live qualification, or merge.

2026-09-02 — `claude-code:@claude_arch` independent validation of the above review (read-only, against current code, no delegation — clean-context reviewer was lost to a spend cap so this is a direct source audit).

**Verdict: I concur — Ready to implement is justified for bounded non-protocol Phase 1; native protocol acceptance is correctly gated to me.** Validated each reconciled point against source:
- Redline: `api/routes.py` in Scope is red → **api-review** (agent-redline-policy.yaml L55-57); `core/**`, `app/**` watch; hooks/tests blue. Risk **High** correct — a red api path is in scope; no persistence-DDL or `core/visibility.py`, so no checkpoint beyond api-review. (Reason field updated to record this.)
- Assumption 1 (status): CONFIRMED reframe. `app/claude_wake_transport.py` L55/L108 sets `"from":"pallium-relay"` — not a shaped Pallium inbox — and the write connection is never read (L57/L106 send-only). Out-of-band status is unreadable here; native write is trigger-only, hook/Relay `delivered` is admission. No speculative listener authorized. Correct.
- Assumption 2 (session_id): CONFIRMED. Frame omits `session_id`; installed debug recipe omits it; exact target is socket/pipe+token+scope registry key. Widen the signature only on live receiver rejection. Correct.
- Assumption 3 (one-shot/ABA): CONFIRMED SUPPORTED by existing code. `ClaudeWakeRegistry.probe` consumes `idle=False` atomically under `self._lock` before the transport call (`core/claude_wake.py` L128-137); `generation` (L30, L97) backs generation-safe restore. Moving the transport call to a module-local worker preserves this as long as the lock-guarded consume stays at worker execution. Deterministic duplicate/concurrent/ABA tests required — agreed.
- Assumption 4 (restart/crash): CONFIRMED honestly UNKNOWN → correctly scoped to persisted next-hook recovery, not automatic cold wake. Hooks (`session_start`/`user_prompt_submit` register idle=False; `stop` registers idle=True; `acknowledge_relay` ACKs) show only natural-turn recovery; no lease-expiry observer exists. No general coordinator — agreed.

**No blocking findings.** Two validator notes for relaydev (non-blocking): (a) keep the idle-consume synchronous inside the worker (not the caller) so the lock still serializes it — if the consume ever moves off-lock the one-shot guarantee breaks; (b) the structured outcome log must not log `socket_path` or `token` (both `repr=False` in `_Registration`, keep it that way). Protocol/session_id/frame-grammar changes and live Windows qualification remain a hard `claude_arch` gate before merge.

2026-09-02 — `claude-code:@claude_arch` independent review of the `c4a11b64` Dogfood secret-boundary extension (plan-only contract, WR-only, no runtime code read as authorization).

**Verdict: CLEAN — relaydev may implement the bounded redaction fix.** Verified all three code claims the contract rests on against current source:
- Claim 1 (shared leaf owns Tier B entropy + known-FP shapes): CONFIRMED in `redaction/__init__.py` — entropy heuristic and shape guards live there. Reusing that leaf for the smallest prose-guard change is correct; no Relay/integration-specific rule needed.
- Claim 2 (core Relay stores the sanitized payload before setting `redacted=true`): CONFIRMED in `core/relay.py` — `send`/`reply` compute `stored_payload = redact_sensitive(raw_payload)`, persist `payload=stored_payload`, then set `redacted = stored_payload != raw_payload`. The safe payload already exists to return.
- Claim 3 (oversized normal Relay result drops the safe payload): CONFIRMED in `app/mcp/server.py::_relay_text` — for an oversized deliveries dict it summarizes to `message_id/recipient/redacted/in_reply_to/created_at/expires_at + delivery_count + delivery_states` and omits `payload`. This is the exact regression the fix targets.

**Scope, criteria, risk all well-formed.** Five files, no protocol/hook/schema. Risk correctly held High. Redline caveat accurate — security-review maps only to `core/visibility.py`, so architect review (this) is the real gate.

**Two implementation constraints (binding, not blocking):** (a) return only the already-sanitized `stored_payload`, never the raw payload — if ≤2000 chars return it, else a bounded preview + explicit truncation marker; (b) the fix must not weaken Tier A/B on the store path — the prose-guard relaxation preserves multiword technical lines only when they carry no genuine secret span. Tests must assert both the preserved-payload path and that a real secret still redacts.

## Result review

Pending.
