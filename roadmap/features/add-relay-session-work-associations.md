---
id: add-relay-session-work-associations
title: Associate Relay sessions with multiple work references
status: done
priority: high
commitment: committed
milestone: pallium-relay
lane: product-surface
---

## Summary

Extend existing work references to the shared Relay session registry. Agents and
developers can discover the sessions involved in a feature, Jira ticket, branch,
Work Record, or another explicit work identifier, across worktrees and containers.
Expose the same associations through HTTP, MCP, the Relay dashboard, and subsequent
Session History ingestion. A session may carry several references simultaneously;
several sessions may share any subset. Association is not ownership or activity.

## Why

Today history can answer what was recorded under a work reference, and Relay can
find addressable sessions. The missing join is which sessions are involved in this
work. A developer coordinating implementation and review across worktrees should
not have to remember and redistribute each session alias. Shared registry state
also avoids writing transient session addresses into divergent Minimap documents.

## Priority and Dependencies

First in the Relay product queue (user priority, 2026-09-09): connecting sessions
to real work provides the clearest visible product value and demonstrates the
collection's integration. Implement before activation-capability normalization,
delivery traces, and further runtime expansion.

Use the existing session registry, routing, and public availability facts. Neither
the activation-capability feature nor delivery traces are prerequisites for
attaching, querying, or displaying associations. Preserve unknown availability
honestly and consume richer facts later when shipped; do not implement those
features inside this one. Confirmed delivery correctness incidents still take
priority. Existing workflow validation remains independently executable.

Minimap's companion feature is `add-pallium-work-item-participants` in the
[Minimap roadmap](https://github.com/rore/minimap/tree/main/roadmap/features).
Pallium owns the association API and generic reference rules. Minimap owns its item
reference producer and optional UI. Agree the shared contract before either
implementation; Pallium remains usable without Minimap or a tracker connector.

## Discovery Before Implementation

Recheck current main and record a compact contract/change inventory in the Work
Record. Start with `core/work_ref.py`, `core/relay.py`, `storage/sqlite_relay.py`,
`storage/sqlite_schema.py`, `api/schemas.py`, `api/routes.py`, `app/mcp/server.py`,
runtime hook reference discovery/ingestion, and `app/dashboard.py`/dashboard UI.
Read the shipped structural-work-reference, current-work injection, exact-search,
and dashboard feature records; older audit prose may describe pre-shipping state.

At planning time, history accepts bounded `pallium_work_refs` metadata (five refs),
and supported hooks discover branches and exact Agent Workflow Work Records.
The injected scalar current-work ref is structurally selected, not an arbitrary
explicit ref. Relay session registration/listing does not yet carry work refs.
The shipped dashboard is observational/administrative, not a human message composer.
Do not claim these new behaviors already exist or bypass existing runtime limits.

## Intended Developer Journey

1. The developer asks an agent to work on an identified feature or ticket. The agent
   attaches the exact known reference; a bare ambiguous ticket key requires its
   project/tracker context, not a guessed namespace. Known branch/Work Record
   references join it through existing structural discovery.
2. A reviewer in another worktree attaches the shared feature/ticket reference.
   It may have a different branch and Work Record. Both sessions remain normal
   native sessions; neither is launched or owned by Pallium.
3. In Relay, selecting the feature reference shows all associated participants,
   including runtime, container, alias/endpoint, and actual availability. The
   developer can inspect/correct explicit associations or copy an exact target.
4. Another agent queries the same reference, selects a recipient, and uses normal
   Relay send. Multiple results never imply broadcast or automatic selection.
5. On changing work, the session removes references it no longer participates in.
   Subsequent turns use the new snapshot; older history retains its original refs.
   A replacement session can use an explicit ref for existing exact history search
   subject to unchanged history visibility and container rules.

## In Scope

### Reference Identity and Shared State

- Persist bounded many-to-many associations against canonical Relay endpoints in
  the existing shared registry/storage. Alias transfer must not transfer bindings.
- Reuse the generic work-reference representation and normalization. Qualify new
  references by repository/tracker identity so unrelated repositories with the same
  branch/item ID, or Jira sites with the same ticket key, do not collide. Define
  stable identity across worktrees and fallback for repos without a usable remote;
  do not use absolute checkout paths or credential-bearing remote URLs as identity.
- Coordinate Minimap's reference format with its companion. Do not hard-code
  Minimap, Jira, or Agent Workflow semantics into Relay or require network lookup.
- Existing bare branch/Work Record refs and recorded history require an explicit
  compatibility decision. Do not silently reinterpret old strings, rewrite old
  sources, union unrelated namespaces, or widen exact search. Document limitations
  of legacy refs and how new qualified refs are supplied and selected.
- References attached together are not aliases or a hierarchy. Querying one exact
  reference matches that reference only; no transitive feature/branch expansion.
- Expose origin (explicit versus structurally discovered) and association freshness.
  Freshness is not proof of native activity, accepted work, ownership, or completion.
  Roles are optional: reuse an existing role field if appropriate; role management
  is not required for the first slice.

### Mutation, Lifecycle, and History

- Provide idempotent attach/detach and read operations, plus structural refresh.
  Choose compact exact HTTP/MCP signatures during design; no generic CRUD framework.
- Agent mutation identifies its current session through the existing runtime-owned
  identity contract. Do not allow arbitrary model-supplied self identities. Explicit
  developer correction follows existing dashboard administrative authorization.
- Track origins so refreshing a branch replaces only discovery-owned associations.
  Explicit feature/ticket refs survive. Detaching an explicit origin does not hide
  a ref still reported by discovery; show why it remains. Concurrent updates must
  not lose unrelated refs or resurrect explicitly removed associations by accident.
- Define close, stale, restart, reopen, deletion, and retention behavior using the
  existing endpoint lifecycle. Closed/stale participants are labeled and available
  through an explicit view/filter; do not silently advertise them as available.
- Carry the applicable association snapshot into subsequent raw turn metadata.
  Define precisely when it is captured, including an attachment during a turn and
  delayed/retried ingestion after detach. Never look up today's associations and
  relabel an older captured turn, or rewrite an entire past session.
- Reconcile the five-reference history cap with registry/input limits and combined
  explicit/structural refs. Define deterministic selection and visible overflow;
  no successfully attached ref may silently appear searchable when it was omitted.
- Preserve the scalar injected current-work contract unless intentionally revised
  with parity tests and guidance. A multi-ref session has no universally preferred
  ref; expose copyable exact refs so the agent can choose the intended search scope.
- Association/history enrichment failure must not break ordinary Relay delivery or
  turn ingestion. Return truthful mutation errors and make degraded continuity
  visible; never fabricate a successful persisted association.

### Agent Interfaces and Guidance

- Read current-session associations, attach/detach explicit refs, and find sessions
  by one exact ref. Return bounded/paginated results with endpoint, alias, runtime,
  container, reference origins, and existing lifecycle/availability facts.
- Discovery is read-only: no wake, message claim, alias mutation, or paid model call.
  Recipient selection and send retain current exact-target and ACK semantics.
- Teach agents to attach known explicit work when taking it up, retain relevant
  feature/ticket refs across branch changes, and detach when leaving that work.
  Never derive an association from conversational similarity or assume completion
  from silence. Agent access works without a Minimap server.
- Apply current Relay access rules to association reads/writes; attaching a ref
  grants no access to protected history or memory and implies no tracker permission.
  Treat identifiers as untrusted data; validate, bound, redact, and escape them.

### Relay Dashboard and Minimap Consumer Contract

- Show multiple selectable work refs on session detail with progressive disclosure
  for long lists; retain container and existing availability indicators.
- Selecting a ref filters the session view across eligible containers. Show the
  active exact filter, clear/reset action, pagination, and distinct empty, loading,
  failed, stale/closed, and unsupported states. Preserve existing container filters
  deliberately: make intersections visible rather than silently hiding matches.
- Let the developer add/remove explicit refs on a selected exact session. Show
  mutation failures/conflicts and discovery-owned refs without optimistic success.
- Provide copyable canonical targets and reuse existing session/message inspection.
  Do not add a human composer or send as an agent. If a supported filtered/session
  deep link is added, document its URL contract and safely encode untrusted refs.
- Publish the bounded capability/read projection required by Minimap: distinguish
  an unsupported API, unreachable service, and successful empty result. Minimap
  uses a configured local endpoint and stores no live bindings in versioned files.

## Out of Scope

Task ownership, execution state, dependency graphs, automatic dispatch/broadcast,
agent launch, tracker synchronization, Jira credentials/API integration, inferred
semantic associations, retrospective history backfill, a new registry service,
and Minimap UI implementation (owned by the companion feature).

## Verification and Done When

1. HTTP/MCP E2E drives register -> attach multiple refs -> discover across worktrees
   and containers -> select/send -> detach -> close/reopen -> cleanup, asserting
   through caller-visible reads. Multiple participants and shared subsets work.
2. Identity coverage includes same item/branch names in unrelated repos/trackers,
   same repo across worktrees, alias transfer, legacy refs, Unicode, malformed and
   secret-bearing refs, empty/max/over-max, duplicates, and missing endpoints.
3. Lifecycle tests cover explicit/discovered overlap, branch/cwd change, concurrent
   mutations, stale registrations, restart, delayed/retried ingestion, and isolated
   test cleanup. Physical endpoint deletion/pruning is deferred because no such
   product lifecycle exists; close/reopen retains associations.
   Old history stays unchanged; new refs retrieve new turns under existing scope.
4. Boundary tests prove no unauthorized cross-session mutation, no history scope
   expansion, no message/wake side effects on reads, and graceful storage/integration
   failure. Preserve current explicit-only discovery limits on unsupported hosts.
5. Dashboard journey tests exercise filtering, correction, long/escaped identifiers,
   unavailable/empty/error states, closed participants, and keyboard access. HTTP,
   MCP, and UI agree; no display claims a task is done or an agent is working.
6. An anonymized two-session example documents the developer flow and the stable
   consumer contract for Minimap. Tests use controlled sessions without paid turns;
   run focused coverage and repository-required checks before implementation review.

Shipped in the implementation PR with endpoint-owned associations, HTTP/MCP/dashboard surfaces, immutable hook capture, cross-runtime identity vectors, public-surface E2E coverage, and an isolated runnable demonstration.
