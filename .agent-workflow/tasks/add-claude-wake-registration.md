<!-- agent-workflow:start -->
**Outcome:**
Claude `SessionStart` and `Stop` can refresh an exact session’s in-memory pipe/token registration through a loopback-only endpoint. The credential remains memory-only; an internal, test-injected fake transport can probe it without any public probe, clear, status, or secret output.

**Target:**
Pallium Relay Claude wake registration/probe foundation.

**Scope:**
One memory-only `core/claude_wake.py` registry; one narrowly scoped loopback registration route with manual bounded body parsing; dependency/app wiring; existing Claude `SessionStart`/`Stop` hooks; focused hook, lifecycle, and fake-transport E2E tests; evidence-backed design/roadmap updates. No SessionEnd, clear route, public probe, coordinator, persistence, or real pipe connection.

**Constraints:**
No persistence, DB/schema, Relay payload/audit, logs, error text, HTTP response, model context, command arguments, files, stdout, or stderr may contain a pipe path or `CLAUDE_CODE_MESSAGING_TOKEN`. The socket peer must be IPv4/IPv6 loopback; same-user local processes are trusted, and body scope is asserted rather than authenticated. Exact `claude-code` runtime and scope are required. Secret-bearing fields must bypass normal Pydantic validation so a 422 can never echo them: the route parses bounded JSON itself and returns constant, generic secret-free failures. Hooks exit 0 on every failure. Do not contact `claude-code:@relaydev`, create/replace a live session, implement the coordinator, or add dependencies. A real transport is out of scope; only injected fakes may receive credentials in tests.

**Completion criteria:**
A valid hook registration creates or atomically replaces one in-memory entry keyed by `(runtime, session_ref)`, retaining verified container/actor scope and a monotonic generation. Server-owned 900-second TTL is refreshed by `SessionStart` and by `Stop` before every existing early return. Expiry is passive fallback; service/app recreation loses entries. The internal probe snapshots under the lock, invokes only an injected fake outside it, and returns a secret-free result. Invalid input, non-loopback peers, stale expiry, restart, or transport failure yield safe unavailable/rejection with no credential disclosure.

**Risk:**
High

**Complexity:**
Moderate

**Reason:**
Pre-edit redline is RED: a route change requires `api-review`. This is a credential and local-trust boundary; High risk remains despite in-memory-only state. Moderate complexity covers lifecycle, lock correctness, hook fail-soft behavior, and end-to-end evidence.

**Discovery:**
Existing Relay session state is SQLite-backed and must not receive this secret. `api/routes.py` has a loopback peer-guard pattern; API may import `core` but not `app`. Architect review requires construction/wiring through `app.dependencies.build_router`, including `app/dependencies.py`, so separate app instances remain isolated. Claude hooks use a six-second fail-soft helper and always exit 0; installed lifecycle currently provides `SessionStart`/`Stop`, not proven `SessionEnd`. Existing installer setup already propagates those hook files. Design 017 requires a direct audited loopback credential path, a user-present disposable target for any live probe, and passive fallback. Pre-edit redline: RED API paths, GRAY core/app/hooks, no boundary violation; `api-review` required.

**Material assumptions:**
The server owns a fixed 900-second TTL; refresh at `SessionStart` and at the beginning of `Stop` keeps an active session available without adding a heartbeat. A process restart clears credentials and is an expected unavailable/fallback state. Body identity does not authenticate a same-user local caller; loopback is only a local trust boundary. A callable fake is sufficient for deterministic E2E and avoids a transport framework; production has no callable and must make no I/O. `SessionEnd` support must be proven from the installed Claude lifecycle before any later clear hook/API is proposed; this slice omits clear entirely. Any requirement for stronger local authentication, secret observability, a non-loopback peer, or a real target requires re-design.

**Plan:**
1. Add a stdlib in-memory registry keyed solely by validated `(runtime, session_ref)`, with container/actor retained and compared on access. Under one lock, atomically replace entries and increment a monotonic generation. Expiry and any future clear compare generation so stale lifecycle work cannot remove a newer registration. Recreate the registry per app instance; restart therefore loses state.
2. Add only a loopback registration endpoint. Validate socket peer for `127.0.0.1`/`::1` and reject `client=None` or non-loopback peers. Manually parse a size-bounded JSON body, reject malformed/wrong-type/empty/over-max/control-character fields using constant generic errors, and never create a secret Pydantic model, response schema, audit event, or diagnostic representation. No public probe, status, or clear endpoint.
3. Construct and inject the registry through `app.dependencies.build_router`/app wiring without breaking API-to-core dependency direction. The internal probe is a core/app seam only: snapshot a live matching generation while locked, call an injected fake after releasing the lock, and default to unavailable without opening a named pipe. This supports re-entry without deadlock and keeps production transport inactive.
4. Extend `SessionStart` to read runtime credentials directly from environment and attempt loopback registration. At the start of `Stop`, before each current missing/bad/empty/oversized transcript return, make the same best-effort refresh. Missing session/scope/credential, invalid/oversized values, connection, timeout, or HTTP failure produce no credential output and exit 0. Do not add SessionEnd or an unregister operation in this slice.
5. Verify current installer/local setup propagation is idempotent for the exact `SessionStart`/`Stop` lifecycle entries; modify installer files only if focused existing tests prove propagation is missing.
6. Add deterministic public-boundary E2E through real hook subprocess/environment -> loopback HTTP -> registry, plus internal fake-probe tests. Cover valid registration/refresh; missing session/scope/credential; malformed JSON, wrong types, empty/max/over-max; valid Unicode scope and control-character rejection; IPv4/IPv6/non-loopback/client-none; atomic replacement/project switch/stale generation; expiry/app recreation; concurrent replace/probe/expiry; callback re-entry; production transport never called; all failure paths exit 0 with no secret in response/error/log/stdout/stderr; and installer lifecycle/idempotence. If installed `SessionEnd` support is subsequently proven in a separately approved change, add only stale-generation clear coverage there.

Key conventions: reuse existing opaque/scope validation and loopback peer guard; stdlib dataclass/lock/callable only; no schema/storage migration; transport acceptance is not model admission; no live target.

Target files: `.agent-workflow/tasks/add-claude-wake-registration.md`; `core/claude_wake.py`; `api/routes.py`; `app/dependencies.py`; app wiring as required by the existing composition root; `integrations/claude-code/hooks/{common.py,session_start.py,stop.py}`; focused tests; `docs/designs/017-relay-wake-phase0.md`; `roadmap/features/add-wake-first-relay-delivery.md`; installer only if test evidence requires it. `api/schemas.py` is intentionally out of scope for secret-bearing request data.

**Verification plan:**
- When a valid hook environment registers or refreshes, the exact registry entry shall be present only in process memory and an internal fake shall receive private values without public exposure -> real hook subprocess/environment -> loopback HTTP -> registry plus injected-fake tests.
- When values are missing, malformed, wrong-typed, empty, max/over-max, control characters, scope-mismatched, remote/client-none, stale, expired, concurrently replaced, or post-restart, registration/probe shall reject or fall back without secret disclosure -> focused route/lifecycle/concurrency tests with response/error/log/stdout/stderr assertions.
- When a fake callback re-enters the registry, no lock is held across the callback and no deadlock occurs -> re-entry test; production default never calls a transport.
- When `SessionStart` or every `Stop` early-return path encounters an HTTP/connection/timeout failure, Claude remains non-blocking and exits 0 with generic output only -> hook subprocess tests.
- When the installer runs, it shall preserve idempotent `SessionStart`/`Stop` entries -> `tests/test_claude_code_integration.py`.
- When implementation is complete, API/security governance and dependency boundaries shall remain satisfied -> redline report, agent-workflow check, import linter, and architecture/API review.
- Before any live test, a user-present disposable target and separate explicit authorization shall exist -> no live test in this branch.

**Plan review:**
2026-08-28 — Clean-context architecture/API/security review from `codex:@relayarch` required: remove public probe/clear, use 900-second refresh semantics, model loopback trust accurately, manually parse secret request fields, key/generate registry state correctly, inject through `app.dependencies.build_router`, and expand exact E2E evidence. Incorporated in this revision. Guarded code remains unauthorized pending reviewed-plan acceptance and High-risk human approval.

**Approvals:**
Pending human approval after reviewed plan, required at High risk.

**Exceptions:**
—

**State:** Blocked
<!-- agent-workflow:end -->

## Checkpoint: api-review

What is changing: A loopback-only secret-registration route and app-owned in-memory registry; the internal fake probe has no HTTP surface.

Why: Existing Claude lifecycle hooks need a non-model, non-persistent refresh handoff for deterministic qualification without exposing the credential.

Affected contract / model / boundary: One secret-bearing local HTTP request parsed manually; API may depend only on core and must preserve per-app isolation. Same-user loopback callers are trusted, not cryptographically authenticated.

Compatibility / migration risk: High — secret-bearing local API boundary; no persisted schema or external network surface is added.

Verification plan: Hook subprocess/environment -> loopback HTTP -> registry, internal fake-probe lifecycle tests, negative input/peer/generation/expiry/concurrency cases, redaction assertions, hook exit-zero checks, and API/architecture review.

## Implementation

2026-08-28 — Created from synced `origin/main` `6288fb3005d74e0528656057ee8746583881b337` on `codex/add-claude-wake-registration`. Planning only. Revised after two clean-context architect reviews: fixed 900-second TTL, Start/Stop refresh, no clear/probe HTTP surface, manual secret parsing, generation-safe state, dependency injection through `app.dependencies.build_router`, and expanded E2E boundary. Next: obtain reviewed-plan acceptance and required verbatim human approval before any guarded code.