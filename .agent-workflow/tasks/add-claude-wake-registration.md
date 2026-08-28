<!-- agent-workflow:start -->
**Outcome:**
Claude `SessionStart`/`Stop` hooks can register and clear an exact session’s pipe/token only through a loopback-only, memory-only registry; an internal probe is deterministically testable with a fake transport and never exposes the secret.

**Target:**
Pallium Relay Claude wake registration/probe foundation.

**Scope:**
A new in-memory `core/claude_wake.py`; narrowly scoped Relay API schemas/routes and app wiring; existing Claude hook helpers plus `SessionStart`/`Stop`; focused E2E/hook/installer tests; evidence-backed design and roadmap updates.

**Constraints:**
No persistence, DB/schema, Relay payload/audit, logs, error text, API response, model context, command arguments, or file may contain a pipe path or `CLAUDE_CODE_MESSAGING_TOKEN`. Loopback-only route; exact `claude-code` identity/scope required. Do not contact `claude-code:@relaydev`, create/replace a live session, implement the wake coordinator, or add dependencies. Hooks must exit 0 on all failures. A real transport is out of scope; tests use a fake callable only.

**Completion criteria:**
When a valid Claude hook registration reaches the loopback surface, the registry shall hold only an in-memory exact-scope entry until replace, clear, expiry, or service restart; probe shall invoke only an injected fake transport and return no secret. Invalid/remote/expired/closed requests shall yield safe unavailable/rejection without secret disclosure, proven through hook→HTTP→registry/probe and lifecycle E2E tests.

**Risk:**
High

**Complexity:**
Moderate

**Reason:**
Pre-edit redline is RED: public API route/schema changes require `api-review`. The slice handles a runtime credential and loopback trust boundary, so risk is raised to High despite no persistence; Moderate complexity covers registry lifecycle, hook failure semantics, concurrency, and E2E coverage.

**Discovery:**
Existing Relay session state is SQLite-backed and must not receive this secret. `api/routes.py` already has a loopback client-host guard pattern; `api` may import `core` but not `app`, so the registry belongs in a new core module and is constructed in `app/main.py`. Claude hooks already use a six-second fail-soft HTTP helper and always exit 0; existing `SessionStart` and `Stop` installation entries are propagated by `app/cli/setup_claude_code.py`. Design 017 requires a direct audited loopback-only credential path, a user-present disposable target for any live probe, and passive fallback. Pre-edit redline: RED API paths, GRAY core/app/hooks, no boundary violation; `api-review` required.

**Material assumptions:**
A new core registry can remain process-memory-only across service restart; any restart necessarily clears credentials and returns `unavailable`/fallback. A callable transport seam is enough for deterministic E2E and avoids introducing a one-implementation interface; the production default must not open a real pipe in this slice. The TTL must be explicitly approved because current Claude hooks have no heartbeat; without an approved bounded value, implementation remains blocked. Any need to expose a secret for observability or to use a non-loopback requester invalidates this plan and requires re-design.

**Plan:**
1. Add a core in-memory registry keyed by validated `(runtime, container_ref, actor_ref, session_ref)`, guarded by a lock. Registration validates exact Claude identity, bounded non-empty pipe/token inputs, and approved TTL; replace is idempotent/atomic; lookup purges expiry; clear/unregister is idempotent; service recreation loses all entries.
2. Add loopback-only registration, clear, and bounded probe API operations. Schemas accept secrets only in request bodies; handlers never serialize, log, include in errors, or persist them. Require `Request.client.host` to be `127.0.0.1`/`::1`; return secret-free status/outcome only.
3. Wire the registry in `app/main.py` and keep API→core imports within the existing boundary. Probe invokes a constructor-injected callable only after exact active registration; the default reports unavailable and does not contact a real named pipe. The test app injects a fake callable to assert authentication/send inputs without exposing them through public output.
4. Extend Claude `SessionStart` to read the runtime-provided credentials directly from environment and POST only to the loopback registration endpoint; extend `Stop` to clear the exact registration. Missing/invalid/oversized environment values, HTTP failure, or timeout are silent fail-soft hook outcomes (stderr is generic/redacted and process exits 0).
5. Verify installer/local propagation continues to register the same `SessionStart`/`Stop` hook files; change installer only if existing setup tests show propagation is incomplete.
6. Add public-surface E2E: hook→HTTP→registry→fake probe; identity mismatch, loopback rejection, replacement/idempotency, TTL/expiry, close/unregister, concurrent updates, restart loss/unavailable fallback, response/error/log redaction, and lifecycle create→replace→expire/clear. Keep all live target testing outside this branch; update design 017 and roadmap with the exact boundary and fallback.

Key conventions: reuse Relay opaque/scope validation and existing loopback guard; use stdlib dataclass/lock/callable only; no schema/storage migration; probe transport acceptance is not model admission; no live target.

Target files: `.agent-workflow/tasks/add-claude-wake-registration.md`; `core/claude_wake.py`; `api/schemas.py`; `api/routes.py`; `app/main.py`; `integrations/claude-code/hooks/{common.py,session_start.py,stop.py}`; focused tests; `docs/designs/017-relay-wake-phase0.md`; `roadmap/features/add-wake-first-relay-delivery.md`; installer only if test evidence requires it.

**Verification plan:**
- When valid hook credentials register, the registry shall expose only secret-free status and a fake probe shall receive the private values -> hook→HTTP→registry/probe E2E with fake callable.
- When input is missing, invalid, oversized, remote, expired, closed, replaced, concurrent, or post-restart, the route/probe shall reject or return unavailable without a secret -> focused public API/lifecycle E2E plus response/log assertions.
- When SessionStart/Stop fails or times out, Claude shall keep its host turn non-blocking and exit 0 -> hook subprocess tests.
- When the installer runs, it shall still propagate the exact SessionStart/Stop hook files -> `tests/test_claude_code_integration.py`.
- When implementation is complete, API/security governance and dependency boundaries shall remain satisfied -> redline report, agent-workflow check, import linter, and architecture/API review.
- Before any live test, the user-present disposable target and separate explicit authorization shall be present -> no live test in this branch.

**Plan review:**
Pending clean-context architecture/API/security review via `codex:@relayarch`; no guarded edit is authorized yet.

**Approvals:**
Pending human approval after reviewed plan, required at High risk.

**Exceptions:**
—

**State:** Blocked
<!-- agent-workflow:end -->

## Checkpoint: api-review

What is changing: Loopback-only registration, clear, and probe endpoints for a memory-only Claude session credential registry.

Why: The existing hooks need a non-model, non-persistent handoff to support deterministic qualification without exposing the credential.

Affected contract / model / boundary: HTTP request/response schemas and route behavior; API may depend only on core, and all callers must be loopback.

Compatibility / migration risk: High — this is a secret-bearing local API boundary, although no persisted schema or external network surface is added.

Verification plan: Public hook→HTTP→registry/fake-probe lifecycle E2E, negative loopback/identity/expiry/concurrency cases, redaction assertions, hook exit-zero checks, and API/architecture review.

## Implementation

2026-08-28 — Created from synced `origin/main` `6288fb3005d74e0528656057ee8746583881b337` on `codex/add-claude-wake-registration`. Planning only. Next: obtain clean-context architecture/API/security review, an approved TTL, and required human approval before touching guarded code.
