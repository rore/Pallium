# Dashboard Operations + Relay workspace

## Product shape

The dashboard is a local, read-only administrative surface for the product as shipped: **Operations** is the default answer to “is Pallium working?” and **Relay** is the place to follow recorded exchanges. Session History is the primary evidence surface; Derived Memory remains optional and must not dominate either view. There is no composer, orchestration control, workflow action, runtime-discovery claim, or delivery-control secret.

## Current panel classification

| Current panel | Production home | Classification / treatment |
|---|---|---|
| Service, queue, ingestion, search, storage/retention health | Operations | **Core/service**; capability health first, counters second. |
| New SourceItem explorer (list/detail) | Operations | **Session History**; governed, explicitly scoped inspection. Separate from the existing derived-memory browser. |
| Historical lookup/reuse activity and usefulness evidence | Operations → offline evidence | **Session History**; preserve retrieval-vs-benefit distinction. |
| Existing Memory Browser, query activity, injection/skip feedback, query debug | Operations → optional capability | **Derived Memory**; preserve existing tooling and keep retrieval diagnostics distinct from benefit. |
| Relay summary tiles and runtime status | Operations summary + Relay | **Relay ops**; summary is a nudge, workspace is the bounded detail. |
| Sessions, messages, deliveries, reply chains, endpoint graph, aliases | Relay | **Relay ops**; observational only. |
| How-memory-helps reports and judge/eval diagnostics | Operations → offline evidence | **Experimental/eval**; last-written, timestamped, denominators and uncertainty visible. |
| Preserved derived outputs and processing state | Operations → optional capability | **Derived Memory**; disabled/enabled/preserved states remain honest. |
| Old memory-centric overview, package-dependent container/actor claims, illustrative mock-only controls | — | **Obsolete**; remove or relocate rather than preserve misleading affordances. |

## Datum and API matrix

| Datum / surface | Decision | Contract and honesty rule |
|---|---|---|
| Existing health, metrics, activity, feedback, query-debug, Relay summary, report readers | Reuse | Keep existing read endpoints and renderers; never turn refresh into a write or lookup. |
| SourceItem list/detail, filters, counts | New app-local projection | `/dashboard/api/*`; caller must provide `container_ref`, `actor_ref`, typed `query_visibility`; omitted/invalid scope is 422. Apply visibility/shared-item actor/forgotten gates before count/order/limit, then per-record defense and shared redaction. |
| Source context | Shipped contract reused explicitly | Detail is telemetry-free. “Surrounding context” alone calls `/source/{id}/context` with identical scope; inaccessible/forgotten content is unavailable, not inferred. |
| History rollups | Shipped file-backed contract | Read allowlisted last-written measurement/judge JSON only. Show generated time, evaluated window, eligible/selected/sample/rated/failed/missing counts, completeness, versions, uncertainty; absent fields stay unavailable. |
| Reuse events and labels | New app-local projection | Bounded scoped event list contains IDs, redacted query text, linkage/rank/score, label/rationale only; no cached SourceItem content. Live detail/context resolves evidence. It is current operational evidence, not exact aggregate-report membership. |
| Relay sessions/messages/deliveries | New app-local projection over shipped Relay records | Read with `_relay_session_factory`; allowlisted scalars only, no claim token/receipt. Actor-domain across containers; no core/storage/API contract changes. |
| Relay aliases | Shipped naming route reused through explicit dashboard action | View is read-only until an explicit save/remove; conflict returns 409 and requires a separate user-confirmed retry against the selected endpoint identity. |
| Runtime discovery, wake-outcome telemetry, new graph aggregate backend | Unavailable / follow-up | Say “not recorded” or “not available”; do not infer from container, delivery admission, or partial data. |

## Information architecture and journeys

Operations opens with one non-collapsible Overview containing separate SourceItem and all Memory-object inventories, the operating summary, and System Health. Non-collapsible Relay Health follows, then Session History with always-visible KPIs and a collapsed browser; Derived Memory is last and follows its enabled state (open when enabled, collapsed when disabled). Source browsing is a compact master/detail surface: plain-language Owner/Workspace scope → recent browse or word search → selected governed detail beside a bounded list → explicit bounded context → no mutation. The useful journey is ingest → scoped list/search/filter → detail → context → forget → absence, with refresh producing no context event.

Relay starts with a counts-only owner overview. “Owner” is the integration-supplied identity namespace (`actor_ref`), not an agent; all-owner mode never unions session or message content. After an owner is selected, the workspace shows current-window participants on the left and keeps the communication map, bounded message timeline, and selected-message detail together on the right. Browsing the full recent-session population is explicit rather than the default. Select a node/connection to filter messages; select a message to inspect delivery/reply detail; parent links navigate reply chains. Alias management lives in the selected endpoint detail and is absent from message detail. The expired-delivery alert deep-links to Relay with the expired filter selected.

Everyday journeys are: (1) confirm service/history/Relay health in one glance; (2) inspect one recorded turn and deliberately open its context; (3) explain a pending/expired/delivered exchange without claiming recipient action; (4) follow a cross-container exchange and resolve a canonical alias conflict; (5) distinguish an offline evaluation result from real-task benefit; (6) browse preserved memories while processing is disabled.

## State contract

Every panel has explicit **loading** (stable skeleton/“Loading…”; controls remain labelled), **empty** (what zero means and the next useful action), **error** (human-readable cause, retry, no fabricated counts), **stale** (last generated/observed timestamp plus offline/stale label), and **partial** (bounded window/count disclosure and next-page affordance) states.

| Surface | Empty / loading / error / stale / partial specifics |
|---|---|
| Operations health | Loading placeholders; “No recorded work yet” is valid; unavailable capability is distinct from failure; service/API error banner with retry; stale last-seen timestamp; never mark Relay pending as failure. |
| SourceItem / History | Empty says no rows match this governed scope; missing scope/invalid enum is 422; missing/deleted/forgotten detail is unavailable; context failures stay local to the context region; reports missing or incomplete say “not generated / not measured,” not zero. |
| Relay sessions | Empty distinguishes no known sessions from no matching filter; split Relay DB unavailability is explicit; unknown legacy endpoint identity is shown as unknown, never rebound. |
| Relay messages/map | Loading uses the same window for list and graph; no messages says no exchange in this selection; delivery/detail errors preserve the list; effective expiry is evaluated at one request timestamp; graph is labelled partial until the bounded window is fully loaded. |
| Pagination | Fixed requested `until` boundary and deterministic `(created_at, id)` descending order; concurrent inserts do not move earlier pages. Show loaded/total-known and “load more”; never present a bounded slice as complete history. |

## SourceItem scope, governance, and evidence

Dashboard reads are not an authorization boundary on localhost. Session History reads still require explicit container, actor, and visibility scope. Relay may list per-owner aggregate counts without a selected actor, but session/message content requires one exact `actor_ref`; it never exposes a cross-owner union. SQL filters visibility, shared-item actor rules, lifecycle/forgotten state, and filters before pagination/counts; deterministic ordering is `(effective timestamp, id)`. A per-record visibility/filter defense and shared ingest redactor protect legacy content and metadata, with the intentional note carve-out preserved. No list refresh expands context or creates a lookup event. Evidence links carry the same scope; if the item is inaccessible, forgotten, or deleted, render an unavailable link and no excerpt. Retrieval, judge calibration, candidate recovery, injection precision, and downstream-task effect remain separate claims; no dashboard wording equates retrieval with benefit.

## Relay semantics and graph/list consistency

Relay reads use the Relay-specific database factory and expose only safe post-redaction fields. Nodes and edges are keyed by persisted endpoint IDs. A null/legacy endpoint ID remains an unresolved/unknown node; duplicate native IDs in different containers are never rebound. Lifecycle state and persisted destination health are separate labels. Effective expiry is computed read-only at the request timestamp; durable year-9999 expiry renders as no practical expiry (`null`), while an actually expired message remains inspectable. Pending means retained for an eligible recipient turn; delivered means admitted to the recipient session, not that it acted; wake outcome is not recorded.

The list and graph consume the same bounded message/delivery projection, with the same filters, reply IDs, redaction, ordering, and fixed `until` boundary. Reciprocal directed rows are collapsed client-side into one bidirectional connection while preserving per-direction counts and delivery-state summaries; self-messages remain self-loops. The map initially fits the rendered projection to its pane, hides browser scrollbars, pans by dragging its background, and permits node dragging for manual untangling; native zoom and Fit reset operate only on that projection. The graph caption reports the window and says partial until all pages are loaded; it never invents missing edges. Delivery detail includes state, send-time selector, endpoint identity, lifecycle timing, and parent link, never claim tokens or receipts.

## Alias confirmation flow

Saving/removing an alias is an explicit action on the selected endpoint. On a 409 conflict, preserve the typed value, identify the current owner, and require a separate confirmation/retry; do not silently transfer. A confirmed transfer uses the selected endpoint’s persisted container/runtime/session identity and the existing canonical naming route. Duplicate names remain rejected; empty alias means unnamed. Success and conflict are announced in a live status region.

## Accessibility and responsive behavior

Use native buttons, links, forms, `details`, tables, and selects with accurate labels and status/error regions. Tabs expose selected state; only subordinate browsers and diagnostics collapse, while Overview, Relay Health, and Session History KPIs remain visible. Every row, graph node, graph edge, message, alert, and deep link is keyboard reachable with visible focus and an accessible name; graph has a linear list alternative, and selection is never color-only. Preserve focus after refresh/detail changes and announce loading/errors/status changes. Avoid horizontal page overflow: desktop uses two-pane Relay and multi-column cards; at ≤820px Relay stacks sessions above content and cards become one column; at ≤520px detail panels and toolbar stack, graph pans within its own bounded region, and table/detail controls remain usable with large text and wrapped IDs.

## Implementation and visual principles

Retain the dependency-free single `app/dashboard.html` with inline CSS/JS and no build step; existing HTML-substring contracts and renderers make a framework or split bundle needless. Keep `app/dashboard.py` projections app-local and bounded. Visual language is quiet dark operational density: capability ownership, clear hierarchy, restrained blue/teal/amber/red status, readable monospace IDs, progressive disclosure, stable layout during refresh, and honest uncertainty. Use color plus text/icon, generous focus states, consistent spacing, and the same data window for every representation. The HTML mock is interaction guidance, not API truth; production states and governed data win.
