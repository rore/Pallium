---
id: add-dashboard-operations-and-relay-workspace
title: Redesign the dashboard around Operations and Relay
status: queued
priority: high
commitment: committed
milestone: pallium-relay
lane: product-surface
---

## Product outcome

The local dashboard reflects Pallium's current product: Relay and Session History
are primary capabilities, while Derived Memory is optional, experimental, and
disabled by default.

Replace the current top-level Operational | How memory helps model with:

1. **Operations** (default) — service and capability health, inspection, and
   debugging.
2. **Relay** — a human-readable workspace for the existing Relay session and
   communication fabric.

The dashboard remains observational and administrative. It does not create agents,
assign work, send as an agent, schedule turns, or define workflows.

## Current-state audit

The implementation already provides a useful base, but its information architecture
still represents the earlier memory-centric product:

- app/dashboard.html is a large vanilla HTML/CSS/JS page with responsive dark UI,
  an Operational tab, a How memory helps tab, service/queue/query panels, a Relay
  summary, Memory Browser, Query Debug, and offline effectiveness reports.
- /health, /status, /debug/queue/health, /dashboard/api/metrics/*,
  /dashboard/api/feedback/stats, and /dashboard/api/relay/summary already expose
  service, processing, retrieval, derived-memory, and aggregate Relay signals.
- /dashboard/api/containers, /dashboard/api/actors, and /dashboard/api/activity
  currently derive their results from memory objects, so they do not support a
  package-free Session History dashboard.
- raw SourceItem storage already records governed content, source/content type,
  actor, role, container, thread, source/artifact/agent references, event and ingest
  times, structural work references in metadata, processing state, and auditable
  forgetting. Broad/exact history search and bounded /source/{id}/context expansion
  already enforce visibility, redaction, and forgotten-item exclusion. There is no
  dashboard-oriented SourceItem list/detail projection.
- Relay already has container-scoped session list/name/close, targeted send/reply,
  message-status, delivery/ACK, lifecycle, and wake-candidate behavior. The current
  session view omits the persisted RelaySessionRecord.id and container metadata;
  there is no global/cross-container session list or paginated message-history read
  surface.
- persisted Relay messages contain the post-redaction payload, sender runtime/native
  session, recipient selector, reply link, actor/container, creation, and expiry.
  Deliveries contain recipient runtime/native session, state, claim/delivery times,
  and attempts. Wake attempt/success telemetry is not persisted and must not be
  invented by the UI.
- current Relay identity, alias uniqueness, delivery lookup, reply, status, and wake
  paths remain container-coupled. The dashboard must consume—not pre-empt—the
  canonical actor-scoped endpoint and routing contract from
  investigate-cross-repository-relay-coordination.

Before implementation, turn this audit into two explicit matrices in the UX/design
artifact:

1. every current panel classified as core/service, Session History, Relay
   operations, Derived Memory, experimental/evaluation, or obsolete;
2. every proposed datum classified as reusable now, new dashboard API, dependent on
   cross-container Relay, or dependent on runtime-specific native discovery.

## UX reference and implementation handoff

Open [the interactive UX mock](../../docs/designs/dashboard-operations-relay-ux.html)
in a browser. This standalone repo-local reference illustrates navigation,
progressive disclosure, selection, and drill-down—not graphic design. Preserve the
production design system. Synthetic data, IDs, health values, and simplified alias
behavior are not API contracts; this feature and canonical backend semantics take
precedence over mock simplifications.
The older [two-view design](../../docs/designs/dashboard-two-view-ux.md) documents
the previous Operational / How memory helps implementation; its top-level
information architecture is superseded by this feature, not a competing target.

Everyday journeys:

- Operations: scan health → expand a capability → select a stored item → inspect
  content, provenance, and bounded context.
- Relay alert: open the workspace with the relevant state/item selected, with a
  clear way back to general browsing.
- Relay: find a session by name, runtime, or container → select a session or graph
  connection → read messages → inspect delivery or follow a parent reply.
- Derived Memory: expand the capability → browse preserved objects → inspect a
  memory and its existing diagnostics, including with new derivation disabled.

Before coding, reconcile the current-state audit and API/dependency matrices with
the checkout. Cross-container Relay is in active development; do not assume either
the old contract or its planned replacement is the shipped contract.

## Information architecture

### Operations

Operations answers: **Is Pallium working correctly, and what is happening inside
each enabled capability?** Keep one compact service-health summary first, followed
by capability-oriented collapsible sections.

Use full-width capability sections rather than explorers inside small summary
cards. Keep service health, alerts, and each capability's health/enabled summary
visible when collapsed. Nest explorers under their owning capability. Start them
collapsed and remember expansion preferences locally. Alert navigation opens the
relevant section and selects its item. Collapsing preserves selection and filters.
Use keyboard-operable expanders with accurate expanded state. Relay links to its
dedicated workspace rather than duplicating its explorer here.

#### Session History / source ingestion

Make raw Session History first-class even when every semantic package is disabled:

- recent and total SourceItems;
- raw recording/storage health;
- lexical search/index availability and optional raw-vector state;
- retention and forgetting state;
- historical lookup and bounded expansion activity where already measured;
- failures or stalled work that actually affect raw history.

Do not relabel the existing ingestion/processing queue as raw source ingestion.
SourceItem.processing_status and package-processing rows include optional derived
package work; the design must separate synchronous raw recording/indexing from
derived extraction/rebuild queues and name each metric by what it measures.

Add a governed **SourceItem explorer** with recent items, bounded search, filters for
container/thread/source type/role/agent when present, event and recorded timestamps,
structural work references, meaningful index/processing state, forgotten-state
handling, and pagination. Detail shows only stored, caller-visible, redacted content
and metadata. Open surrounding context reuses the existing bounded
/source/{id}/context behavior; do not build transcript replay or bypass visibility,
retention, redaction, or forgetting.

#### Relay operations

Keep the existing Relay health summary as an operational subsystem: messages,
delivered/pending/expired counts, delivery latency, redeliveries, runtime lifecycle
counts, and persisted destination health. It answers **Is Relay healthy?** and does
not duplicate the Relay workspace.

#### Derived Memory

Treat Derived Memory as optional, not deprecated. Preserve Memory Browser and
Query Debug under its collapsible section. Disabled means new processing is off:
show that compact state and a count of preserved objects, while keeping stored
memories browsable and inspectable under the same governance. Do not hide the
explorer or erase data when derivation is disabled. Show an honest empty state
when no memories exist and distinguish historical diagnostics from unavailable
live processing. When enabled, show the existing package/extraction queue, memory
counts, derived query/injection/skip/feedback/flag diagnostics, and extraction
failures here. Disabled processing is not a failure or a wall of zero metrics.

Move existing historical lookup/reuse measurements under Session History evaluation.
Move RAW/DERIVED/HYBRID and derivation-fidelity reports under Derived Memory. Preserve
their live/retrospective/offline labels, last-generated timestamps, empty states, and
existing report readers; do not delete useful backend/report support because the
top-level hierarchy changed.

### Relay workspace

Relay answers: **Which sessions exist in Pallium's Relay fabric, and what
communication actually occurred?** It is not the Relay health screen.

#### Session explorer and naming

Show named and unnamed Pallium-known sessions as equal participants. Where the
canonical contract provides it, show endpoint ID, optional alias, runtime, native
session reference/title, container/repository/worktree metadata, last seen,
lifecycle, and persisted destination health. Show wake capability/status only from
observable evidence.

Show the container on every session surface: list, graph node, and detail. Use a
readable container name and expose the canonical full reference in details;
distinguish repository/worktree metadata when available. Include containers in
session search and filtering. Duplicate readable names remain distinguishable
through canonical endpoint/container references. Missing metadata is explicitly
unknown, never inferred from the dashboard checkout. Cross-container edges are
visible within the authorized actor domain without widening History/Memory access.

Allow assign, transfer, and remove alias through the existing canonical naming
semantics. Provide copy actions for canonical exact selectors and alias selectors.
Naming is optional addressing metadata, not registration, permission, or Relay
membership. Containers are provenance/filter/group metadata, not a communication
boundary in the intended actor-scoped Relay domain.

#### Communication graph

Render an observational graph:

- node = one real Relay session, named or unnamed;
- edge = persisted Relay communication between two sessions;
- node/edge activity derives from a bounded selected time window;
- runtime and container/repository are visual/filter metadata;
- node click opens session detail; edge click opens pairwise message history.

An edge never means permission, dependency, workflow transition, or an executable
rule. Derive the initial graph from a complete, explicitly bounded message window
using the shared message projection. One paginated page is not the whole window:
either exhaust its bounded pages or visibly label coverage as partial/truncated
and offer a way to load more. Never present first-page counts as complete activity.
Pair selection and the explorer must agree on window and filters. Add a separate
aggregate endpoint only if real volume or latency warrants it.

#### Message explorer

Provide global recent activity plus per-session and pairwise views. Show sender and
recipient, selector/alias used at send time when represented, timestamps,
reply/in-reply-to relationship, delivery states/attempts/timestamps, expiry, and
persisted destination health.

Expose only the stored post-redaction payload. Never retain or reconstruct the
pre-redaction message. Do not claim wake-attempt or wake-success telemetry until a
separate telemetry feature persists it.

#### No composer

Do not add a dashboard message composer. Current Relay requires a real sender
session and validates that sender; the dashboard must not impersonate one. A future
explicit user-to-session message type would change the Relay sender contract and is
separate work.

## Backend/API plan

### Pure redesign and reuse

- keep /health, /status, /debug/queue/health, existing dashboard metrics,
  effectiveness-report readers, Memory Browser, Query Debug, and Relay summary;
- reuse raw history search, SourceItem persistence, historical metadata, and bounded
  source-context expansion rather than copying their governance logic;
- reuse Relay session naming/lifecycle semantics and persisted message/delivery
  records rather than implementing a dashboard-specific registry or delivery model;
- retain the current local responsive/dark UI foundation. Splitting
  app/dashboard.html is allowed if it materially improves maintenance, but add no
  frontend framework, bundler, or dependency without demonstrated benefit.

### New dashboard projections

- add small paginated /dashboard/api/sources and
  /dashboard/api/sources/{id} read models for recent/search/filter/detail. They
  must call shared governance behavior and fail closed; JavaScript must not query
  storage internals directly;
- replace memory-backed container/actor/activity projections with capability-neutral
  or SourceItem-backed equivalents so Operations works with zero semantic packages;
- after the cross-container contract lands, add a bounded actor-domain Relay session
  projection that exposes canonical endpoint identity and location metadata;
- add one paginated Relay message/delivery history projection with time, session,
  pair, runtime, container, state, and reply filters. Derive the first graph from
  this response instead of adding a second graph backend;
- use the existing naming mutation surface if its post-migration contract is safe
  for the local dashboard. Do not expose storage writes directly.

All new list endpoints require explicit maximum page sizes, deterministic ordering,
empty pages, invalid-filter errors, and actor/visibility isolation. Avoid returning
claim tokens, receipts, secrets, or other delivery-control material to the browser.

### Explicit dependencies

- UX/IA, Operations, package-free health, SourceItem exploration, and relocation of
  existing panels can be designed and implemented against shipped behavior.
- canonical endpoint identity, actor-domain alias namespace, cross-container session
  listing, cross-container graph edges, and final Relay workspace E2E depend on
  investigate-cross-repository-relay-coordination and its accepted implementation.
  Do not hardcode today's container-scoped selectors as the new UI contract.
- recent native Claude Code/Codex/OpenCode session discovery is an investigation or
  integration-owned follow-up unless a runtime already exposes a safe bounded
  discovery API. Distinguish Relay-known endpoints from merely discovered native
  sessions, and never insert arbitrary native IDs into Relay just to populate the
  dashboard. Adoption/naming is allowed only when Relay can safely address and wake
  the endpoint under the runtime's real contract.

## Product boundary

The redesign does not make Pallium an agent runtime, agent creator, task or roadmap
manager, workflow builder, scheduler, supervisor, delegation engine, automatic
reviewer chain, or when-X-then-invoke-Y system. Users keep working in Claude Code,
Codex, OpenCode, and future integrations; Pallium makes those independent sessions
observable and connected.

Relay routing remains explicit and non-semantic. The dashboard consumes canonical
routing/identity state and never invents routing rules. Cross-container Relay does
not widen Session History or Derived Memory visibility.

## Required design and validation

1. Produce and review an Operations + Relay UX/IA design before layout code. Include
   the panel and datum matrices, priority/empty/error states, responsive behavior,
   and the split-or-retain decision for the current HTML file.
2. Run caller-surface dashboard/API E2E with all semantic packages disabled through
   start → ingest → index → list/search → detail → bounded context → forget → absent
   from normal results. Assert Operations is useful and contains no false derived
   queue failure.
3. Run the same surface with Derived Memory enabled, then disabled with preserved
   historical memories. Verify the section changes state without losing inspectable
   stored output or mislabelling offline evaluation as live.
4. Cover SourceItem empty/one/max/over-max pages, Unicode and non-ASCII content,
   search/filter combinations, deterministic pagination, missing IDs, invalid
   filters, forgotten anchors/neighbors, mixed visibility, redaction, retention,
   structural references, and raw lexical/vector enabled/disabled/failure states.
5. Cover Relay empty/one/max/over-max pages, named and unnamed sessions, alias
   assign/transfer/remove/conflict/idempotence, multiple runtimes, closed/dormant/
   unreachable/reactivated states, replies and reply chains longer than two,
   pending/claimed/delivered/expired/redelivered delivery states, Unicode/redacted
   payloads, and missing/invalid/other-actor entities.
6. After cross-container Relay lands, drive traffic between sessions in different
   repositories/containers and verify session list, graph, message filters, naming,
   and detail views through public endpoints. Assert the dashboard exposes no
   cross-actor Relay data and no cross-container Session History data.
7. Verify graph nodes/edges exactly match the selected bounded message window;
   unnamed sessions remain visible, message-less sessions have no invented edges,
   and graph interaction cannot create messages or workflow state.
8. Run the real dashboard in a browser at desktop and narrow widths, with empty,
   realistic, and high-cardinality fixtures. Iterate visually and keep screenshots;
   HTML substring tests alone do not validate the UX. Cover capability collapse and
   preference restore, alert-to-item navigation, preserved-memory exploration while
   derivation is disabled, container labels on every session surface, duplicate and
   missing container names, and graph coverage across pagination.
9. Update docs/dashboard.md and screenshots so public documentation describes
   Operations + Relay and the package-free primary configuration. Keep Relay and
   Session History docs aligned with the accepted cross-container contract.

## Done when

1. Operations is the default top-level view and remains fully useful with every
   semantic package disabled; Session History, Relay health, and optional Derived
   Memory have accurate, compact capability sections.
2. A governed SourceItem explorer supports bounded recent/search/filter/detail and
   existing surrounding-context behavior without a dashboard-only access path.
3. The Relay workspace shows canonical named and unnamed sessions, observational
   communication edges, and stored/redacted message-delivery history; aliases can be
   managed without changing communication authority.
4. No dashboard composer, workflow control, invented wake telemetry, unbounded list,
   governance bypass, or heavy frontend stack is introduced.
5. Required public-surface E2E, cross-container E2E after its dependency lands, live
   browser verification, docs, and screenshots pass. The completed
   add-dashboard-operational-and-value-rework item remains done; only its obsolete
   product framing is superseded.
