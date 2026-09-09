<!-- agent-workflow:start -->
**Outcome:** Developers and agents can associate multiple exact work references with each Relay session, find all participating sessions by one exact reference across worktrees and containers, safely correct current associations, and carry truthful snapshots into subsequent Session History without implying ownership or liveness.

**Target:** Pallium.

**Scope:** Extend the existing Relay endpoint registry and generic work-reference machinery through persistence, HTTP, MCP, supported hook ingestion, the Relay dashboard, documentation, synthetic demo assets, and caller-surface E2E. No second registry or tracker-specific model.

**Constraints:** Preserve canonical Relay endpoint identity, runtime-owned current-session mutation, targeted-only messaging, actor-free cross-container Relay routing, container-scoped History/memory access, immutable historical snapshots, and the five-reference history limit. Association is not ownership, activity, completion, wake, dispatch, or permission. No launcher, tracker sync, orchestration, semantic inference, paid model loop, live installed-service change, or synthetic write to the real history store.

**Completion criteria:** HTTP/MCP/dashboard callers can attach, detach, structurally refresh, read current-session associations, and find plural participants by one exact bounded reference with canonical targets, origins, freshness, lifecycle, and honest unknown availability. Two sessions in different worktrees/containers can share a feature while retaining distinct branch, Work Record, and external refs; an agent selects one exact recipient and completes normal send/reply. Work switching/removal cannot lose unrelated origins, resurrect removed explicit refs, transfer with aliases, or relabel older history. Qualified identities avoid repository/tracker collisions; legacy behavior is explicit. Empty/max/overflow, Unicode, malformed/secret-bearing, concurrency, lifecycle, restart, degraded storage/integration, authorization, and accessibility journeys pass through public surfaces. A runnable isolated synthetic demo and screenshots show the developer journey without modifying the installed service or real history store.

**Risk:** High

**Complexity:** Large

**Reason:** Pre-edit redline reports API_CHANGE plus SCHEMA_CHANGE with red/watch API and persistence surfaces, requiring api-review and persistence-review. The complete feature spans independently verifiable registry, ingestion, HTTP/MCP, dashboard, lifecycle, and history outcomes across multiple sessions.

**Discovery:** In progress. Required source inventory starts from `core/work_ref.py`, Relay core/storage/schema/API/MCP, hook discovery and ingestion, dashboard projections/UI, current tests, and the shipped structural-ref/current-work/exact-search/dashboard records. Pre-edit classification found no existing boundary violation; storage and public contracts must remain layered.

**Material assumptions:** (1) Existing generic work-ref normalization can represent the stable qualified identities without a new reference domain; disproof requires a narrowly reviewed extension, not Relay-specific parsing. (2) Existing Relay endpoint IDs remain the sole association owner and alias transfer never moves associations; any current alias-keyed persistence would stop the design. (3) Hooks can reuse one structural discovery snapshot for both Relay refresh and turn ingestion without a second process or lookup; if timing proves otherwise, ingestion continuity wins and the plan returns to review. (4) Dashboard administrative mutation can reuse existing exact-session authorization; absent such a seam, do not expose arbitrary cross-session mutation until a reviewed contract exists. (5) The five-reference history cap can use a deterministic documented projection with visible overflow while the registry retains a separately bounded superset; if callers cannot see omission, do not ship silent searchability claims.

**Plan:** Pending design discovery and architect review. The implementation will reuse the existing endpoint registry/reference path, add the smallest origin-aware many-to-many persistence and bounded projections, keep agent self-mutation separate from dashboard administration, capture immutable association snapshots before turn ingestion, and extend the existing dependency-free Relay dashboard. Target files and exact stop conditions will be fixed after the design packet is approved.

**Verification plan:** Each completion criterion will map to public HTTP/MCP/dashboard/hook E2E plus focused persistence/lifecycle checks after design approval. Required repository tests, import-boundary/redline/workflow gates, synthetic isolated demo, browser screenshots, and independent result review are mandatory before a review-ready PR.

**Plan review:** Pending clean-context smart review after architect design approval.

**Approvals:** Approved by user 2026-09-09: "you're about to get assigned work from the architect agent, i approve this work and doing PRs"

**Exceptions:** —

**State:** Blocked or returned to planning
<!-- agent-workflow:end -->

## Implementation

2026-09-09 — Created isolated worktree `C:\Dev\rore\Pallium\.worktrees\relay-session-work-associations` on branch `feat/relay-session-work-associations` from `origin/main` `0dbb0691`; design discovery is in progress and no production file has been edited.

## Plan review

Pending architect design review and subsequent clean-context smart plan review.
