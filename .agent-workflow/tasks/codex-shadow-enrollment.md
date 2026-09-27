# Codex shadow-only native enrollment

Canonical feature: `roadmap/features/add-wake-first-relay-delivery.md` (umbrella remains queued). Owner: relay-dev. Implementation starts from shipped `4d75328ed7d418cfb9556c86bff2ec8cd4ab1d5f`; no private experiment history is imported.

<!-- agent-workflow:start -->
**Outcome:** An explicitly enabled trusted Codex MCP child can enroll one approved pair for finite authenticated shadow observation without any delivery effect.

**Target:** Pallium Windows Codex integration.

**Scope:** app/codex_bridge_pipe.py, app/cli/setup_codex.py, app/main.py, app/mcp/server.py, app/mcp/codex_desktop_bridge.py, storage/sqlite_relay.py; tests/test_codex_bridge_pipe.py, tests/test_relay_shadow_snapshot.py, tests/test_codex_mcp_desktop_bridge.py, tests/test_codex_integration.py; docs/designs/codex-mcp-desktop-bridge.md, docs/codex-integration.md, and this Work Record.

**Constraints:** Shadow-only, off by default; no Desktop/native wake, payload fetch, claim/ACK, delivery/reservation/settings mutation, schema/grant persistence, new mandatory dependency, separate runtime or live configuration/activation. Preserve normal/off/inert/HTTP behavior and scope/TTL/retry contracts. Trusted enrolled component assertion is not Desktop attestation or malicious-same-user/administrator/SYSTEM isolation.

**Completion criteria:** When an approved actual metadata request enrolls over the protected native channel, only its exact pair has a finite process-local lease; invalid policy/peer/metadata/replay/lifecycle input denies. Close/revoke/expiry/EOF/stop/restart discards authority. Read-only observations respect deadlines and disclose no payload or private handles. Actual native and MCP caller tests cover boundaries, faults and lifecycle while ordinary tools remain live and delivery effects stay zero.

**Requirement baseline:**
{"source":"work-record-initial","outcome":"An explicitly enabled trusted Codex MCP child can enroll one approved pair for finite authenticated shadow observation without any delivery effect.","scope":"app/codex_bridge_pipe.py, app/cli/setup_codex.py, app/main.py, app/mcp/server.py, app/mcp/codex_desktop_bridge.py, storage/sqlite_relay.py; tests/test_codex_bridge_pipe.py, tests/test_relay_shadow_snapshot.py, tests/test_codex_mcp_desktop_bridge.py, tests/test_codex_integration.py; docs/designs/codex-mcp-desktop-bridge.md, docs/codex-integration.md, and this Work Record.","constraints":"Shadow-only, off by default; no Desktop/native wake, payload fetch, claim/ACK, delivery/reservation/settings mutation, schema/grant persistence, new mandatory dependency, separate runtime or live configuration/activation. Preserve normal/off/inert/HTTP behavior and scope/TTL/retry contracts. Trusted enrolled component assertion is not Desktop attestation or malicious-same-user/administrator/SYSTEM isolation.","completion_criteria":"When an approved actual metadata request enrolls over the protected native channel, only its exact pair has a finite process-local lease; invalid policy/peer/metadata/replay/lifecycle input denies. Close/revoke/expiry/EOF/stop/restart discards authority. Read-only observations respect deadlines and disclose no payload or private handles. Actual native and MCP caller tests cover boundaries, faults and lifecycle while ordinary tools remain live and delivery effects stay zero."}

**Risk:** High

**Complexity:** Moderate

**Reason:** Security-sensitive native authentication/provisioning and additive opt-in MCP surface; Redline API/persistence checkpoints apply to server and read-only Relay reader. No persistence migration or protected behavioral requirement change.

**Discovery:** Shipped inert bridge is isolated in Codex stdio lifespan. Existing setup env/env_vars already support scoped mode configuration. HTTP is trusted-local/plain; installed pywin32 supplies native ACL/peer APIs, with first-instance flag/CancelIoEx not exposed in win32file. Existing SQLite sessions wait fifteen seconds, unsuitable for a three-second shadow exchange. Native transport completion-before-free and daemon bounded-stop patterns exist in Claude runtime code.

**Material assumptions:** Supported Windows environment has required already-installed native APIs and ACL-protected local filesystem; absence disables shadow. Actual current metadata must match separately provisioned exact-pair policy; missing/conflicting metadata denies. One owner-lock/serial worker owns transient state; concurrency or cancellation uncertainty never authorizes new work. Bounded SQLite snapshot is evidence, not external-action admission. Zero-child bootstrap and actual Desktop child lifetime remain unqualified.

**Plan:** Invoke Agent Workflow and classify before code. Reuse the free managed checkout on a fresh feat/codex-shadow-enrollment branch. Implement six approved product paths: native protected provisioning/owner-lock/channel and process-local grant/lease/sequence; isolated CLI branch; service lifespan; shadow-only MCP enroll/status registration and child lifecycle; bounded read-only Relay snapshot. Preserve inert behavior. Use message-mode bounded JSON, OS user/retained-peer validation, genuine per-request metadata, independent fixed-pair authority, finite monotonic deadlines with UTC policy expiry, fresh epoch/revision invalidation, no retry after uncertain mutating response. Dedicated daemon I/O workers, stop-event plus bounded join, same-worker cancellation and retained unresolved buffers isolate ordinary shutdown. Add caller tests during implementation, then subsystem and selector-required full non-slow checks once, import/governance checks, independent result review, PR/CI. Manager owns final merge/install decision; no live trial follows. Stop and report material scope/security/automatic rejection, never weaken a regression.

**Verification plan:** Valid/invalid exact-pair enrollment and finite lifecycle → actual MCP/native channel tests; ACL/peer/pipe collision/partial/max/over-max/unicode/version/sequence/error/cancel/EOF/shutdown → Windows native caller tests with restricted-token denial, distinguishing it from a foreign-user witness; pending/queued/uncertain/delivered/expired/live-claim/partial observations and locked database → read-only snapshot/native status tests with unchanged ordinary Relay read assertions; monotonic rollback/forward UTC expiry and restart/revoke/competitor → complete lifecycle caller tests. OFF/inert/HTTP/non-Windows/missing APIs preserve catalog/normal tools → existing and extended MCP caller tests. Assert zero wake/claim/ACK/payload/settings/reservation changes. Run python scripts/test-plan.py --base origin/main, required full suite once, import-linter and fresh complete-path Redline/workflow checks; native coverage must not be replaced by Linux skips.

**Plan review:** Agent technical review: independent review_bridge_security_options (Sol/medium) accepted exact prospective minimum at private design checkpoint 84e2b5e241f56adce4ef9ce992c71bf595134ed2, including process-local reduction, trust adjustment, read-only deadline, cancellation ownership and fresh shipped-base requirement. Manager separately accepted that exact revision and authorized this isolated implementation; reference in Plan review below. Reuse unchanged review, not another broad audit.

**Approvals:** Approved by user standing task authorization: "I approve, stop asking, all is approved". The user explicitly delegated expert/manager review and continued non-destructive reliability work; manager conveyed final exact-plan technical authorization on 2026-09-28. This is standing human work consent plus delegated technical review, not a claim the human personally inspected this plan/diff. No live policy/activation or merge/install authority is inferred.

**Exceptions:** None

**State:** Ready for review
<!-- agent-workflow:end -->

## Plan review

User requested Astra as manager/expert and continued exploration; independent Sol review accepted the native shadow plan and its process-local simplification. Manager inspected exact final design revision and directed implementation under existing explicit work approval, requiring focused tests, full checkpoint, PR and final manager merge/install decision. No unrelated private incidents or raw runtime evidence are publication inputs.

## Checkpoints

API-review: additive optional empty-argument shadow enroll/status tools only for eligible Windows stdio; ordinary/off/inert/HTTP catalog unchanged. Persistence-review: new bounded read-only metadata reader only, no schema/data write or normal pool/timeout change. Security technical review: OS-authenticated peers plus protected operator policy, no authority from identifiers/ancestry/capability presence; trusted-local same-user compromise remains outside isolation. Required PR checkpoint labels/reviews remain actual repository gates, not implied by this record.

## Implementation

Pre-edit: main and reuse checkout were clean; merged PR252 checkout is free of runtime ownership because integrations/service use the separate stable installed clone. Fresh branch from fetched origin/main 4d75328e; intended thirteen-path Redline classification includes API and persistence checkpoints, no boundary violation. Workflow applicability is normal (application change), not documentation exemption. Record committed at ce9fa6ac before code. Six approved product paths implemented; native tests and coherent integration verification underway. apply_patch worked; no deterministic fallback needed.

Development review corrected next-turn controller binding, native TokenUser tuple handling, and unresolved write-buffer retention. Reader corrections cover NULL expiry and terminal-history masking. Native reservation and Relay scope generations are different domains; existing traces do not correlate them. Actual anchored work remains held with an explicit evidence limit, accepted by manager; no writer/core scope expansion. This stage qualifies channel/enrollment/lifetime, not production wake eligibility.

Native full-chain checks reject foreign ancestor replacement rights and foreign owners. Ordinary Windows C:\ root is owned by exact canonical TrustedInstaller SID; manager and independent reviewer approved that privileged OS SID for ancestor ownership only. No service-SID prefix/display-name trust, ACL modification or private-owner/peer widening. Fixed local drives only. Unexpected pending I/O failures now use the same cancel-or-retain ownership path; grant/UTC authority is rechecked after reads.

## Evidence

Initial focused evidence: MCP caller file 39 passed (17.53s); vocabulary alignment focused 45 passed/19 deselected (3.58s); separate provisioning CLI 7 passed/49 deselected (0.19s). Reader initial 15 passed; changed null-expiry/history cases and native Windows checks pending. Initial independent development review findings are being resolved before final review. Broader checks have not yet run on this change.

Coherent subsystem checkpoint: MCP bridge, Codex integration, read-only snapshot and Codex wake files: 281 passed in 63.12s. Read-only file corrected: 19 passed. Native kernel suite 54 passed before final ancestor-owner hardening; final exact-SID/ancestor regression run pending. Optional service startup/shutdown faults keep HTTP health/status working: 2 passed (0.98s). Selector reports full lane across the complete thirteen-file union; full non-slow and final independent review remain pending. No live provisioning or activation occurred.

Final native checkpoint: 62 passed in 4.38s, including one real stdio MCP child → real worker/client/service pipe → actual Relay SQLite reader. Next-turn observation, ordinary-tool responsiveness, controller denial, child EOF and unchanged HTTP message/all Relay tables are asserted. Only unrelated normal get_status HTTP client is stubbed in that child; shadow path is real. Actual foreign-account and Desktop child lifetime remain unqualified.

First full non-slow attempt at dfe70d89: 1 failed, 2002 passed, 2 skipped, 1 xfailed (119.60s), stopped on unchanged Claude hook test_confirmed_switch_does_not_attach_old_identity_to_new_pin. Original output is retained in this task's exec-session 21913 transcript, not misrepresented as a saved file or passing run. Exact node passed twice alone; clean main hook file passed 63 tests with four workers and identical source hashes. Cause remains unknown: baseline matches do not prove non-causality. No hook/test contract was altered. A complete final run after the actual-chain coverage correction is required; no retry-until-green loop.

Final complete non-slow checkpoint at 6e1b2f979f2e30883ca5c231c0cf4184189ea388: 5455 passed, 34 skipped, 2 xfailed in 242.41s. Local authoritative output: ignored build/shadow-full-final.log; PR/CI is the published evidence surface. Additional startup/provisioning/remote-drive checks: 10 passed (1.08s). Fresh import-linter/Redline complete-path checks pass boundaries; workflow blocking predicates pass, with pending API/persistence maintainer result-review checkpoints reported as advisories. Reuse unchanged native/subsystem evidence; no application code follows the tested revision.

## Result review

Agent technical review: independent non-implementer review_bridge_security_options (Sol/medium), accepted exact candidate after reviewing production corrections and the real stdio/native/SQLite caller journey; final full-suite condition satisfied by the checkpoint above.

Reviewed revision: 6e1b2f979f2e30883ca5c231c0cf4184189ea388.

Verification adequacy: adequate for the approved shadow-only enrollment/observation slice. Real Windows peer/ACL/channel and actual MCP-to-SQLite lifecycle evidence supplement the full non-slow suite. No outstanding material finding; High risk unchanged and six-product-path scope preserved. Native anchors remain held without invented generation correlation. Restricted-token denial is not foreign-account proof; Desktop lifetime, zero-child bootstrap, busy-safe owner admission, durable owner fencing and actual wake activation remain unqualified and excluded. Original intermittent full-run cause remains unknown despite the passing complete final checkpoint.

Human result review and API/persistence PR checkpoints remain distinct maintainer gates. Manager owns final merge/install decision and canonical roadmap reconciliation. Ready for review is not shipped or reliability complete; no live provisioning/activation is inferred.
