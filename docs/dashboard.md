# Dashboard

The local dashboard presents Pallium as two top-level views: **Operations** (the default) answers whether the service and each capability are healthy; **Relay** is an observational workspace for recorded sessions and exchanges. It is localhost-only and read-only: it does not create agents, send messages, assign work, or define workflows.

![Dashboard](../assets/dashboard_screenshot.png)

## Access

- Service mode: http://localhost:19836/dashboard
- Dev mode: http://localhost:8000/dashboard

No authentication is required because the dashboard is localhost-only, like the local API. Scope fields still apply to every history read; they are not an authentication boundary.

## Operations

Operations leads with service, storage, raw recording, queue, search, and Relay health, followed by collapsible capability sections. Pending Relay delivery is neutral; expired delivery and impaired dependencies are called out with actionable links. Existing metrics, activity, feedback, and diagnostics remain available under their owning capability.

### Session History

Session History remains useful with semantic packages disabled. The governed SourceItem explorer supports explicitly scoped list/search/filter/detail reads using `container_ref`, `actor_ref`, and typed `query_visibility`; omitted or invalid scope is rejected. Visibility, shared-item actor rules, retention/forgotten state, filters, and pagination are applied before counts and ordering, with per-record defense and redaction afterward. Detail is read-only and telemetry-free. An explicit surrounding-context action reuses `/source/{id}/context` with the same scope; refresh does not manufacture lookup events. Inaccessible, forgotten, or deleted evidence is shown as unavailable, never from a cached excerpt.

The usefulness panel separates live lookup/exposure/expansion facts from retrospective judge or benefit claims. Last-written aggregate reports show their generation time, evaluated window, denominators, sample/rated/failed/missing counts, completeness, versions, and uncertainty when present. Missing, stale, incomplete, or unvalidated reports are not rendered as zero benefit. A separately bounded reuse-event view exposes only redacted query/linkage/label metadata and resolves source evidence live; it is operational evidence, not assumed to be the exact aggregate sample.

### Derived Memory

Derived Memory is optional and disabled by default. Existing Memory Browser, query activity, injection/skip/feedback/flag diagnostics, Query Debug, and extraction reports remain here. Disabled processing means no new derivation, not data loss: preserved memories remain browsable and historical/offline diagnostics retain honest labels. Empty, unavailable, and stale states are explicit.

## Relay

Relay begins with a counts-only owner overview. An owner is the integration-supplied identity namespace (`actor_ref`) that prevents different people or configurations from sharing Relay names and sessions; it is not an agent. Choosing an owner is required before session or message content is shown, so “All owners” remains useful without creating a cross-owner detail read.

For one owner, named and unnamed sessions appear across containers with endpoint ID, alias, runtime/native reference, container/repository metadata, lifecycle, last-seen, and persisted destination health when available. Containers come from Relay session check-ins, are ranked by active sessions, show active/total counts, and can be searched beyond the first page. Container is provenance/filter metadata, not a hidden communication boundary. Runtime discovery and wake outcome are shown only when recorded; otherwise they are unavailable.

The default session list shows the participants in the current bounded message window, with recent (24-hour) sessions as the default scope; the full recent-session list is an explicit browse action. The communication map and recorded-message timeline stay visible together on desktop, and message detail opens beside a bounded scrolling list. Reciprocal traffic is collapsed into one bidirectional connection with per-direction counts; native zoom, fit, keyboard interaction, and a linear message alternative keep dense graphs inspectable. Nodes are persisted endpoint IDs and connections are persisted communications. Legacy null endpoint IDs remain unknown and duplicate native IDs are never rebound.

The graph and message list use the same bounded, redacted projection, filters, fixed `until` boundary, and deterministic `(created_at, id)` ordering. The window is labelled partial until its bounded pages are fully loaded. Delivery state, lifecycle, effective expiry, reply links, selector-at-send, and timing are inspectable without claim tokens or receipts. Durable year-9999 expiry renders as no practical expiry; delivery admission never implies recipient action.

Aliases are optional addressing metadata. Save, transfer, or remove is an explicit action through canonical naming semantics. A conflict is a visible 409 requiring a separate confirmation/retry against the selected endpoint identity; no silent rebinding occurs.

## Read behavior and states

Dashboard projections are bounded app-local reads over existing records and allowlisted report files; they do not alter storage, claim deliveries, expand context, or expose pre-redaction content. Every panel has honest loading, empty, error, stale, and partial states with retry or next-page affordances. Narrow layouts stack capability cards and Relay panes without page overflow; keyboard users can reach tabs, collapsibles, filters, list/detail controls, graph nodes/edges, aliases, and linear graph alternatives with visible focus and status/error announcements.

## When to use it

- Scan Operations for service and capability health.
- Browse governed Session History and deliberately open bounded context.
- Use Relay to follow a session, pair, reply chain, or expired delivery.
- Use Derived Memory diagnostics only as optional historical/experimental evidence, never as proof of downstream benefit.