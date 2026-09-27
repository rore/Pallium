# Optional Codex MCP Desktop bridge

Status: design draft, 2026-09-27. No production implementation or activation approval.
Canonical work: [wake-first Relay delivery](../../roadmap/features/add-wake-first-relay-delivery.md).
Private experiment: `codex-desktop-bridge-spike` Work Record; its history is not publication-ready.

## Decision and evidence

Explore one optional adapter inside Pallium's existing Desktop-launched Codex
stdio MCP process. Do not start another Codex runtime, a second MCP server, or a
general broker. Keep the adapter disabled by default. Its first implementation
slice is inert: demonstrate lifecycle and normal-tool isolation with **zero
Desktop mutations**. This document proposes boundaries, not a shipping wake path.

The private spike demonstrated legitimate child inheritance of the Desktop
app-tools connection and genuine per-request metadata. A finite deferred action
survived completion of its authorizing turn. In one naturally unloaded disposable,
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

The Desktop capability stays inside the eligible MCP child. Never return it from
a tool, log it, write it into state, or send it to Pallium's service. The service
can select eligible Relay work; only the child can communicate with Desktop.
Normal hook claim, payload rendering, scope injection, and ACK remain unchanged.
The bridge must not carry message payloads or become a second receive/ACK path.

| Boundary | Holds | Does not confer |
| --- | --- | --- |
| Desktop → MCP child | Private connection; current request metadata | Standing permission to wake any task |
| Approved enrollment → child | Bounded action grant with exact coverage | New identities inferred from cwd/history |
| Child ↔ service | Separate authenticated bridge channel; opaque grant handle | Desktop capability or arbitrary prompts |
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

For a later activation proposal, prefer a narrowly scoped, setup-issued local
bridge credential over changing authentication for all Pallium APIs. Store it only
in an operator-approved user-private location; do not place it in model arguments,
tool output, logs, repository configuration, or the service's public read surfaces.
Bind the channel to the configured service instance; reject redirects and remote
destinations. Authenticated channel possession identifies an enrolled child, but
does not prove a model-supplied controller ID or mint destination authority.
Credential possession does not prove that a genuine Desktop child supplied the
controller metadata. Origin binding and bootstrap remain unresolved prerequisites
for authenticated shadow, alongside enrollment approval, credential provisioning/
rotation, the supported local threat model, and platform protection. Same-user
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

Service restart changes its bridge epoch, invalidates transient leases/grants,
and requires fresh enrollment; durable dispatch fences survive. Child EOF,
cancellation, shutdown, capability loss, or configuration refresh stop background
work and close its transports. A service outage marks bridge availability offline
without blocking normal MCP responses. Do not automatically bootstrap another
runtime or refresh authorization using historical request metadata. Backlog rescue
requires a new approved grant explicitly covering retained work; removing the
spike's freshness guard is not authorization for that work.

Use a dedicated bounded async task and separate HTTP/pipe resources, not the normal
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

The next deliverable is the reviewed **inert** slice, not automatic cold delivery.
Activation has three gates: authenticated grant enrollment, busy-safe owner
admission, and qualified executor availability/bootstrap. If Desktop has no eligible
live MCP child, the proposed adapter cannot wake a task; restart/unload/replacement
qualification must establish how an authorized executor becomes available without
a competing runtime, manual task turn, or discarded fences. Until then report
unavailable and retain pending messages, rather than promise universal cold wake.
Publication, installation, and reliability completion remain separate from this
design draft.
