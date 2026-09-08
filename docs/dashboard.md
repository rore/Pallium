# Dashboard

The local dashboard presents **Operations** (the default) for service and capability health and **Relay** for recorded sessions and exchanges. An optional **Evaluation** view exposes private product-effectiveness diagnostics only when `[features].dashboard_roi` is enabled. The dashboard does not create agents, send messages, assign work, or define workflows.

![Dashboard](../assets/dashboard_screenshot.png)

## Access

- Service mode: http://localhost:19836/dashboard
- Dev mode: http://localhost:8000/dashboard

The default service binds locally and the dashboard has no authentication. If a deployment exposes the service beyond localhost, protect the whole API and dashboard at the network boundary. Session History scope fields constrain reads but are not authentication.

## Operations

Operations opens with an always-visible Overview: separate totals for original Session History source items and all stored Memory objects, the current operating summary, and System Health. System Health reports semantic-search readiness, absolute database inventory, and current/24-hour processing counts without inventing capacity limits or success rates. Relay Health follows as an always-visible status surface, then Session History. Only the Session History browser and lower-level diagnostics use progressive disclosure. Pending Relay delivery is neutral; expired delivery and impaired dependencies are called out with actionable links.

### Session History

Session History remains useful with semantic packages disabled. The section shows the total original SourceItem inventory and collapses only its browser. The browser explains what is searchable, accepts a typed workspace plus owner and content/provenance filters, and keeps a compact scrolling list beside a selected detail pane. The divider between them supports pointer dragging and keyboard arrows; narrow layouts stack the panes. Scrollbars use the dashboard theme.

The current governed projection still requires exact `container_ref`, `actor_ref`, and typed `query_visibility`; omitted or invalid scope is rejected. Visibility, shared-item actor rules, forgotten state, filters, and pagination are applied before counts and ordering, with per-record defense and redaction afterward. Detail is read-only and telemetry-free. An explicit surrounding-context action reuses `/source/{id}/context` with the selected item’s exact scope; refresh does not manufacture lookup events. Unrestricted cross-owner history is intentionally not exposed without a separate authenticated administrative boundary.
### Derived Memory

Derived Memory is optional and last in Operations. Its section is collapsed while derivation is disabled and opens automatically while enabled; its object total remains visible in Overview either way. Existing Memory Browser, query activity, injection/skip/feedback/flag diagnostics, Query Debug, and extraction reports remain here. Disabled processing means no new derivation, not data loss: preserved memories remain browsable and historical/offline diagnostics retain honest labels. Empty, unavailable, and stale states are explicit.
### Evaluation

Evaluation is hidden and its report endpoint returns 404 by default. Set `[features].dashboard_roi = true` or `PALLIUM_FEATURES_DASHBOARD_ROI=true` only on the private installation used for product measurement. The view contains lookup/reuse, candidate-recovery, and fidelity evidence with explicit denominators, timestamps, uncertainty, and “not measured” states; none is presented as proof of downstream benefit.

## Relay

Relay opens directly into recorded activity without an actor/owner picker. During the actor-model transition, the client resolves the most active stored identity namespace internally and keeps all session/message API reads within that exact scope; it does not union private message content across identities. The compatibility step can be removed when the actor-free Relay backend lands.

Named and unnamed sessions appear across containers with endpoint ID, alias, runtime/native reference, container/repository metadata, lifecycle, last-seen, and persisted destination health when available. Containers come from Relay session check-ins, are ranked by active sessions, show active/total counts, and can be searched beyond the first page. The default list shows current-window participants; full recent-session discovery is explicit.

The communication map and recorded-message timeline stay visible together. The map initially fits the complete loaded projection, hides browser scrollbars, pans by background drag, allows node dragging, and provides zoom and Fit controls. Reciprocal traffic collapses into one bidirectional connection while preserving direction counts. Messages are newest-first with recorded time visually primary; selected delivery detail stays beside the bounded scrolling list. Aliases are endpoint-only and disappear from message detail. The expired-delivery KPI in Operations opens Relay with the expired filter selected.

The graph and list use the same bounded, redacted projection, fixed `until` boundary, and deterministic `(created_at, id)` ordering. Legacy null endpoint IDs remain unresolved. Delivery admission never implies recipient action, and claim tokens or receipts are never exposed.
## Read behavior and states

Dashboard projections are bounded app-local reads over existing records and allowlisted report files; they do not alter storage, claim deliveries, expand context, or expose pre-redaction content. Every panel has honest loading, empty, error, stale, and partial states with retry or next-page affordances. Narrow layouts stack capability cards and Relay panes without page overflow; keyboard users can reach tabs, collapsibles, filters, list/detail controls, graph nodes/edges, aliases, and linear graph alternatives with visible focus and status/error announcements.

## When to use it

- Scan Operations for service and capability health.
- Browse governed Session History, resize list/detail as needed, and deliberately open bounded context.
- Use Relay to follow a session, pair, reply chain, or expired delivery.
- Use Derived Memory for optional memory/search diagnostics; use the private Evaluation view for ROI research, never as automatic proof of downstream benefit.