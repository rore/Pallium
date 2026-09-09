<!-- agent-workflow:start -->
**Outcome:** Developers and agents can associate multiple exact work references with each Relay session, find all participating sessions by one exact reference across worktrees and containers, safely correct current associations, and carry truthful snapshots into subsequent Session History without implying ownership or liveness.

**Target:** Pallium.

**Scope:** Extend the existing Relay endpoint registry and generic work-reference machinery through persistence, HTTP, MCP, supported hook ingestion, the Relay dashboard, documentation, synthetic demo assets, and caller-surface E2E. No second registry or tracker-specific model.

**Constraints:** Preserve canonical Relay endpoint identity, runtime-owned current-session mutation, targeted-only messaging, actor-free cross-container Relay routing, container-scoped History/memory access, immutable historical snapshots, and the five-reference history limit. Association is not ownership, activity, completion, wake, dispatch, or permission. No launcher, tracker sync, orchestration, semantic inference, paid model loop, live installed-service change, or synthetic write to the real history store.

**Completion criteria:** HTTP/MCP/dashboard callers can attach, detach, structurally refresh, read current-session associations, and find plural participants by one exact bounded reference with canonical targets, origins, freshness, lifecycle, and honest unknown availability. Two sessions in different worktrees/containers can share a feature while retaining distinct branch, Work Record, and external refs; an agent selects one exact recipient and completes normal send/reply. Work switching/removal cannot lose unrelated origins, resurrect removed explicit refs, transfer with aliases, or relabel older history. Qualified identities avoid repository/tracker collisions; legacy behavior is explicit. Empty/max/overflow, Unicode, malformed/secret-bearing, concurrency, lifecycle, restart, degraded storage/integration, authorization, and accessibility journeys pass through public surfaces. A runnable isolated synthetic demo and screenshots show the developer journey without modifying the installed service or real history store.

**Risk:** High

**Complexity:** Large

**Reason:** Pre-edit redline reports API_CHANGE plus SCHEMA_CHANGE with red/watch API and persistence surfaces, requiring api-review and persistence-review. The complete feature spans independently verifiable registry, ingestion, HTTP/MCP, dashboard, lifecycle, and history outcomes across multiple sessions.

**Discovery:** Current main stores work refs only on immutable SourceItem metadata (`pallium_work_refs`, normalized/deduplicated, maximum five). Hooks discover bare `git-branch:*` and `agent-workflow:*` refs, choose the first structural ref for scalar current-work injection, and independently rediscover at user/assistant ingestion. Relay persists endpoint identity/lifecycle/alias but no work refs; container-local recipient listing and the service-global dashboard are separate projections. Alias release/transfer does not replace endpoint identity, close retains the endpoint, and a turn reopens that exact endpoint. Minimap has no reusable identity helper yet; its queued companion explicitly makes Minimap the producer of a repository-plus-roadmap-root-qualified item ref and Pallium the association owner. Pre-edit redline classification is API_CHANGE plus SCHEMA_CHANGE, Risk High / Complexity Large, with API and persistence review required and no existing boundary violation.

**Material assumptions:** (1) A small generic `work:v1:<32-hex-scope-digest>:<normalized-local-ref>` envelope can reuse current normalization while leaving producer semantics outside Relay; if API review rejects this shared envelope, return to planning rather than accept unqualified cross-container collisions. (2) Existing Relay endpoint IDs remain the sole association owner; alias transfer never moves rows. (3) The trusted hook/MCP identity seams can resolve the current endpoint without adding model-supplied runtime/session arguments; if a supported runtime cannot do so, its mutation tool fails closed and the feature does not weaken identity. (4) Dashboard correction remains a trusted-local administrative operation on one exact endpoint ID, matching the current dashboard trust boundary. (5) Maximum 20 explicit plus five structural refs is adequate for the first slice; the history projection remains five and visibly reports omissions. (6) No physical endpoint deletion/pruning exists today; retained associations cascade on any future deletion and test cleanup disposes only the isolated database.

**Plan:** Pending architect design review. After approval: (1) add the Work Record's reviewed API/persistence checkpoints and get clean-context smart plan review; (2) add one endpoint-owned origin table and generic qualification/validation helper; (3) extend Relay core/HTTP with atomic structural refresh, current-session explicit attach/detach/read, and exact-ref participant lookup; (4) expose four narrow MCP tools using the receive path's runtime-owned identity resolver; (5) make supported hooks refresh at turn admission and capture immutable post-refresh/current snapshots for user/assistant ingestion; (6) extend the existing dependency-free dashboard with exact-ref filtering and exact-endpoint explicit correction; (7) add focused persistence/API/MCP/hook/dashboard tests, then the required public-surface E2E, isolated synthetic demo, docs, screenshots, full suite, workflow/redline gates, and independent smart result review. Stop and return to planning on identity weakening, silent history overflow, container/history access widening, or a required tracker/runtime-specific Relay abstraction.

**Verification plan:** Public-surface E2E will cover register -> structural refresh -> explicit attach -> plural cross-container lookup -> exact send/reply -> work switch -> detach -> close/include-inactive -> reopen -> isolated cleanup. Boundary cases cover empty/duplicate/max/over-max, origin overlap, concurrent refresh/attach/detach, alias transfer, restart, Unicode and escaped refs, invalid/unqualified/secret-bearing refs, missing/current-vs-other endpoint mutation, unavailable snapshot service, delayed ingestion after detach, stable same-repo worktree scope, distinct repository/roadmap/tracker scopes, exact non-transitive lookup, and no message/claim/history-permission side effects. Dashboard browser tests and screenshots cover loading/empty/error/overflow/inactive states and keyboard access. Run focused nodes, affected files, `--lf`, full `tests/ -x -q`, import/workflow/redline checks, then a clean-context smart review before PR handoff.

**Plan review:** Pre-edit classifier: MIXED -> API_CHANGE + SCHEMA_CHANGE, High/Large; API and persistence review required. Architect contract review and clean-context smart implementation-plan review are pending.

**Approvals:** Approved by user 2026-09-09: "you're about to get assigned work from the architect agent, i approve this work and doing PRs"

**Exceptions:** —

**State:** Blocked or returned to planning
<!-- agent-workflow:end -->

## Design review packet

### Exact workspace

- Worktree: `C:\Dev\rore\Pallium\.worktrees\relay-session-work-associations`
- Branch: `feat/relay-session-work-associations`
- Work Record: `.agent-workflow/tasks/relay-session-work-associations.md`
- Base: `origin/main` `0dbb0691d60a98dda06702d6107645af8e842a08`
- Work Record creation commit: `0b543f3e`

### Current versus proposed behavior

Current: Relay endpoints have identity, alias, lifecycle, and delivery health but no work refs. History alone stores at most five bare normalized refs per immutable turn. Hook structural discovery is local, bare, and independently recomputed; recipient discovery is container-local while the dashboard can inspect sessions service-wide.

Proposed: the Relay registry owns bounded endpoint-to-exact-ref rows. Each `(endpoint_id, work_ref, origin)` row records `origin` (`explicit` or `structural`), first association time, and last confirmation time. An exact ref can have both origins. Structural refresh atomically replaces only that endpoint's structural rows; attach/detach mutates only its explicit row. Reads group origins and expose the existing endpoint/lifecycle/destination facts. Alias transfer has no effect. Close retains rows; default participant lookup omits dormant/closed endpoints, `include_inactive=true` returns them labeled; reopen of the same endpoint retains rows. Any future physical endpoint deletion cascades rows.

No ownership, execution, completion, wake, dispatch, role, tracker sync, inference, reference aliasing, transitive expansion, or human message composer is added.

### Reference identity and compatibility

Pallium adds one generic envelope, not producer-specific parsing:

`work:v1:<scope_digest>:<local_ref>`

- `scope_digest` is the first 32 lowercase hex characters of SHA-256 over a producer-owned canonical scope string.
- `local_ref` uses the existing work-ref normalization; the whole value remains at most 128 Unicode code points, leaving 87 for `local_ref`.
- A producer must use stable non-secret scope material. Repository structural refs use the already-resolved canonical Relay container (`git:` remote with credentials removed, or `repo:` root-commit fallback). Minimap defines its scope from canonical repository identity plus normalized repository-relative roadmap root. Tracker producers include canonical tracker authority/project. Absolute checkout paths and credential-bearing strings are forbidden inputs.
- Relay validates the envelope and exact normalized value but never interprets `minimap`, Jira, branch, or Work Record meaning and never performs a network lookup.
- A bare ticket/item key is rejected by association mutation as ambiguous. Existing historical bare refs remain unchanged and exactly searchable; they are not aliases of qualified refs and receive no automatic union/backfill.
- Hook structural output becomes qualified for new turns. The scalar current-work field remains one structurally selected ref with the same selection rule, but its value is the new qualified form. This intentional compatibility change gets Python/OpenCode parity tests and guidance. Old bare history remains under the old exact key; new qualified history is under the new exact key.
- Git repos without a usable remote use the stable root-commit container fallback. Non-git/path containers cannot claim cross-worktree structural identity; they can attach a producer-supplied qualified explicit ref and otherwise report structural association unsupported.

Limits are 20 explicit refs plus five structural refs per endpoint, with deduplication after normalization. The union is at most 25. Subsequent-history projection remains five: reserve the first structural/current-work ref, then refs having an explicit origin in normalized lexical order, then remaining structural refs in discovery order. Every read/mutation reports `included_refs`, `omitted_refs`, and per-association `history_included`; explicit-first ordering is only a storage projection rule, never a preferred-work claim.

### Proposed HTTP contract

All responses use existing validation/error conventions; work-ref participant results carry `contract: "relay-session-work-associations/v1"` so an HTTP consumer can distinguish a valid response. Older services return route-not-found (unsupported); connection/timeout/malformed/over-limit remain distinct client states.

- Extend `POST /relay/turn` request with optional ordered `structural_work_refs: list[str] | null`. `null` preserves old-client behavior; `[]` clears structural rows. Registration/delivery still succeeds if association refresh fails, and the response carries a bounded `work_associations` snapshot plus a non-secret refresh status/warning.
- `GET /relay/sessions/work-refs?runtime=<r>&session_ref=<s>&container_ref=<c>` returns the exact endpoint's grouped association/history snapshot without liveness or message side effects.
- `POST /relay/sessions/work-refs/attach` and `POST /relay/sessions/work-refs/detach` accept `{runtime, session_ref, container_ref, work_ref}` for trusted integrations and return the post-mutation snapshot. Attach confirms freshness; detach is idempotent and reports when the ref remains because structural origin still exists. A missing/closed or mismatched current endpoint fails truthfully; attach never creates a session.
- `GET /relay/work-refs/participants?work_ref=<exact>&include_inactive=false&limit=50&offset=0` performs one service-global exact match, maximum `limit=200`, returning total/page metadata and session rows with canonical `endpoint_id`/exact selector, alias, runtime, container, grouped origins/freshness, state, lifecycle, destination health, last seen, and a derived availability enum (`available`, `unreachable`, `stale`, `closed`, `unknown`) whose raw basis fields remain present.
- Dashboard-only trusted-local correction uses `POST /dashboard/api/relay/sessions/{endpoint_id}/work-refs` with `{action: "attach"|"detach", work_ref}`. It targets one canonical endpoint ID and calls the same Relay service methods; it is not exposed as agent self-mutation.

Association storage writes remain behind `RelayService`; API/dashboard code does not import storage. Structural replacement plus origin upserts/deletes are single SQLite transactions, so concurrent operations cannot erase another origin or unrelated refs.

### Proposed MCP contract

The three current-session tools have no model-supplied runtime/session arguments. They reuse `pallium_relay_receive`'s request-metadata/environment identity resolver and optional injected `container_ref`; resolution fails closed.

- `pallium_relay_work_refs(container_ref: str | None = None)`
- `pallium_relay_attach_work_ref(work_ref: str, container_ref: str | None = None)`
- `pallium_relay_detach_work_ref(work_ref: str, container_ref: str | None = None)`
- `pallium_relay_participants(work_ref: str, include_inactive: bool = False, container_ref: str | None = None, offset: int = 0)`

The participant tool uses the existing bounded MCP text-page pattern, returns plural exact selectors, and never selects, sends, wakes, claims, or broadcasts. Normal `pallium_relay_send`/`pallium_relay_reply` remain unchanged.

### Snapshot timing and failure

At user-prompt admission, the hook resolves the container, discovers and qualifies one ordered structural set, and submits it in `/relay/turn`. The post-transaction response snapshot is copied into that user SourceItem before ingestion. Immediately before constructing the assistant SourceItem, the Stop hook performs the read-only current-session snapshot call and copies that result. Therefore an explicit attach/detach during the turn affects the assistant item but cannot relabel the already captured user item. A delayed/retried ingestion resubmits the captured metadata; ingestion never looks up today's registry state.

If association refresh/read is unavailable, ordinary Relay claim/delivery and SourceItem ingestion continue. The hook omits unconfirmed refs, records a bounded `pallium_work_refs_status: unavailable` marker, and emits a non-secret local warning. It never reports persistence success or silently reuses an older snapshot. Exact search continues to use only the immutable `pallium_work_refs` list and existing container/visibility rules; attaching a ref grants no History or memory access.

### Concrete developer and agent walkthrough

1. Session A already exists in the Pallium implementation worktree. On the next prompt its hook automatically replaces structural rows with qualified refs for branch `feat/relay-session-work-associations` and Work Record `relay-session-work-associations`. The developer copies the exact feature ref displayed by Minimap, for example `work:v1:7f3c9d140a6e44d58934a88a253cc017:feature:add-relay-session-work-associations`, and the Jira producer's exact `work:v1:2ab7725e5e764d10a4406d6907e31b98:ticket:pal-412`. They ask, “Attach this session to these two exact work refs.” The agent calls attach twice and sees both `explicit`, the branch/Work Record as `structural`, and whether all four enter the five-ref history projection.
2. Session B already exists in a different worktree/container (for example the Minimap companion branch). Its local branch/Work Record refs are different. The reviewer explicitly attaches the same copied feature and Jira refs. Nothing infers this from its prompt or files.
3. The developer opens Dashboard -> Relay, pastes/selects the exact feature ref, and sees an active exact filter plus both participant cards across containers. Each card shows runtime, container, alias if present, canonical endpoint selector, explicit/structural origin freshness, lifecycle, and availability; absent health is visibly `unknown`. The existing container filter remains visible as an intersection, with Clear/Include dormant and closed controls and distinct loading/empty/failed states.
4. An agent asks `pallium_relay_participants` for the same exact feature ref. It receives two bounded rows, chooses Session B's canonical `relay-session-…` selector, calls normal `pallium_relay_send`, and Session B uses normal `pallium_relay_reply`. No broadcast or automatic recipient choice occurs.
5. When Session A changes branch/Work Record, its next prompt replaces only old structural rows; the explicit feature/Jira refs survive. When it leaves the work, it explicitly detaches those refs. If the same ref is still discovered, the response says it remains and names `structural` as the reason. New turns use the new snapshot; prior SourceItems remain unchanged. Dormant/closed Session B disappears from the default participant result but remains under Include inactive with truthful status. Reopening the same endpoint restores it without transferring rows through an alias.
6. If the developer supplies bare `PAL-412`, mutation returns an ambiguity error requiring the exact qualified ref. Unknown availability is shown as unknown, not guessed. Non-git structural qualification reports unsupported while explicit producer refs remain usable.

### Shared files and implementation surface

Schema/API/persistence review surface: `storage/sqlite_schema.py`, `storage/sqlite_relay.py`, `core/relay.py`, `api/schemas.py`, `api/routes.py`.

Shared with existing/future exact-search and structural-reference work: `core/work_ref.py`, `core/service.py`, `app/mcp/client.py`, `app/mcp/server.py`, `integrations/codex/hooks/common.py`, `integrations/codex/hooks/user_prompt_submit.py`, `integrations/codex/hooks/stop.py`, `integrations/claude-code/hooks/common.py`, `integrations/claude-code/hooks/user_prompt_submit.py`, `integrations/claude-code/hooks/stop.py`, `integrations/opencode/.opencode/plugins/pallium.mjs`, `tests/test_work_ref.py`, `tests/test_structural_work_refs_e2e.py`, `tests/test_exact_work_ref_search.py`, `tests/test_search_history_tool.py`, and hook parity tests. These are coordination hotspots; implementation will rebase before editing and avoid changing exact-search visibility semantics.

Dashboard surface: `app/dashboard.py`, `app/dashboard.html`, `tests/test_dashboard.py`, `tests/dashboard_plain_language_renderer.mjs`. Documentation/roadmap changes follow contract approval. No new dependency, registry service, role model, deep-link contract, or Minimap code is proposed in this slice.

## Implementation

2026-09-09 — Created isolated worktree `C:\Dev\rore\Pallium\.worktrees\relay-session-work-associations` on branch `feat/relay-session-work-associations` from `origin/main` `0dbb0691`; design discovery is in progress and no production file has been edited.

## Plan review

Pending architect design review and subsequent clean-context smart plan review.
