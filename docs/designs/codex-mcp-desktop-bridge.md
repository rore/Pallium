# Codex MCP Desktop bridge

Status: product integration is implemented, independently reviewed and installed
locally. Default automatic Windows Desktop delivery has live idle and unloaded
witnesses: one claim/ACK each, payload-only marker responses, no manual target wake.
Existing inert, shadow and finite inventory modes retain
their separate restrictions.
Canonical work: [wake-first Relay delivery](../../roadmap/features/add-wake-first-relay-delivery.md).
Private experiment: `codex-desktop-bridge-spike` Work Record; its history is not publication-ready.

## Approved product integration (2026-10-01)

Automatic wake covers registered Codex Relay recipients across sender runtimes
by default on supported Windows Desktop. Normal setup forwards the host capability
name `CODEX_APP_TOOLS_PIPE_PATH`, without storing its value. Native Windows stdio,
Codex agent identity and an actual inherited host capability remain required;
HTTP MCP and other platforms do not start this connection. The Windows native
service listener starts automatically at its configured local port. Existing
explicit finite diagnostic modes retain their separate lifecycle. A legitimate local Codex MCP child supplies the retained
connection and actual request metadata during ordinary Relay activity. Caller
metadata is provenance; it is never taken from model-supplied sender arguments.
Source/channel/Desktop loss or service restart invalidates connection custody.
The private connection is scoped to the service's actual listening port. MCP
must configure the matching loopback HTTP URL; remote services, URL credentials,
path prefixes, queries and fragments cannot enroll a local wake connection.

The existing scheduler reads the exact target's current Desktop state before
dispatch. `idle` selects the existing queue and prompt hook; `notLoaded` selects
retained MCP and the SessionStart hook. Working, unknown, malformed or
unavailable state leaves the delivery pending for existing recovery. This is
best-effort non-interruption: Desktop provides no atomic idle-only submission,
so the target can become busy between the check and the wake.

Reuse the existing durable reservation and persist uncertainty before initiating
the selected transport. Never fall back to the other transport after an attempt
or uncertain result. Release the registry lock before waiting for responses.
Hook payload emission and ACK remain
the delivery path. Normal operation requires no manual trial policy or action
files, new message store, second scheduler, or new transport implementation.
Historical trial fences remain intact.

Retained native wake alone does not guarantee a payload hook for an already
loaded chat. Loading through retained wake and then queueing would add a second
action unnecessarily. Both paths passed through the normal automatic lifecycle
on the installed build. Service restart
requires fresh authenticated MCP request metadata to re-enroll the connection.

These user-approved decisions supersede the earlier experimental requirements
below for normal product mode, including manual finite destination grants and an
absolute non-interruption guarantee. They do not change the restrictions of
existing experimental modes or prove general lifetime/restart reliability.

## Decision and evidence

Explore one optional adapter inside Pallium's existing Desktop-launched Codex
stdio MCP process. Do not start another Codex runtime, a second MCP server, or a
general broker. Keep the adapter disabled by default. Its first implementation
slice is inert: demonstrate lifecycle and normal-tool isolation with **zero
Desktop mutations**. This document proposes boundaries, not a shipping wake path.

The private spike demonstrated legitimate child inheritance of the Desktop
app-tools connection and genuine per-request metadata. A finite deferred action
was accepted after its authorizing turn completed while that child remained alive.
This does not prove custody after child exit. In one naturally unloaded disposable,
a native queued wake plus one Desktop owner action led to trusted hook injection
and ACK on attempt one, with observed settings preserved. That combined witness
does not identify which action loaded the task or establish an atomic load-only
operation. A different native-only unloaded recipient remained queued without
execution throughout a two-minute window; that is a bounded comparator, not a
same-recipient causal experiment or proof of permanent impossibility.

Desktop sends can join an active turn. The busy-turn/steering contract is therefore
**deferred**, not solved by a list-before-send check. The private interface is
version-bound. MCP-child survival across Desktop restart, unload, configuration
refresh, and capability replacement remains unqualified. Existing uncertain native
reservations remain fenced; none of this permits retrying their queue submissions.

An earlier separately authorized actual-Python lifecycle attempt could not
initialize its disposable through the ordinary Desktop messaging entrypoint, which
rejected setup without an active turn. Later authenticated shadow enrollment did
reach Pallium's protected channel after normal chat use, but did not open a Desktop
connection. The earlier setup result does not show that shadow enrollment still
lacks an initialization path; Desktop connection custody remains unqualified.

## Existing seams and eligibility

`app/cli/setup_codex.py` installs the Python `app.run mcp` child with stdio,
ten-second startup and thirty-second tool limits. It does not currently forward
the Desktop app-tools capability. `app/mcp/server.py:create_server` registers normal
tools and is also used by `app/main.py` for HTTP. Merely constructing this shared
server must never start a Desktop bridge. `app/mcp/context.py` resolves Codex task
identity from each request's metadata; a process-wide environment identity is not
an acceptable replacement for that request identity.

Eligibility requires an explicit opt-in installation mode, the Codex-local stdio
entry point, and an inherited Desktop capability. Non-Codex stdio, HTTP/SSE,
standalone service startup, missing capability, and incompatible native tool schema
leave the adapter unavailable while normal Pallium tools continue. Environment
flags select eligibility; they do not authorize destinations or actions. Global
Codex setup spans projects: enabling one installation must not grant wakes to all
projects or all sessions using it. Project trust and ordinary tool approval remain
mandatory. No trust bypass or fabricated request metadata is allowed.

Reuse the existing MCP lifecycle through an explicit entry-point option and an
optional app-layer module. Gate before importing that module. The implementation
must verify FastMCP's supported lifespan/shutdown seam rather than rely on private
SDK internals or start a thread during tool registration. Core Relay policy remains
runtime-neutral; the app adapter owns Desktop-specific framing and tool discovery.

## Custody, authority, and communication

In the shipped child-shadow mode, the Desktop capability stays inside the eligible
MCP child. Never return it from a tool, log it, write it into state, or send it to
Pallium's service. The shipped service-custody mode below is a separate,
default-off transport-only exception: after exact finite operator admission, the
existing service may retain one connection for inventory reads only. It does not
authorize wake actions.
Normal hook claim, payload rendering, scope injection, and ACK remain unchanged.
The bridge must not carry message payloads or become a second receive/ACK path.

| Boundary | Holds | Does not confer |
| --- | --- | --- |
| Desktop → MCP child | Private connection; current request metadata | Standing permission to wake any task |
| Approved enrollment → child | Bounded action grant with exact coverage | New identities inferred from cwd/history |
| Shipped child-shadow child ↔ service | Separate authenticated bridge channel; opaque grant handle | Desktop capability or arbitrary prompts |
| Shipped inventory source child → service | Endpoint transferred after exact operator admission; one RAM-only inventory connection | `tools/call`, wake, claim/ACK, payload, or broader Desktop authority |
| Service → adapter instruction | Exact delivery and live endpoint generation | Permission to override settings or retry native writes |
| Hook → recipient | Trusted scope and actual payload; claim/ACK | Bridge authority |

Availability and authorization are separate. Startup capability detection means
“this child might be able to connect,” not “this child may wake.” A future grant
must originate in an approved enrollment using genuine current request metadata
and explicitly authorized destination coverage. Bind it to the controller,
destination endpoint and scope generation, permitted fixed action, expiry,
revocation, and service epoch. A captured ended-turn grant is delegated authority,
not evidence that its original turn is still active. Thread, container, endpoint,
actor, and work references are identifiers, not secrets or authorization proofs.

The current HTTP client has no authentication headers; operations explicitly
defines the service as trusted-local with no auth. The service launch nonce proves
supervisor generation, not request authority. Existing dashboard/Relay GETs can
support inert observation, but cannot issue or validate production wake grants.
Loopback origin alone is insufficient. An authenticated enrollment and instruction
channel is a **prerequisite**, not an existing facility to reuse by assumption.

The shadow implementation uses a user-private Windows named pipe and separately
provisioned operator policy, not an HTTP bearer credential or new API authentication.
Store that policy only
in an operator-approved user-private location; do not place it in model arguments,
tool output, logs, repository configuration, or the service's public read surfaces.
Bind the channel to the configured service instance; reject redirects and remote
destinations. Authenticated channel possession identifies an enrolled child, but
does not prove a model-supplied controller ID or mint destination authority.
OS peer authentication does not independently attest Desktop origin. Shadow
trusts the explicitly enrolled component to assert genuine current request metadata;
it is not suitable for an untrusted client. Bootstrap and actual Desktop child
lifetime remain unresolved qualification gates. Same-user
malicious code and a compromised Desktop
process are not isolated by a user-private credential. No custom crypto or general
identity platform is proposed.

## Lifecycle, arbitration, and failure isolation

Several MCP children may exist. A child is an ephemeral executor, not the permanent
owner of every task. Each authorized controller has independent grants; never use
the last request's identity as global state. The service arbitrates one live executor
lease per grant/destination generation. A replacement child receives a fresh
instance identity and must re-enroll; an old child cannot act with a new epoch or
generation. Lease expiry indicates lost availability, not permission to retry an
already dispatched action.

Any later mutating stage requires a service-side atomic pre-dispatch fence for a
durable logical owner action, shared across children. Grants, epochs, and endpoint
generations authorize/check execution and belong in audit evidence; changing them
must not create a fresh attempt. Re-enrollment, lease replacement, another controller,
and scope moves retain an uncertain logical-action fence. A later protocol must
define correlation/coalescing with an immutable covered delivery set or a stable
pending-batch action identity when deliveries share an existing native reservation.
A newly observed message must not mint another owner attempt merely because its
delivery ID differs. These are required constraints, not a protocol designed here.
Rechecks alone are not atomic idempotency. Reuse the existing Relay store and wake
reservation patterns where their contracts fit; do not introduce an independent
broker database. Storage failure means no Desktop action. Crash after fencing,
timeout after write, missing response, or contradictory evidence retains an
uncertain fence and reports intervention. A fence may suppress an unexecuted action;
it cannot prove exactly-once execution. Lease expiry, service restart, or a missing
native queue row must not erase it. Owner-action fences and existing native queue
reservations are distinct: the bridge must never repeat the native submission.

For shipped child-shadow mode, service restart changes its bridge epoch,
invalidates transient leases/grants, and requires fresh enrollment; durable dispatch
fences survive. Child EOF, cancellation, shutdown, capability loss, or configuration
refresh stop background work and close its transports. Shipped service custody
has a separate EOF rule described below. A service outage marks bridge availability offline
without blocking normal MCP responses. Do not automatically bootstrap another
runtime or refresh authorization using historical request metadata. Backlog rescue
requires a new approved grant explicitly covering retained work; removing the
spike's freshness guard is not authorization for that work.

Use dedicated bounded daemon I/O workers and separate pipe resources, not the normal
tool client's retry budget. Coalesce one notification per authorized destination;
do not create an agent turn per delivery. Set explicit caps on enrolled grants,
pending notifications, response bytes, native calls, reconnects, and time spent
per operation. Saturation reports deferred/unavailable status without dropping
Relay messages or spawning unbounded tasks. Before activation, size these caps
against existing Relay limits rather than add speculative throughput machinery.

Adapter import/startup/background exceptions disable only the bridge. Shutdown
cancels its task, closes resources, and joins within a finite bound; a stuck optional
transport cannot delay ordinary MCP shutdown indefinitely. Blocking pipe operations
must have bounded cancellation behavior and cannot occupy the MCP event loop.
No raw native errors, payloads, credentials, or scope values enter diagnostics.
MCP stdout remains exclusively protocol traffic: no startup banners, polling logs,
or unsolicited status frames. Use fixed redacted stderr categories or a bounded
diagnostic surface. Ordinary Relay tools retain their existing error semantics.

An in-process adapter provides logical exception/resource isolation, **not**
protection from process crash, native-library faults, memory exhaustion, or an
unbounded implementation bug. Inert acceptance covers injected, contained import,
startup, task, and transport faults; it cannot promise normal tools survive a
same-process crash.
Move to a supervised child only if measured isolation failures justify it; do not
promise process isolation or build another broker now.

## Stages, evidence, and rollback

The inert development opt-in is `PALLIUM_CODEX_BRIDGE_MODE=inert`. It is considered
only by the local stdio entrypoint with `PALLIUM_AGENT_REF=codex` and inherited
Desktop capability presence. Ordinary setup does not enable it or forward the
capability. This mode owns one idle task, adds no tools, and does not connect to
Desktop or the service; it is not a delivery feature or an enrollment grant.

1. **Inert integration:** off by default; explicit local-stdio eligibility;
   optional lifecycle module; fixed bounded diagnostics. No grant issuance, new
   service route, background work selection, owner calls, native queue writes,
   claim/ACK, live service GET observation, live lifecycle experiment, or setup
   changes. Use deterministic fakes only. Test contained import/startup/task/
   transport failures and cancellation while concurrent normal tools still work.
   Assert zero Desktop mutations through the caller surface, including multiple
   children and non-Codex/HTTP construction.
2. **Authenticated shadow:** only after enrollment/auth design approval. Observe
   exact scoped candidates, arbitrate leases, and record hypothetical decisions.
   No Desktop mutations, delivery claims, ACKs, or reservations that suppress the
   shipped native path. Exercise forged/missing grants, restart/epoch/generation
   drift, expired deliveries, endpoint moves, concurrent controllers, response loss,
   EOF, saturation, malformed/oversized responses, Unicode, and version mismatch.
3. **Controlled activation:** separate authorization and reviewed busy-turn contract
   required. Prove settings/ownership preservation, safe admission, durable fences,
   uncertain outcomes, and actual hook injection/ACK in disposable recipients.
   Differentiate owner acceptance, queued native wake, and delivered payload.
   Keep ordinary busy recipients non-interrupted. Activation requires host-enforced
   safe admission or an explicitly approved exact contract change. A precheck that
   finds a cold or idle recipient does not prevent it becoming busy before the
   owner action; classifying recipients by that precheck is not a safety gate.

Inert tests drive MCP stdio/HTTP selection with deterministic fake resources and
controlled contained faults. Authenticated service-surface tests belong to the
later shadow/activation stages, not the inert slice. Those stages use deterministic
fake Desktop framing and controlled lifecycle faults before runtime qualification. Existing
spike evidence is reused, not re-created. Runtime trials are opt-in and bounded;
mock success is not proof of cold wake or Desktop lifetime. All production-related
changes receive repository-selected validation, caller-visible edge-case E2E, and
independent review. This design-only delta needs documentation/workflow checks, not
another spike run. The private branch's preexisting helper changes still need their
broader publication validation and privacy cleanup before any future PR.

Rollback disables the optional adapter and stops only its owned background resources.
Normal tools, hooks, pending messages, TTL, native reservations, and ACK behavior
remain intact. Revoke enrollment credentials/grants through their approved lifecycle;
never clear an uncertain fence merely to restore availability. No service/app restart
or configuration change is part of this design task.

The shipped child-shadow deliverable is authenticated **observation**, not automatic cold delivery; that mode requires a live MCP child.
The separate shipped inventory-custody mode is designed to bootstrap after ordinary first-chat use
and retain its admitted connection after source-child exit while the Desktop process
and epoch remain valid. It does not claim before-first-chat availability, zero-child
startup, restart recovery, or universal cold wake. Activation still requires
authenticated grant enrollment, busy-safe owner admission, and qualified executor
availability. Publication, installation, and reliability completion remain separate
from this design draft.

## Shadow-only implementation contract

The optional Windows mode adds two empty-argument MCP tools: enrollment and status.
It requires local Codex stdio, explicit `PALLIUM_CODEX_BRIDGE_MODE=shadow`, inherited
Desktop capability presence, a protected bootstrap file, and the required native
APIs. Neither tool connects to Desktop. OFF, inert and HTTP behavior is unchanged.
Ordinary setup does not enable shadow or forward the capability.

An operator separately provisions one controller/recipient pair, its exact scope
generation, action `shadow-only`, monotonically increasing policy revision, UTC
expiry, and enabled/revoked flags. Provisioning does not edit Codex configuration.
The policy and service bootstrap live under the user-private
`PALLIUM_HOME/config/codex-shadow` directory (default `~/.pallium`). Native owner,
protected DACL, non-reparse paths, exclusive owner lock, first pipe instance,
remote-client rejection, and both-direction OS process/user checks protect the
channel. Fixed local drives only are supported. Same-user malicious code,
administrators, SYSTEM and the exact Windows TrustedInstaller privileged OS owner
are outside this isolation claim; TrustedInstaller is allowed for ancestor ownership
only, never private files or channel peers. Other service SIDs are not trusted.
A restricted-token denial is not a foreign-user-account witness.

Current request thread and turn metadata must be present and agree. Identifiers,
environment variables, process ancestry, and capability presence cannot grant
destination authority. The service checks the independently fixed exact pair.
One serial channel holds at most one opaque process-local grant: maximum lifetime
300 seconds, lease 15 seconds, renewal no more often than every 5 seconds. Renewal
never extends the grant. Epoch, policy revision, sequence, retained process handle
and creation time reject stale or replaced participants. There is no grant table,
automatic reconnect, or re-enrollment after uncertain failure.

Observations use a separate read-only SQLite connection with `query_only`, no lock
retry, and a deadline within three seconds. They expose only bounded status/reason
and remaining grant time. Hypothetical eligibility is not atomic action admission
or delivery. No payload, handle, policy, scope, capability or raw native error is
returned. Normal storage timeouts remain unchanged.

Current native trace rows do not correlate their reservation generation with the
Relay scope generation. Actual native-anchored work therefore stays held, even
when accepted, with an explicit evidence limit. The channel tests qualify secure
enrollment and lifetime, not reliable production wake eligibility. Different
generation domains must never be compared as if interchangeable.

EOF, cancellation, stop, expiry, policy change/revocation, peer loss and restart
discard authority. Shutdown is bounded; uncertain overlapped I/O retains its owned
buffers/handles rather than freeing them or starting another worker. This stage
performs zero wake, claim, ACK, reservation or settings writes. Existing uncertain
native reservations remain fenced. Live provisioning and runtime qualification are
separate gates after review; tests use isolated temporary policy/channel fixtures.

An unavailable observation deliberately ends the shadow worker rather than keeping
or renewing unverified authority. A failed snapshot cannot establish current
endpoint/scope validity, so the service rejects it and closes the channel. The
worker also fails closed on an authenticated `unavailable` response. Neither case
automatically reconnects or re-enrolls. A fresh eligible MCP child requires a new
explicit enrollment with genuine current metadata and still-valid operator policy.
Normal MCP tools and retained Relay messages continue unchanged.

## Service-owned Desktop inventory custody

This separate, default-off implementation reuses the existing durable Pallium service
and never starts a detached helper or competing app-server. Ordinary inventory
admission performs only fixed, redacted `tools/list`; it grants no wake, claim, ACK,
or payload authority. Existing current-request wake authority and the shipped
child-shadow behavior remain unchanged.

The operator prepares a protected private inventory directory; that creates
readiness only, not admission. The service publishes an authenticated manifest of
its PID, creation time, and epoch. A child sends a capability-free ready message
valid for at most 300 seconds. The operator then arms one exact tuple: OS-
authenticated source child, service PID/creation/epoch, Desktop PID/creation/user
SID/executable/version, and enabled inventory-only policy with expiry no later than
300 seconds and action `desktop-inventory-only`. An explicit tool request asks for
admission. Only after policy checks
may the source transfer its inherited endpoint over that same authenticated
channel. The service rechecks policy, peer, epoch, revision, and expiry, retains at
most one RAM-only connection, and verifies the actual native server against the
approved Desktop identity before `tools/list` and each later inventory read. This
defines the startup sequence, not a general API or final user-facing flow.

Repeated admission for the same tuple/revision is idempotent. There is no
replacement or reconnect while I/O is ambiguous. Revocation advances the policy
revision to N+1 by compare-and-swap; only after conclusive close may the operator
arm N+2. Expiry, Desktop identity loss, or a conclusive close ends custody;
unresolved I/O remains unavailable until close is conclusive. Source-child EOF
alone does not revoke an independently
authorized service registration. A service restart loses the RAM registration and
requires a new admission after ordinary chat use; zero-child startup bootstrap and
persisted credential recovery are outside this implementation. This limited custody
provides no wake authority and does not qualify cold delivery, busy safety, or
restart recovery.

The proof uses at most two fixed inventory reads, not an external observation API.
Inventory treats unrelated tools' dictionary input schemas as opaque; the
separately armed owner action still requires its exact tool descriptor.
After admission the service reads once while the retained source process is alive;
that read must finish with the source still alive. Only after a positive signal
from that retained process handle may it read once more on the same connection.
Revoke, expiry, shutdown or identity loss wins over that second read; no retry is
permitted. At most four protected create-once artifacts (`proof-before.json`,
`proof-exit.json`, `proof-after.json`, `proof-failure.json`) hold strict,
epoch/revision/fingerprint-correlated redacted evidence. No phase is overwritten or
reused. The operator-only `read_inventory_proof(directory, expected_policy)`
performs a strict bounded schema and expected-policy comparison, returning fixed
historical status and booleans without connection, TTL or current-authority fields.
Missing phases mean incomplete evidence, not current closure or policy failure.
The supplied policy is comparison input, not authority;
this reader grants no authority and performs no tool call or connection. PASS
requires the complete consistent before/positive retained-handle exit/after sequence
with no failure artifact. The explicit `historical_transport_pass` remains
historical after later ordinary expiry, revocation, or stop. Neither the artifacts,
manifest nor a live HTTP process establish current worker/connection availability
or authority; the readback makes no such claim and never authorizes wake. Exact-owned cleanup
precedes rearming. This is not a recurring scheduler, persisted capability or
delivered-message receipt.

The existing sibling `policy.lock` serializes only `policy.json` pathname/security
opens and reads through data-handle close, plus policy writes through CAS/replace
and temporary cleanup. Retry only native WinError 32 at lock creation, with a
monotonic deadline of at most 0.2 seconds; other errors fail immediately. Release
the lock before Desktop verification, native I/O, source waits, disposal, or proof
publication. It never serializes native I/O.
The lock does not guarantee every Windows replacement succeeds. A failed policy
write reports failure and preserves the previous policy; failed revocation is not
reported as revoked. No data-write retry or permission relaxation is added.

Service-only failure diagnostics retain the first fixed stage and allowlisted
category for an actual transfer, correlated by service epoch and policy revision.
They distinguish native open/peer checks, before/post-exit authority and inventory
I/O, and proof publication before public normalization can lose that distinction.
No exception text, traceback, endpoint, environment, response or tool inventory is
logged. Unknown diagnostic values use fixed fallbacks; a failed log sink does not
change failure handling. Later cleanup cannot replace the original attribution,
and ordinary cleanup after sealed successful proof adds no failure diagnostic.
Public MCP fields and protected proof fields remain unchanged. These diagnostics
do not retrospectively explain an earlier failure or qualify unloaded wake.

### Finite exclusive unloaded-payload trial

A separately armed, one-endpoint trial may use the retained inventory connection
for one `send_message_to_thread` Desktop action. It requires an authenticated,
still-running source child with runtime-owned caller thread/turn metadata,
positive before inventory on the retained connection, current finite policy and
Desktop peer, and a distinct exclusively owned target. Source liveness and custody
are rechecked immediately before the native write; source exit denies this action.
The live operator must independently verify that the exact exclusive target is
`notLoaded` immediately before arming; source/target inequality alone does not
prove it. This remains a controlled experiment, not ordinary wake admission or a
busy-turn safety guarantee.

Before creating the delivery, the service commits a sticky `trial_enrolled` bit on
the target Relay endpoint and one exact SQLite trial row under the same Codex wake
registry lock used by native send and recovery dispatch. Both dispatch paths
suppress native wake for that enrolled endpoint. Missing or invalid trial authority
also suppresses native dispatch; normal endpoints keep their existing behavior.
The bit and row survive service restart and ordinary inventory-gate cleanup. A
single protected action request then binds one still-pending delivery. Before any
Desktop write, the service commits the irreversible spent fence, checks the exact
pending delivery and target again, and verifies the retained live tool descriptor.
No SQLite transaction contains a native call.

The fixed Desktop request uses the Relay-verified target thread and a delivery-ID
instruction only. The caller thread/turn comes from authenticated source metadata;
no payload, model, effort, host override, or operator-supplied caller identity is
sent. The source and target must differ. After a failed or ambiguous initiation,
the endpoint remains spent and native-suppressed; no retry or fallback is allowed.
Protected outcome and service log values are fixed enums only. `submitted` means
only that a matching non-error native result envelope was observed. A successful
trial requires a genuine target turn with hook payload emission and ACK/Relay
readback. Post-source-exit lifetime and general unloaded or busy-turn reliability
remain separate, unproven claims.
