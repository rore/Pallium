<!-- agent-workflow:start -->
**Outcome:**
The local dashboard presents Pallium as Relay + Session History through a polished, usable Operations view and observational Relay workspace, while optional Derived Memory remains available without dominating the product.

**Target:**
Pallium dashboard.

**Scope:**
Dashboard-only read projections and UI in `app/dashboard.py` and `app/dashboard.html`; dashboard/API/browser E2E tests; `docs/dashboard.md`, the Operations/Relay UX design artifact, roadmap status/alignment, and the public dashboard screenshot. No core Relay, storage schema, or general API contract changes.

**Constraints:**
Preserve Relay actor-scoped routing/naming semantics and Session History visibility, redaction, retention, and forgetting; never expose delivery-control secrets or pre-redaction payloads; no composer, orchestration, workflow controls, runtime discovery claim, heavy frontend stack, or paid work during refresh; remain useful with all semantic packages disabled.

**Completion criteria:**
Operations defaults to accurate capability-oriented health and explicitly scoped, governed SourceItem inspection; Session History usefulness shows last-generated measurement/judge coverage, denominators, completeness, versions, uncertainty, and governed evidence journeys without equating retrieval with benefit; Relay shows actor-domain named/unnamed sessions, bounded persisted message/delivery history, cross-container observational edges, legacy/unresolved identity honestly, and canonical alias management; Derived Memory disabled/enabled/preserved states remain honest and usable; caller-surface edge-case E2E, responsive accessibility checks, live desktop/mobile visual QA, documentation, and screenshots pass.

**Risk:**
Elevated

**Complexity:**
Large

**Reason:**
Redline found guarded `app/**` paths blue and the required public screenshot under unclassified `assets/**` gray, with no boundary violation. Large because SourceItem exploration, Relay session/message projections, graph/naming interaction, package-state relocation, and full lifecycle/browser validation are independently verifiable outcomes.

**Discovery:**
`origin/main` at `ca9c864b58f1afc1661b34d077a297d0e2892f8e` contains PR #133. Exact Relay selectors and aliases route actor-wide across containers, but `/relay/sessions` and `relay_list_sessions` remain container-local; dashboard actor-domain session/message projections are therefore new bounded reads. Existing dashboard container/actor/activity endpoints are memory-backed and fail the package-free product model. SourceItem records contain the required governed metadata; bounded context already exists at `/source/{id}/context`. Relay message/delivery records contain post-redaction payload, endpoint/container, reply, lifecycle, attempt, and timing data but no list projection or wake-outcome telemetry. The existing vanilla UI, metrics, Relay summary, Memory Browser, Query Debug, and report readers are reusable. The roadmap and `docs/dashboard.md` still describe the cross-container dependency or old memory-centric surface and must be aligned. The UX mock is interaction guidance, not visual/API truth; it needs production density, complete-window graph semantics, keyboard graph handling, collapse preference persistence, and real empty/error states.

**Material assumptions:**
- Dashboard projections may read the existing SQLite ORM records in `app/dashboard.py`, matching the current dashboard summary pattern. Source list/detail require explicit `container_ref`, `actor_ref`, and typed `query_visibility`; omitted/invalid scope is 422. SQL applies the same visibility plus shared-item actor rules before count/order/limit, excludes forgotten rows, and a per-record `source_item_matches_filters`/`is_visible` defense plus the shared ingest redactor protects legacy content/metadata while preserving the intentional note carve-out. Detail is a read-only projection, not context expansion. The explicit surrounding-context action alone calls `/source/{id}/context` with the same scope so refresh does not manufacture lookup/expansion events. Any need to alter storage/core/API surfaces invalidates the redline classification and returns the task to planning.
- Localhost remains a single-user administrative boundary; `actor_ref` and visibility inputs scope reads but are not authentication. Evidence of a different authorization requirement stops implementation for product/security review.
- Native runtime session discovery remains out of scope because no safe shipped discovery contract was found; if one is discovered during implementation, record it as a follow-up rather than silently expanding scope.
- The existing historical measurement and judge CLIs can write aggregate-only JSON to fixed `.local/research/historical_lookup_measurement.json` and `.local/research/historical_lookup_judge.json` paths without producer changes. The dashboard reads only these files for rollups and requires explicit validation/completeness metadata for positive claims; missing artifact fields remain unavailable, never inferred. Because those reports contain no event/source IDs, a separate bounded `/dashboard/api/history/reuse-events` projection reads existing `HistoricalLookupReuseEventRecord` and append-only label rows with the same required container/actor/visibility scope. It returns identifiers, redacted query text, linkage, rank/score and label/rationale only—never cached SourceItem content. Request, exposed-history, and subsequent-context evidence is resolved live through the governed SourceItem detail/context surfaces, so forgotten/inaccessible IDs become honest unavailable links rather than leaked excerpts. The event explorer is operational evidence and is not represented as the exact aggregate report sample.
- One shared, explicitly bounded Relay message window from the Relay-specific session factory can drive both the explorer and graph; if realistic data shows unacceptable volume/latency, stop and plan a separate aggregate backend rather than presenting partial counts as complete.

**Plan:**
1. Finalize the design artifact with current-panel and required-datum matrices, interaction/state rules, responsive/accessibility requirements, and the decision to retain the dependency-free HTML while simplifying its information architecture.
2. Add the smallest bounded dashboard read projections in `app/dashboard.py`: package-neutral metadata/health; SourceItem list/detail with required caller container/actor/visibility, SQL-before-pagination visibility/actor/forgotten gates, deterministic `(effective timestamp, id)` ordering, shared filter/visibility defense, and post-read redaction; actor-domain Relay sessions; and paginated message+delivery history. Keep detail reads telemetry-free; the explicit context action reuses `/source/{id}/context` with identical caller scope. Reuse existing models, validators, naming, and summary surfaces; do not modify core/storage contracts.
3. Extend the file-backed report allowlist with `historical_lookup_measurement` and `historical_lookup_judge` for aggregate rollups, and add a separately bounded, explicitly scoped `/dashboard/api/history/reuse-events` projection over existing event/label records for navigable evidence. Render evaluated window, generated time, selection/eligible/sample/rated/failed/missing counts, uncertainty and version fields when present; classify missing/incomplete/unvalidated/self-match/event-order/excerpt evidence honestly. The event projection returns no cached SourceItem content: task/request IDs, exposed source IDs, expansion links, and append-only labels resolve live through the same scoped SourceItem detail/context endpoints, where forgotten or inaccessible items become unavailable. Clearly label event browsing as current operational evidence, not the exact aggregate report sample. Include reuse, no-reuse, and insufficient-evidence journeys; judge calibration remains reference-set validation, not real-world benefit.
4. Rework `app/dashboard.html` around Operations and Relay. Preserve the visual foundation and renderers, relocate existing panels under owning capabilities, implement progressive disclosure and compact master/detail browsing, derive the graph from the same bounded message window, and retain honest optional/offline states.
5. Relay reads use `storage._relay_session_factory`, an allowlisted response with no claim token/receipt, and endpoint IDs for nodes/edges. Legacy null endpoint IDs stay unresolved/unknown and duplicate native IDs are never rebound. Effective expiry is computed read-only at one request timestamp; durable year-9999 expiry renders null; lifecycle and persisted destination health remain distinct. Pagination uses a fixed requested `until` boundary and deterministic `(created_at, id)` descending order; the graph is labelled partial until the bounded window is fully loaded. Alias transfer is a separate explicit retry after 409, using the selected endpoint record's container/runtime/session identity and existing naming route.
6. Add caller-surface tests for empty/one/max/over-max, omitted/invalid scope, same-container other-actor rows, cross-container private/public/global behavior, redacted metadata, forgotten/retained/deleted rows, Unicode, deterministic and concurrent-insert pagination, preserved Derived Memory, split Relay DB, unresolved legacy endpoints, duplicate native IDs across containers, named/unnamed/multi-runtime/cross-container Relay, reply chains, effective/durable expiry, delivery states, no-secret/no-mutation reads, and alias conflict/takeover; add focused browser checks for keyboard/collapse/filter/detail/graph behavior and narrow layouts.
7. Run focused then broader verification, start the isolated service through the repository wrapper when installed-service validation is needed, and visually iterate with Playwright at desktop/mobile using realistic and empty states until alignment and usability are sound.
8. Update `docs/dashboard.md`, UX evidence, screenshot, and roadmap status; run workflow/redline checks, obtain smart final review, address findings, and prepare the PR.

Key conventions: vanilla HTML/CSS/JS with no build step; `/dashboard/api/*` read models; explicit bounded deterministic ordering; native `details`/buttons/forms and accurate ARIA; one message projection shared by graph and list; existing canonical exact selector and `@alias` naming semantics.

Target files/classes: `app/dashboard.py::mount_dashboard`, `app/dashboard.html`, `tests/test_dashboard.py`, focused dashboard browser/E2E coverage under `tests/`, `docs/designs/dashboard-operations-relay-ux.md` (new design record), `docs/dashboard.md`, `assets/dashboard_screenshot.png`, and roadmap feature status/alignment files only.

Stop conditions: any required core/storage/schema/general API edit; evidence that actor/visibility scope cannot be enforced by existing behavior; incomplete Relay graph coverage presented as complete; or material performance failure of the bounded shared message projection.

**Verification plan:**
- When semantic packages are disabled, Operations shall remain useful and SourceItems shall complete ingest → explicitly scoped list/search/filter → detail → bounded context → forget → absence through caller-visible surfaces without refresh-generated lookup events → focused dashboard API/E2E tests.
- When last-generated Session History reports are missing, stale, incomplete, unvalidated, or no-reuse, the usefulness panel shall label that state honestly; separately bounded event/label evidence shall distinguish itself from the report sample and resolve task, exposed-history, and subsequent-context SourceItems live so forgotten/inaccessible links reveal no cached content and no inference is called downstream benefit → report-state, event-pagination/isolation, and governed evidence-navigation E2E tests.
- When derived output exists before processing is disabled, Derived Memory shall show Disabled while preserving governed browsing and honest historical/offline labels → configuration lifecycle E2E plus browser assertions.
- When actor-owned named and unnamed sessions exchange cross-container Relay messages, including split-DB, duplicate-native-ID, unresolved-legacy, durable/expired and concurrent-insert cases, Relay shall show allowlisted sessions, exact endpoint-ID observational edges, fixed-window message/reply/delivery detail, and explicit alias assign/transfer/remove without mutation, secret material, rebinding, or cross-actor leakage → dashboard API E2E seeded through public Relay endpoints plus legacy fixtures.
- Empty/one/max/over-max, Unicode, invalid filters, missing IDs, conflicts, pagination ordering, reply chains, and delivery states shall have explicit observable contracts → parameterized caller-surface tests.
- Keyboard users and narrow/desktop viewports shall navigate tabs, collapsible capabilities, master/detail surfaces, graph alternatives, filters, and alert deep links without horizontal page overflow → Playwright browser checks and retained screenshots.
- Existing dashboard metrics, reports, Memory Browser, Query Debug, service health, and Relay summary shall remain functional → existing dashboard tests plus focused regression tests.

**Plan review:**
Clean-context Astra review approved after two focused revisions; see `## Plan review` and `### Final re-review` below.

**Approvals:**
Not required at this risk level

**Exceptions:**
—

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

- Context/discovery complete on isolated branch `feat/dashboard-operations-relay-workspace` from `ca9c864b58f1afc1661b34d077a297d0e2892f8e`.
- Read-only backend, UX, and redline audits completed. No production or test code edited.
- Smart-model review findings were resolved: SourceItem scope, Session History aggregate/evidence separation, and merged Relay read semantics are explicit. Final re-review approved; ready to implement.
- Material design checkpoint complete: added docs/designs/dashboard-operations-relay-ux.md covering panel/data classification, production journeys and states, governed SourceItem evidence, Relay semantics, consistency, accessibility, responsive behavior, and the dependency-free single-HTML decision.

- Implemented the dependency-free Operations + Relay dashboard shell: persisted capability disclosure, governed SourceItem and reuse-event inspection, and bounded observational Relay sessions/messages/map/alias flow.

- Aligned the dashboard UI to finalized projection contracts: nested source detail/evidence, context-only scope, actor-required Relay pagination, and the canonical alias route.

- Removed superseded dashboard function definitions; finalized source and Relay contracts now have one implementation each.

## Evidence

- Live current dashboard and repository UX mock rendered with Playwright at desktop and mobile widths before implementation.
- Redline pre-edit verdict: blue for app/tests/docs, gray for public screenshot asset, no boundary violation; minimum Risk Elevated.
- `uv run python -m pytest tests/test_dashboard.py -q` -> 40 passed, including effective expiry, naive UTC bounds, fixed-window concurrent insert, governed free-text suppression, and expansion-role projection.
- `node tests/dashboard_plain_language_renderer.mjs app/dashboard.html` -> all renderer cases passed, including producer-shaped multi-rater completeness, Wilson/kappa/calibration objects, and Relay pair-selection contracts.
- `uv run python -m pytest tests/test_cross_container_relay_e2e.py -q` -> 6 passed.
- `uv run python -m pytest tests/test_source_context_visibility.py tests/test_global_visibility.py tests/test_visibility_scope.py -q` -> 49 passed.
- Relevant raw-history lifecycle and Relay split-store matrix -> 20 passed. The optional derived-vector gate could not activate because `usearch` is not installed; its failure is environment-specific and the dashboard does not add or depend on that package.
- `python -m py_compile app/dashboard.py` and `git diff --check` passed.
- Playwright visual QA against the live isolated service passed at 1440px and 430px: zero page/console errors, no body overflow, persisted disclosure state, scroll reset, SourceItem search/detail/provenance/context, Relay graph/list/detail consistency, actual graph-edge click with endpoint-pair preservation, keyboard graph navigation, clear/reset selection, bounded session coverage, out-of-window parent messaging, alias assign/remove, delivery/reply fields, and producer-shaped missing/incomplete/calibrated report states. A 30-node graph fixture retained internal scrolling without page overflow.
- Public dashboard screenshot refreshed from the visually accepted Operations state.
- Skill-feedback audit: all seven triggers were No.

## Result review

Initial clean-context Astra result review required nine changes. All findings were addressed with focused regressions: governed evidence free text; edge pair encoding; producer report schema; effective expiry; UTC bounds; session pagination; scope/selection reset; bounded parent messaging; and classified, independently paged evidence navigation. Astra re-review found three remaining boundary semantics; all are now covered: offset-aware timestamps canonicalize to UTC, default empty measurement calibration yields to populated judge-vs-gold calibration, and persisted null-rung labels render as explicit no genuine reuse. Final clean-context Astra re-review: APPROVED. All prior findings are resolved; bounded history, explicit out-of-window parent states, and observational/non-causal usefulness evidence remain intentional documented limits.

## Plan review

Clean-context review against the Work Record, workflow plan-review requirements, roadmap/UX reference, dashboard code/tests, and merged Relay/SourceItem behavior.

**Verdict: CHANGES REQUIRED.** Resolve the following planning gaps and repeat review before implementation; none presently demonstrates a need for a new core/storage contract.

1. **Specify the SourceItem governance path and scope contract.** The existing dashboard's direct ORM reads establish placement precedent, not a source-access gate. `core.visibility.is_visible` accepts non-global candidates when the query container is absent and does not enforce same-container actor filtering; `get_source_context` defaults missing caller scope to the anchor. Name the explicit caller container/actor/visibility inputs, their missing/invalid behavior, the shared filter/visibility and redaction helpers used by list/detail, and how bounded pagination/counts avoid including inaccessible or forgotten rows. Preserve the intentional note behavior and structural metadata rules. Carry the same scope to context and report-evidence requests; do not infer History authority from a Relay endpoint or its container. Routine list refresh must not invoke context expansion per row and manufacture historical-lookup events. Add explicit tests for omitted scope, other-actor same-container data, cross-container private/public behavior, forgotten/retained/deleted rows, and redacted metadata. Dashboard-only implementation appears feasible using bounded ORM reads plus shared gates, but the present generic instruction to reuse governance is not sufficient to verify that assumption.

2. **Plan the required Session History usefulness surface explicitly.** The roadmap requires evaluated-window/sample/denominator/completeness/version information and task → exposed history → subsequent work evidence navigation, including no-reuse and insufficient-evidence cases. `app/dashboard.py` currently serves only `raw_derived_hybrid`, `derivation_fidelity`, and `reuse_judge_calibration`; the latter validates a judge, not real-task benefit. Existing judge/rollup scripts are available but are not a dashboard report contract. Identify the supported last-generated artifact(s), audit event-time ordering/exact exposed excerpts/self matches/rater completeness as requested, document unavailable fields honestly, and specify governed evidence resolution that cannot serve cached forgotten/private excerpts. Add this journey and stale/missing/incomplete/unvalidated report cases to completion criteria and verification. If meeting it requires an evaluation-producer change outside the recorded scope, return that scope to planning instead of treating panel relocation as completion.

3. **Pin the merged Relay read semantics and corresponding E2E cases.** Read through `_relay_session_factory` (Relay may live in a separate DB), key edges by persisted endpoint IDs, and show legacy null/unresolved endpoint references as unknown rather than rebinding native IDs to a later registration. The migration deliberately never rebinds unresolved rows. Reuse safe scalar formatting/session helpers, but do not reuse `_delivery_view` wholesale (it contains claim tokens/receipts) or `relay_message_status` for refresh (it materializes expiry under a write transaction). Specify read-only effective expiry, durable expiry as null, lifecycle versus destination-health labels, an allowlisted response shape, and one fixed time boundary/tie-break cursor for paginated graph coverage. Add split-DB, unresolved legacy endpoint, duplicate native session IDs across containers, no-secret/no-delivery-mutation, and concurrent-insert pagination checks. Alias transfer must be an explicit user action after conflict, using the selected endpoint's persisted container/runtime/session identity and the existing naming route.

Scope/UX judgment: retaining vanilla HTML, one shared bounded message projection, and app-local administrative read models is proportionate; no graph aggregate service, registry, framework, or schema extension is justified. Preserve memory-only container options when replacing the current selectors so retained memories remain discoverable after source retention. The planned keyboard, narrow-layout, collapse persistence, empty/error, and full-window graph checks are appropriate; implement the panel/datum matrices before layout edits. Roadmap/docs drift from the old container-coupled Relay contract is correctly identified and must be resolved in the final artifacts.

### Re-review

**Verdict: CHANGES REQUIRED.** The explicit SourceItem list/detail scope, shared gates/redaction, telemetry-free refresh, and merged Relay read semantics/tests now address findings 1 and 3 at plan level. Verify that the explicit context action retains the intended actor/visibility contract as part of the caller-surface tests; passing parameters alone is not proof of filtering.

Finding 2 remains blocked on a false artifact assumption: `JudgeReport.to_dict()` in `evals/historical_lookup_judge.py` omits its labels/consensus event IDs and all source references; `compute_reuse_rollup()` in `evals/historical_lookup_measurement.py` also emits aggregates without event/source IDs. The two selected files therefore cannot supply the plan's cited-source evidence journey. An unavailable-fields label does not fulfill a drill-down that is impossible for every artifact these producers emit. Name a concrete evidence source: for example, a separately bounded, explicitly scoped dashboard projection over existing `HistoricalLookupReuseEventRecord`/`HistoricalLookupReuseLabelRecord`, resolving request/exposed/subsequent source references through current governance and marking absent linkage or exact excerpts unavailable. Keep this independently browsed evidence distinct from an exact report sample unless persisted linkage proves membership. Alternatively, explicitly expand scope to an offline artifact-producer change and reclassify/review it. Add the selected data path, provenance limits, and observable evidence-navigation tests to the plan before approval.

### Final re-review

**Verdict: APPROVED. Remaining planning blockers: none.** The separate bounded, scoped reuse-event/label projection supplies a concrete evidence path using existing persistence, while aggregate artifacts remain aggregate-only and are not presented as exact sample membership. Live SourceItem resolution and explicit unavailable-link/excerpt states resolve the last blocker without expanding beyond the recorded dashboard read-model scope or requiring producer/core/storage changes. The prior SourceItem and Relay revisions remain sufficient at plan level.

During implementation, apply the no-cached-content requirement to every event response field, including query text and label rationale; legacy/free-text telemetry must not become a route around current source governance. Include that assertion in the already planned forgotten/inaccessible evidence E2E checks. Final approval of the result still requires the recorded API/browser coverage, visual QA, and docs/roadmap alignment.
- Backend read projections implemented and focused dashboard caller tests added; verification pending.
- Review follow-up complete: activity no longer exposes SourceItem content; Relay list/message filters, lifecycle/health, fixed-window `as_of`, and pagination metadata are covered by focused tests.
- Finalized aggregate usefulness rendering for measurement/judge reports with explicit denominators, completeness, uncertainty, calibration, version, and non-causal language; missing reports fall back to clearly labelled operational reuse evidence.
