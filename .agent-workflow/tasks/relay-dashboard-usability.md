# Relay dashboard usability

<!-- agent-workflow:start -->
**Outcome:** The live Relay dashboard starts with an understandable owner overview and provides a usable, visually verified workspace for finding active containers, sessions, conversations, and delivery detail.

**Target:** Pallium dashboard.

**Scope:** Relay dashboard read projections, vanilla HTML/CSS/JS interaction and layout, focused caller-surface tests, dashboard design/docs, and visual evidence.

**Constraints:** Preserve actor-domain isolation, bounded secret-free reads, canonical Relay identity/naming semantics, keyboard accessibility, and the no-composer boundary. Add no frontend framework or dependency. Keep this branch open and do not create a PR until the user finishes the wider dashboard improvement round.

**Completion criteria:** (1) When no owner is selected, the Relay view shall explain the owner boundary and show useful owner activity summaries instead of an empty workspace. (2) When an owner is selected, containers and sessions shall default to recent activity, rank active containers first, and keep dormant/history records behind explicit controls. (3) When a session, graph node, connection, or message is selected, the graph, message list, and visible detail shall stay in one context without an implicit view switch. (4) At realistic high cardinality and narrow/desktop widths, the graph shall remain navigable with zoom/reset controls and the session/message/detail surfaces shall remain readable. (5) The dashboard API shall remain bounded, actor-isolated, deterministic, read-only, and free of delivery-control secrets.

**Risk:** Routine

**Complexity:** Moderate

**Reason:** Redline classifies every intended dashboard, test, docs, and roadmap path blue with no boundary findings or required checkpoint. Moderate complexity reflects coordinated read-model, interaction, responsive-layout, and real-data visual changes.

**Discovery:** The live database contains 8 actors, 837 Relay sessions, 1,136 messages, and 251 unranked container options. `Rotem Hermon` owns 666 sessions and 1,134 messages; only 16 sessions have aliases. The initial Relay load races actor population: the dropdown can display `Cabinet` while the workspace says no actor is selected. Blank `actor_ref` cannot call the actor-required session/message projections. The current circular graph expands with node count, draws crossing straight edges, and replaces itself with the message list on selection. Message detail renders below the full list. Existing projections already preserve actor isolation, redaction, pagination, fixed-window ordering, lifecycle, and effective-expiry semantics.

**Material assumptions:** The localhost dashboard may summarize counts across actor identities, but session/message content remains actor-scoped; disprove if product policy treats even cross-actor aggregate counts as private, then require explicit actor selection with no aggregate counts. Existing `recent` lifecycle (seen within 24 hours) is the correct default active-session definition; disprove through live-data review, then adjust the label/window without changing Relay storage semantics.

**Plan:** First add one bounded Relay overview projection that returns aggregate owner summaries without content and, for one actor, ranked container/session activity facets. Preserve the existing actor-required session/message endpoints. Then replace the flat initial filters with an explanatory owner overview and an actor-scoped workspace defaulting to recent sessions; expose dormant/history as explicit choices and make container selection searchable/ranked without a new dependency. Keep graph, conversation list, and sticky detail visible together; use native SVG grouping plus zoom/reset controls and aggregate repeated pair edges rather than adding a graph library. Reuse existing selection, pagination, naming, redaction, and endpoint helpers. Update focused API/renderer contracts, docs/design notes, and visual screenshots. Stop and return to planning if aggregate owner counts violate actor policy, if a usable graph requires unbounded reads, or if intended changes cross Relay routing/storage boundaries. Key conventions: vanilla single-file UI, public HTTP surface tests, deterministic bounded reads, readable short container labels with canonical refs only in detail. Target files: `app/dashboard.py`, `app/dashboard.html`, `tests/test_dashboard.py`, `tests/dashboard_plain_language_renderer.mjs`, `docs/dashboard.md`, `docs/designs/dashboard-operations-relay-ux.md`, related roadmap feature status, and dashboard screenshot.

**Verification plan:** (1) No owner selected shows explanations and accurate owner summaries -> focused dashboard API + renderer/browser contract. (2) Selected owner returns recent-first sessions and ranked containers, with explicit dormant/history controls -> API edge-case tests and live database browser check. (3) Selections preserve the combined map/list/detail context -> renderer interaction contract and desktop browser exercise. (4) High-cardinality and responsive views stay usable -> realistic live corpus screenshots at desktop and narrow widths, including zoom/reset and sticky detail. (5) Read behavior remains bounded/isolated/secret-free -> existing and added dashboard projection E2E tests, then affected subsystem and full suite before review.

**Plan review:** Clean-context review completed on 2026-09-08 in `## Plan review`; the resolved implementation conditions and caller-surface checks there are part of this plan.

**Approvals:** Not required at this risk level.

**Exceptions:** —

**State:** Ready to implement
<!-- agent-workflow:end -->

## Plan review

Reviewed on 2026-09-08 by the clean-context reviewer against the Work Record, repository AGENTS.md, agent-workflow skill/operating mode and plan checkpoint, dashboard projections/UI/tests, and `docs/designs/dashboard-operations-relay-ux.md`. The requested `.claude/skills/agent-workflow/SPEC.md` is absent; the installed checkpoint and operating-mode instructions provide the applicable readiness rules. No product code was changed.

Decision: acceptable with the following resolved conditions incorporated into implementation and verification. The dependency-free dashboard projection plus native controls/SVG is the smallest viable architecture; no new graph backend, storage contract, framework, cache service, or alias behavior is needed.

1. **Owner aggregates and isolation.** The design identifies this as a localhost administrative surface, and existing `/dashboard/api/actors` and `/dashboard/api/relay/summary` already expose owner identities and cross-owner totals. This supports a deliberately limited aggregate overview, not cross-owner session inspection. Without an owner, allowlist only actor identity, aggregate session/message counts, and aggregate activity timestamps; never include container refs, session refs/IDs, titles, aliases, payload previews, selectors, or deliveries. Selected-owner facets must apply actor predicates before grouping/counting/ordering/limiting and use `_relay_session_factory`. Count messages separately from session/delivery joins to prevent fanout multiplication. Unknown owners return a truthful empty projection. Test two owners sharing a container/native session identity, message fanout, and split Relay storage; assert exact keys and that detail endpoints still reject omitted/blank actor scope. Aggregates are a deliberate documented administrative exception, not a claim of caller authentication.

2. **Bounded reads and meaningful activity.** A response limit alone does not bound SQL work. Use a fixed number of grouped scalar queries, no per-owner/container queries or Python materialization of every session/message, and cap returned owner/container facets (default 100, maximum 200) with a truthful pagination/search continuation. SQL aggregate scans may still scale with stored rows; disclose that ceiling and check representative query plans/latency rather than claiming constant work. Load facets on entry/scope change/explicit refresh, not on the existing periodic health cadence. Container rank is recent nonclosed session count descending, then latest last-seen descending, then canonical container ref for deterministic ties; do not label recent-but-unreachable sessions healthy. Compute all lifecycle counts against one request timestamp using the existing 24-hour boundary; closed remains separate. State exactly whether container counts describe all sessions or the selected lifecycle. No schema/index changes are authorized by this plan; return to planning if measured cost requires them.

3. **High-cardinality discovery and async scope correctness.** Search must reach containers beyond the first facet page; a client filter over only the first 100 is insufficient. Use bounded server search or explicit accessible paging, retain a selected option even when it is outside the current results, and disambiguate identical short labels while retaining canonical refs in detail. Owner selection is explicit and blank remains blank after asynchronous actor loading. Every owner/filter reset immediately clears old sessions, messages, selection, detail, pagination/window, and graph state; capture a request generation/scope and ignore stale success and error responses from refresh/load-more requests. Do not derive the full runtime option list from the currently runtime-filtered page. These requirements address observed `fetchActors`, `fetchRelay`, and `fetchRelaySessions` races without introducing a state framework.

4. **Graph/list/detail contract.** Derive graph edges and the message list from the same bounded message/delivery window. Aggregate only repeated directed endpoint pairs; preserve direction, fanout, and mixed delivery states without inventing an aggregate delivery outcome. Include endpoints found in messages even when absent from the recent/paginated session list, with an explicit unresolved metadata label; never infer canonical identity from native session names. Keep unknown legacy endpoints unknown. The partial caption must distinguish loaded message window, local selection, and incomplete session metadata: an empty selected subset does not prove no recorded conversation exists. Expose load-more or existing endpoint/pair API filtering when the chosen session has no matches in the loaded global window. Selection and parent navigation keep map, list, and detail visible, clear an out-of-context detail, and retain keyboard focus. Zoom/reset must fit the complete loaded graph in its bounded viewport; if any visual cap is introduced, disclose it and retain a complete list alternative. Do not silently drop nodes to make the screenshot readable.

5. **Verification strengthened to caller behavior.** Extend `tests/test_dashboard.py` with HTTP-surface tests for empty/unknown owner; exact aggregate field allowlist and isolation; deterministic ties; facet limit 1/200/201 and invalid/blank filters; high-cardinality paging/search; recent cutoff, dormant, closed, unreachable, and Unicode labels; split storage and fanout counts; repeated reads leaving Relay state unchanged. Retain existing secret, expiry, and fixed-window pagination tests. Extend `tests/dashboard_plain_language_renderer.mjs` beyond the existing pure pair-selection assertion to exercise actual Relay event handlers and deferred fetch completions: blank initial owner, A-to-B and A-to-blank switches with A completing last, stale errors/load-more, filters, selection clearing, parent chain longer than two, unknown endpoints, repeated directed edges, and visible map/list/detail together. A pure markup substring assertion does not discharge these interaction contracts. Record real browser journeys for owner overview -> container -> session/node/pair -> message -> parent -> clear/change owner, keyboard activation/focus, zoom/reset, API error/retry, and desktop/narrow widths. Use anonymized synthetic labels for new checked-in fixtures and visual evidence. Screenshots supplement these checks rather than proving races or API isolation. The affected subsystem suite and one full suite remain required before result review, even while PR creation is deferred.

6. **Documentation drift.** The current design specifies mutually exclusive Map/Messages views and postpones graph aggregates; revise it to the combined workspace and explain that pair aggregation is client-side within a bounded window. Document the aggregate-only owner overview exception, recent-session default, facet pagination/search, and completeness wording in dashboard docs. Update only the relevant roadmap feature state once implemented and verified; this review does not declare the feature shipped.

## Implementation

Pending.

## Evidence

Pending.

## Result review

Pending.
