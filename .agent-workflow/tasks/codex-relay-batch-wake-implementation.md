<!-- agent-workflow:start -->
**Outcome:** Codex-to-Codex Relay exchanges can submit and deliver bounded whole batches through the regular-turn path, with notification-only wake only after G1-G3 evidence proves it safe.
**Target:** Pallium Relay milestone 1.
**Scope:** Implement only the narrow request-local Codex Relay receive-identity fix in `app/mcp/context.py`, `app/mcp/server.py`, `tests/test_mcp_context.py`, `tests/test_mcp_server.py`, `tests/test_relay_mcp_tools.py`, scoped MCP lifecycle E2E, and `AGENTS.md` plus relevant MCP/usage guidance. The immutable per-server metadata-trust flag defaults false and is enabled only by `main()`'s actual local Codex stdio bootstrap. No claim/ACK/reply semantic change, installed reload, service/config change, batching, coordinator, or G1-G3 work is included.
**Constraints:** Preserve unrelated `uv.lock`. No live trigger, production edit, service/config change, managed runtime, Claude/OpenCode wake adapter, second injection path, or redesign before this checkpoint is reviewed. Runtime adapters stay out of core; no raw claim token/HTTP guidance.
**Completion criteria:** Each applicable E01-E18 case drives its HTTP, MCP, or hook surface and observes status plus integration output; G1-G3 qualify the installed Codex runtime before wake is enabled; the no-ping exchange and wake-disabled regular-turn control have recorded evidence.
**Risk:** High
**Complexity:** Large
**Reason:** Intended changes include red API contracts (`api/schemas.py`, `api/routes.py`) and red persisted schema (`storage/sqlite_schema.py`), with durable ownership, expiry, and runtime-admission behavior. The work spans independently verifiable evidence, data, API, runtime, and release slices.
**Discovery:** The approved design is `docs/designs/relay-batch-codex-wake.md`; it supersedes earlier timeout/dual-path rules and leaves G1-G3 deliberately unproven. Current R1 sends one bounded payload, emits/ACKs individual deliveries, and `tests/test_relay_mcp_lifecycle.py` plus `tests/test_relay_mcp_tools.py` cover receipt-bound claim/ACK/reply and lease races. Existing wake fixtures are deterministic protocol fixtures only, not Codex queued-turn or full-admission evidence. The existing design Work Record is closed on branch base `4560f6b`; its `uv.lock` modification is unrelated.
**Material assumptions:** (1) A queued turn on the installed Codex runtime reaches the same pre-model claim/render hook as a normal/busy-boundary turn; G1 disproves this and keeps wake passive. (2) The runtime can witness full-envelope context admission and fence stale publishers; G2 disproves this and retains visible uncertainty without automatic replay. (3) The bounded batch envelope fits the real model context while draining a 64-delivery backlog; G3 disproves this and lowers/rejects limits before acceptance. (4) Pre-edit redline classification has no boundary violation; any such result stops implementation rather than being worked around.
**Plan:** (1) Review this preflight and run the smallest coordinated G1/G2/G3 qualification with no production mutation. (2) If a gate fails, record the evidence and return the adapter/admission design to review; do not implement a workaround channel. (3) If all gates pass, obtain API, persistence, architecture/runtime, and security review checkpoints before guarded edits. (4) Implement B's batch/passive path and its parameterized E01-E08/E10-E16 E2E coverage before C's notification coordinator; keep both wake and ordinary turns on one claim/render/admit path. (5) Implement C only after B passes; run D's installed-runtime, no-ping qualification and release/rollback checks. Reclassify on scope change.
**Verification plan:** G1 queued-turn hook and busy-boundary execution → captured installed-Codex hook transcript and status. G2 whole-envelope admission plus stale-publication fencing → full-envelope/digest witness with controlled interruption. G3 bounded 64-delivery drain headroom → installed-runtime size/context measurement. E01-E16 → parameterized HTTP/MCP/hook E2E cases on a fresh SQLite database with controlled clock/transport. E17-E18 → one bounded installed two-Codex run plus a wake-disabled regular-turn control, recording runtime/version/OS, captured full envelope, status, and cleanup. No test treats queue success, sender markers, model acknowledgement, or missing history as context-admission proof.
**Plan review:** The coordinator accepted the external review conditions through Relay on 2026-08-31; the user directly approved all architect instructions. Implement after documenting the conflict truth table and adding failing regressions, then return one consolidated commit/diff/test review. The local Codex parent-owns-stdio-pipe assumption is operational only, not cryptographic provenance. The prior G2/G3 review remains separate; no batch gate is opened.
**Approvals:** Approved by user 2026-08-31: "yes"; Approved by user 2026-08-31: "i approve everything the architect tells you to do"
**Exceptions:** —
**State:** Ready for review
<!-- agent-workflow:end -->

## Scoped receive-identity plan — review only

1. Keep `create_server()` metadata-untrusted by default. In `main()`, derive an explicit opt-in only when the actual selected transport is local `stdio` and the configured runtime is Codex; streamable HTTP, SSE, embedded/network mounting, test factories, and a mere environment claim cannot opt in.
2. Reuse the validated metadata parser for a request-local receive context. Inject hidden FastMCP `Context` only into `pallium_relay_receive`; on the trusted path, require valid matching `thread_id` and `session_id` plus a valid `turn_id`. Present-but-conflicting metadata or environment identity fails closed with no client call. Missing metadata may retain the current validated runtime-owned environment fallback; other runtimes retain their existing behavior.
3. Keep all receive/receipt/ACK/reply semantics unchanged after a session reference is selected. Do not expose identity metadata, add model arguments, mutate environment, or change service/configuration.
4. Add focused MCP and tool-layer regressions for trusted concurrent A/B request isolation, malformed/conflicting/no-call, hidden-schema/model-argument rejection, network-forgery denial even with stdio-looking environment, `main()` stdio bootstrap wiring, and unchanged legacy environment/receipt lifecycle behavior. Update Codex Relay guidance to state the integration-owned identity boundary and fail-closed behavior.
### Conflict truth table

| Request metadata | Environment identity candidates | Trust/runtime | Receive identity / observable result |
| --- | --- | --- | --- |
| absent | one valid resolved legacy candidate | any legacy/non-Codex, or trusted Codex | preserve current environment-backed receive |
| absent | no candidate | trusted Codex | current `PALLIUM_THREAD_REF` fail-closed result; no client call |
| valid equal thread/session + valid turn | none | trusted Codex stdio | use request-local session reference |
| valid equal thread/session + valid turn | all present candidates equal it | trusted Codex stdio | use request-local session reference |
| present invalid, null, one-sided, malformed, over-limit, or conflicting | any | trusted Codex stdio | fail closed; no fallback or client call |
| valid request metadata | any disagreeing env candidate | trusted Codex stdio | fail closed; no client call |
| any request metadata | any | untrusted/default/network server or non-Codex | request metadata ignored; preserve legacy behavior |
## Implementation

- 2026-08-31: Created `codex/relay-batch-wake-implementation` from `4560f6b` in the existing checkout. No production, service, configuration, or test changes were made. Awaiting review of this preflight and the G1-G3 protocol.

- 2026-08-31: Implemented the authorized diagnostic-only slice: `pallium_relay_status(runtime_diagnostic=true)` reads only injected FastMCP request metadata, reports allowlisted source/shape, presence/validity, and SHA-256 digests for validated thread/session IDs, and makes no receive, claim, ACK, configuration, or service change. The injected `Context` remains absent from the model-visible tool schema. Windows `apply_patch` failed with the documented process-launch restriction, so the four named files were updated using scoped deterministic PowerShell replacements.

## Evidence

### Required checkpoints

Pre-edit classification is HIGH: `storage/sqlite_schema.py` requires persistence review; `api/schemas.py` and `api/routes.py` require API review; guarded runtime/core/storage paths require architecture/runtime review. `core/visibility.py`, if changed for capability scoping, adds security review. Boundary rules prohibit `api` importing storage/runtime layers and storage importing `app`/`capabilities`; adapters compose outside core. No boundary exception is permitted.

### Smallest coordinated G1-G3 probe protocol

1. Use two existing installed Codex sessions and an isolated test container/database. Send one known batch through the normal MCP/Relay path, queue one bounded notification, and capture the recipient's queued pre-model hook at both idle and busy boundaries (G1). Do not use an app ping, manual receive, or payload-bearing queue item.
2. G2 passes only when the installed runtime exposes an independently readable, runtime-owned immutable context-commit artifact for the exact queued turn/recipient containing a fresh attempt nonce and the full-envelope digest. Interrupt before/after publication, reclaim, and attempt a stale publisher: it must produce no matching commit; any ambiguous outcome remains `uncertain`. Hook output, Relay DB writes, CLI queue success, model output, partial transcript, and absent history are non-evidence.
3. G3 passes only with a documented native hard input/context bound, or a conservative derivation, covering the maximal permitted normal-turn context plus eight max envelopes. Run exact-bound and over-bound envelopes across 64 pending deliveries and capture the wake-disabled ordinary-turn control. If only empirical headroom is available, disable wake and cap/passively block acceptance. Clean every test session, test database, queued notification, and temporary evidence fixture; retain only redacted evidence.

### E2E matrix

| ID | Observable result | Fault injection / boundary | Surface | Reset / evidence |
| --- | --- | --- | --- | --- |
| E01 | Valid whole batch only; rejected input creates no rows/wake | empty/one/max/over-max, whitespace, malformed, both/neither forms | HTTP + MCP | fresh DB; deterministic |
| E02 | Every accepted part/envelope is complete and bounded | exact/over bytes and code points, Unicode/RTL/emoji/surrogates, redaction growth | HTTP + hook | fresh DB; deterministic + G3 real runtime |
| E03 | Cross-part secrets redact; forged markers remain data | split secret, forged envelope | MCP + hook | redacted capture; deterministic |
| E04 | One committed snapshot/retry result; no expiry extension | crash/disk-full/contention, lost response, concurrent retry, alias transfer, cleanup | HTTP + SQLite | fresh DB/clock; deterministic |
| E05 | Scope/recipient/receipt misuse reveals no data or retargets | cross scope/actor/session, replay, close/reopen/project change | HTTP + MCP | isolated scopes; deterministic |
| E06 | Reply is atomic and bounded; failed reply never ACKs | expired parent, bad receipt, siblings, depth boundary | HTTP + MCP | fresh DB/clock; deterministic |
| E07 | Exactly one whole-batch owner, ordered on both paths | concurrent regular/wake/recovery claims in both orders | hook + MCP + HTTP | barriers/fresh DB; deterministic |
| E08 | Uncertain publication remains visible; stale publisher fenced | interrupt pre/post claim/publication/admission/ACK | hook + HTTP | controlled transport; G2 real admission witness |
| E09 | Wake uncertainty never duplicates delivery or strands regular turn | lost/duplicate/empty queue notice; regular turn wins | queue adapter + hook | clear queued notice; deterministic |
| E10 | FIFO makes bounded progress without starvation | over-turn backlog, oversized oldest, send at idle transition, equal/backward clocks | HTTP + hook | fresh DB/restart; deterministic + G3 backlog run |
| E11 | Restart/clock changes reconcile durably without blind retry | restart in every outstanding state; forward/backward clock | HTTP + hook | restart fixture/fresh DB; deterministic |
| E12 | Expiry and late evidence report truthfully | expiry before/during claim/publication/ACK/reply; sweep race | HTTP + MCP + hook | controlled clock; deterministic |
| E13 | Fan-out admission is atomic and recipients complete independently | mixed protocol/capacity/recipient failure | HTTP + MCP | isolated recipients; deterministic |
| E14 | Unsupported/disabled/stale/refused wake falls back only on a regular turn | absent/busy/permission/stale capability/unsupported hook | adapter + hook | clear capability state; G1 real queued hook |
| E15 | Limits/blocks/retry window are visible; no silent loss/loop | burst/rate/depth, compatibility shrink, invalid row, cleanup boundary | HTTP + status | controlled clock/DB; deterministic |
| E16 | Legacy traffic remains safe through upgrade/rollback | installer upgrade/downgrade, singleton/reply compatibility | installer + MCP + hook | disposable install/test DB; deterministic |
| E17 | Agent receives whole six-part batch and handles retry/status/reply | ordinary task with no coaching/external artifact | installed MCP + skill | isolated session/transcript; one bounded real-agent run |
| E18 | Automatic exchange has no surrogate prompt/ping; control uses ordinary turn | task→result→review→remediation; wake disabled control | two installed Codex sessions | clean sessions/queue; real-agent G1/G2 evidence |


### Architect correction pass (2026-08-31)

Hook-delivered review from `codex:01a032e8-038a-7ea1-9aad-a0c26710213b` (a lower-authority peer context) reproduced an unpaired-surrogate crash and requested this bounded correction. The patch now rejects non-printable/control/surrogate or overlong IDs before hashing; limits string metadata JSON to 4096 characters; and treats malformed/deep JSON as invalid. In-memory MCP regressions send different request `_meta` concurrently and assert each exact digest stays request-local, forged model arguments are ignored, status arguments remain mutually exclusive, and no status/receive/ACK/reply HTTP client method is called.

### Diagnostic-only evidence (2026-08-31)

- Focused MCP contract checks passed: `.venv\Scripts\python.exe -m pytest tests/test_mcp_context.py tests/test_mcp_server.py -q` → **67 passed**. The suite retains four pre-existing FastMCP/Pydantic forward-reference warnings.
- `python -m compileall -q app/mcp/context.py app/mcp/server.py` and `git diff --check` passed.
- Regression coverage asserts absent and malformed metadata, exact SHA-256 output without raw/secret fields, conflicting identities, independent session hashes, context omission from the model schema, normal status behavior, and unchanged fail-closed receive behavior without a runtime session ID.
- No installed MCP reload or live metadata probe was run. This is diagnostic instrumentation only, not G1 context-admission or receive-binding evidence.
### Runtime binding diagnosis (2026-08-31)

Observed: this Codex desktop session's `pallium_relay_receive` returns `PALLIUM_THREAD_REF is not set`; the coordinating Codex task reports the same failure. The failure is not a successful Relay exchange and no delivery was claimed.

Cause: the installed `mcp_servers.pallium` stdio configuration supplies static `PALLIUM_AGENT_REF = "codex"` but no `PALLIUM_THREAD_REF`. `app/mcp/context.py` correctly refuses model-supplied identity and can only fall back to `CODEX_THREAD_ID` or `CODEX_SESSION_ID`; neither is inherited by this MCP process. In contrast, the `UserPromptSubmit` hook receives `session_id` in Codex's hook payload and calls `/relay/turn` with it. Thus normal user-turn hook delivery can be session-bound while explicit MCP receive cannot be bound in this desktop host.

Implication: this is a runtime/session-binding qualification failure, not a queue or admission result. Keep explicit MCP receive fail-closed; do not create a shared static ID, infer from the address book, call raw HTTP, or use an app ping as evidence of delivery. Any future fix must establish a runtime-owned per-turn MCP session binding and prove it through G1/G2 before wake or recovery behavior changes.
### Dogfood correction preflight (2026-08-31)

This amendment supersedes the earlier conclusion that missing process environment proves unavailable identity. The installed Codex runtime parses `x-codex-turn-metadata` and recognizes `session_id`/`thread_id` (with `turn_id`); installed FastMCP exposes request `_meta` with unknown keys preserved. Pallium currently ignores that request context, so the evidence supports a bounded Pallium integration hypothesis, not an authorization to trust or claim from it yet.

- **RD-01 revised disposition — MCP receive identity.** Reproduction remains: both desktop sessions return `PALLIUM_THREAD_REF is not set` because `app/mcp/context.py` only resolves static environment/fallback variables. The installed stdio config provides only static `PALLIUM_AGENT_REF = codex`; multiple MCP subprocess trees exist under Codex app-server processes, so process multiplicity does not establish per-task binding. Read-only qualification is required for actual `_meta` presence, exact session/thread semantics, and whether the stdio parent/metadata boundary is trusted. No static ID, model-supplied field, address-book inference, raw claim, or metadata dump is permitted.
- **RD-02 corrected disposition — app delegation ping.** The historic app delegation ping neither injected Relay nor qualifies G1. It is not an executable activation protocol. Use a native Codex queue notification only where separately authorized; it remains notification-only and never proves delivery/admission.
- **Minimal review-before-reload diagnostic.** Add no claim-capable path. A status-only diagnostic may inspect FastMCP `Context.request_context.meta.model_extra` and expose only allowlisted booleans/source classification for `session_id`/`thread_id`/`turn_id`, metadata shape, and configured stdio runtime—not raw metadata or identifiers. Unit tests must reject absent, malformed, conflicting, model-argument, and cross-task values; an onboarding test confirms no static session config; a real no-coaching probe must compare two existing sessions. Only after review/reload may this diagnostic run; it does not authorize `relay_receive` to bind or ACK.
- **G1 recorded idle PASS (2026-08-31).** Native Codex queue activation `G1-ACT-20260831-0958-91bfc2` targeted the exact task/session `01a0478e-9bca-7570-88c7-09dcc76cc638`. Its singleton Relay envelope marker was `G1-SINGLETON-20260831-0958-7ef03c`, with Relay message ID `relay-msg-31bf4f3d05b14b439a98f409ddeec2fe`; it was automatically injected on that queued turn without manual receive/ACK. This is hook-delivery feasibility only: it does not prove G2 context admission, stale-publication fencing, receive identity, batching, or G3 headroom. No app delegation ping is part of the protocol.
- **G2/G3 corrections.** G2 may use full-envelope runtime-history readback or equivalent committed-context evidence, independently hashing actual content; a marker or absence is insufficient. Investigate stale-publication fencing now and test generation fencing only after it exists. G3 is <=8 complete batches and <=16384 code points/65536 UTF-8 bytes aggregate per turn; defer 64-backlog qualification until batch support exists.
- **Review/risk.** `build/relay-dogfood-preflight-redline.json` remains GRAY with no boundary violation/checkpoint for the dogfood paths; the Work Record remains High/Large due the retained API/persistence batch scope. New manager and clean-context review are required before code or diagnostic reload.
## Recovery

Current branch: `codex/relay-batch-wake-implementation`; baseline: `4560f6befe87deba2e17be5e0bd9cd9b6d69cd2f`; unrelated `uv.lock` remains modified and unstaged. Next action only after coordinator review: inspect the consolidated diff/test summary, then decide whether an installed-MCP diagnostic reload/probe is authorized. Do not bind receive identity, claim/ACK, alter config/service, or continue G1-G3 from this patch alone.

### Manager diagnostic review (2026-08-31)

Reviewed 12079dc: Unicode failure corrected; request-local protocol tests exercise real MCP calls and assert no status/receive/ACK/reply HTTP methods invoked. Independently ran tests/test_mcp_context.py, tests/test_mcp_server.py and tests/test_relay_mcp_tools.py: 83 passed, four pre-existing warnings. Removed an identical duplicate test definition directly (no extra review cycle). apply_patch hit Windows error 1327; exact-file deterministic PowerShell fallback used.

Diagnostic-only patch approved. Active manager MCP tool schema still lacks runtime_diagnostic, so installed metadata presence remains unobserved. The Codex MCP connection must be reloaded before two-session diagnostic calls; the installed codex mcp command has no reload subcommand, and no app reload tool is exposed. Do not restart the Pallium HTTP service as a substitute, kill unrelated processes or fabricate metadata. Next: reconnect the existing Codex Pallium MCP sessions, call pallium_relay_status(runtime_diagnostic=true) in each, compare hashes to known runtime-owned session IDs, then review the smallest identity-binding fix. No claims or wake/coordinator completion inferred.
### Post-restart live diagnostic checkpoint (2026-08-31)

This task's refreshed MCP call returned only allowlisted fields: `source=codex_turn_metadata`, `shape=object`, valid/present thread and session IDs with the same SHA-256 `00229bd63bde786a45957ec3a3687b0c23ccd61b76f66d6a803ef9ca6f3bb0ff`, valid/present turn ID, and `identity_conflict=false`. Independently hashing this task's runtime-owned session ID produced the same digest. The hook-delivered architect report from `codex:01a032e8-038a-7ea1-9aad-a0c26710213b` (lower-authority peer context) recorded a distinct matching digest `ce766a943dee07b4d16fa137a93363286bc2f91ae318ffd07598cb121e0d88ff`, valid/present turn ID, and no conflict. The two task-local digests differ as expected; this proves request-local diagnostic carriage across two sessions, not receive authorization, claim capability, or G2 admission.

### Proposed receive-identity slice — not authorized to implement

Smallest candidate: inject FastMCP `Context` into `pallium_relay_receive`, invisible to the tool schema, and derive a Codex session reference only from the allowlisted `x-codex-turn-metadata` request context when both `thread_id` and `session_id` are valid, equal, and accompanied by a valid `turn_id`. No model argument, environment mutation, static configuration, claim behavior, or fallback broadening is allowed. Missing, malformed, oversized, control-bearing, unequal, or unavailable metadata must preserve today's fail-closed receive response and make no HTTP call.

Security gate: the MCP request `_meta` field is caller-controlled in the generic protocol. Before this candidate can bind Relay ownership, architecture/security review must establish that this installed Codex transport authenticates the metadata origin (or supplies a signed/runtime-attested equivalent). The diagnostic's schema hiding and forged-model-argument regression do not prove that provenance. Without that evidence, the proposed binding remains blocked.

Required regression matrix before any implementation: valid matching request metadata binds only its own concurrent request; absent/malformed/deep/oversized/control values, one-sided IDs, conflict, wrong runtime, unavailable `Context`, and failed provenance all fail closed with zero client call; model-argument and raw-MCP metadata forgery cannot alter identity; existing environment-backed non-Codex/legacy receive behavior is unchanged; status diagnostics remain non-claiming; receipt/ACK/reply/lease semantics remain unchanged once a genuine receive is admitted.
### Consolidated identity-fix review (2026-08-31)

Architect Relay review specifies the local trust assumption precisely: the configured Codex host owns the stdio pipe. This is neither cryptographic attestation nor protection against a compromised local host. Therefore only `main()`''s actual local Codex-stdio construction may opt in, while generic factory/network paths remain denied independently of environment. External architecture review is the sole next action; implementation remains blocked and no G2/G3/batch gate has changed.

### Recovery update

Next action: obtain one focused external architecture review of the scoped plan, record its verdict, and return it through Relay. Do not implement, reload, claim, mutate identity/configuration, restart a service, or substitute an app delegation ping for native queue activation.
### External architecture review (2026-08-31)

Conditional approve of the scoped plan. Acceptance details for any implementation are now explicit:

1. Request metadata is caller-controlled MCP `_meta`; local-stdio acceptance rests only on the documented operational assumption that the configured Codex parent exclusively owns that pipe. The code and tests must not claim protocol-level provenance authentication. Generic `create_server()` and every network transport keep an immutable metadata-trust value of `False`, regardless of `PALLIUM_MCP_TRANSPORT` or request metadata.
2. The conflict algorithm must be defined and tested before coding. Any present-but-invalid or one-sided metadata fails closed with zero client call. Valid metadata requires matching thread/session IDs and a valid turn ID. Each configured/runtime identity candidate (`PALLIUM_THREAD_REF`, `CODEX_THREAD_ID`, `CODEX_SESSION_ID`) must agree with the request identity; any disagreement fails closed. Do not compare only `resolve_context().thread_ref`, because its current priority would hide contradictory environment values.

The requested hidden `Context`, request-local closure state, no-global-mutation rule, and unchanged claim/receipt/ACK/reply handling are otherwise approved. The next step is manager acceptance of this review through Relay; implementation remains blocked.
### Receive-identity implementation (2026-08-31)

Implemented the accepted bounded slice. `create_server()` now has immutable `trust_codex_request_metadata=False`; only `main()` sets it true for the actual Codex stdio bootstrap. `pallium_relay_receive` receives a hidden FastMCP `Context` only on that trusted server and uses the same bounded parser as the diagnostic. Complete matching request thread/session plus turn identity is request-local; all present runtime/environment candidates must agree. Invalid, null, one-sided, malformed, oversized, conflicting, or disagreeing metadata fails closed before any client call. Absent metadata retains legacy integration-owned environment resolution; non-Codex/default/network paths ignore request metadata. Claim token stripping, receipt/ACK/reply semantics, service/configuration, installed reload, batching, and coordinator behavior are unchanged.

Verification: `.venv\\Scripts\\python.exe -m pytest tests/test_mcp_context.py tests/test_mcp_server.py tests/test_relay_mcp_tools.py tests/test_relay_mcp_lifecycle.py -q` → **119 passed**, with four pre-existing FastMCP/Pydantic forward-reference warnings. `python -m compileall -q app/mcp/context.py app/mcp/server.py` and `git diff --check` passed. Coverage includes the truth table, direct stdio bootstrap, network-forgery denial despite stdio-looking environment, hidden Context schema, real in-memory MCP concurrent two-session receive plus ACK against disposable HTTP/storage, malformed/no-call, and unchanged lifecycle behavior.

### Recovery update — implementation review

Next action: return one consolidated commit/diff/test summary to the architect and await review. Do not reload installed MCP, change configuration/service, make a production claim, or continue batch/G1-G3 work from this slice.

### Consolidated final-review correction (2026-08-31)

Corrected the parser boundary so a present `x-codex-turn-metadata: null` is invalid rather than absent; only an omitted header retains legacy environment fallback. The FastMCP wire layer normalizes a null `_meta` entry away, so the direct parser regression proves the explicit-present distinction and the in-memory MCP regression proves the resulting no-claim fallback. Extended the protocol suite with all three runtime-candidate conflicts, malformed/deep/oversized/control inputs, hidden forged Context/model arguments, absent trusted-metadata fallback, and concurrent per-session receive followed by receipt ACK and receipt-bound reply. The original messages' delivery states are read through the ordinary HTTP status endpoint and both are `delivered`.

Verification: `.venv\Scripts\python.exe -m pytest tests/test_mcp_context.py tests/test_mcp_server.py tests/test_relay_mcp_tools.py tests/test_relay_mcp_lifecycle.py -q` → **129 passed**, with four pre-existing FastMCP/Pydantic forward-reference warnings. `compileall` and `git diff --check` passed. No installed reload, service/configuration change, production claim, or G1-G3/batch work occurred; unrelated `uv.lock` remains unstaged.

### Recovery update — final review

Next action: send the consolidated correction, test, and scope summary through the hook-delivered Relay reply and notify the architect session per the user's standing instruction. Await any further review; do not reload installed MCP, change configuration/service, make a production claim, or continue batch/G1-G3 work from this slice.

### Relay dogfood follow-up (2026-08-31)

The first hook-delivered `pallium_relay_reply` with only delivery ID/message returned 422 because `container_ref` and `actor_ref` were omitted; retrying with the injected scope succeeded. Recorded the generic follow-up `roadmap/ideas/fix-relay-hook-reply-scope-resolution.md` and placed it on the Agent Relay board. It is outside this completed identity-binding slice; no scope-resolution implementation was added here.
