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

**Material assumptions:** (1) The association identity can be a generic tuple of readable `scope_ref` plus existing-normalized `local_ref`, with fixed-length `work:v1:<sha256>` as its advanced exact key; if Minimap cannot reproduce that function, return to contract review. (2) Existing bare branch/Work Record refs remain the scalar/history representation while their registry rows carry repository scope; no implicit search union or migration is needed. (3) The first slice has exactly the two structural sources shipped today plus at most three explicit refs, so every successful explicit association fits the unchanged five-ref history projection. (4) Existing Relay endpoint IDs remain the sole association owner; alias transfer never moves rows. (5) Trusted hook/MCP identity seams resolve the current endpoint without model-supplied runtime/session arguments; unsupported runtimes fail closed. (6) Dashboard correction remains trusted-local administration on one exact endpoint ID. (7) No physical endpoint deletion/pruning exists today; retained rows cascade on future deletion and tests dispose only the isolated database.

**Plan:** Pending architect design review. After approval: (1) add the Work Record's reviewed API/persistence checkpoints and get clean-context smart plan review; (2) add one endpoint-owned origin table and generic qualification/validation helper; (3) extend Relay core/HTTP with atomic structural refresh, current-session explicit attach/detach/read, and exact-ref participant lookup; (4) expose four narrow MCP tools using the receive path's runtime-owned identity resolver; (5) make supported hooks refresh at turn admission and capture immutable post-refresh/current snapshots for user/assistant ingestion; (6) extend the existing dependency-free dashboard with exact-ref filtering and exact-endpoint explicit correction; (7) add focused persistence/API/MCP/hook/dashboard tests, then the required public-surface E2E, isolated synthetic demo, docs, screenshots, full suite, workflow/redline gates, and independent smart result review. Stop and return to planning on identity weakening, silent history overflow, container/history access widening, or a required tracker/runtime-specific Relay abstraction.

**Verification plan:** Public-surface E2E will cover register -> structural refresh -> explicit attach -> plural cross-container lookup -> exact send/reply -> work switch -> detach -> close/include-inactive -> reopen -> isolated cleanup. Boundary cases cover empty/duplicate/max/over-max, origin overlap, concurrent refresh/attach/detach, alias transfer, restart, Unicode and escaped refs, invalid/unqualified/secret-bearing refs, missing/current-vs-other endpoint mutation, unavailable snapshot service, delayed ingestion after detach, stable same-repo worktree scope, distinct repository/roadmap/tracker scopes, exact non-transitive lookup, and no message/claim/history-permission side effects. Dashboard browser tests and screenshots cover loading/empty/error/overflow/inactive states and keyboard access. Run focused nodes, affected files, `--lf`, full `tests/ -x -q`, import/workflow/redline checks, then a clean-context smart review before PR handoff.

**Plan review:** Pre-edit classifier: MIXED -> API_CHANGE + SCHEMA_CHANGE, High/Large; API and persistence review required. Architect rejected the first opaque-input/current-work-migration design in Relay message `relay-reply-b7c2c94869bde6853c9b1f7ed0537cd73fe580132f8575220cfaaab8ade151b5`. Corrected architect review and a fresh clean-context smart design/implementation-plan review are pending; the rejected design is not review evidence.

**Approvals:** Approved by user 2026-09-09: "you're about to get assigned work from the architect agent, i approve this work and doing PRs"

**Exceptions:** —

**State:** Blocked or returned to planning
<!-- agent-workflow:end -->

## Corrected design review packet

### Exact workspace and gates

- Worktree: `C:\Dev\rore\Pallium\.worktrees\relay-session-work-associations`
- Branch: `feat/relay-session-work-associations`
- Work Record: `.agent-workflow/tasks/relay-session-work-associations.md`
- Base: `origin/main` `0dbb0691d60a98dda06702d6107645af8e842a08`
- Work Record creation: `0b543f3e`; rejected packet: `72e609cc`
- Classification: API_CHANGE + SCHEMA_CHANGE, Risk High / Complexity Large. Before production editing, the corrected plan requires architect contract approval, fresh clean-context smart plan review, and recorded API-review plus persistence-review checkpoints. The human approval is only the user's verbatim 2026-09-09 statement already in `Approvals`; architect/manager review does not substitute for it.

### Smallest product slice

Current behavior remains intact: hook discovery continues to emit bare `git-branch:*` and `agent-workflow:*` refs, scalar current-work remains the first structural ref, and immutable History keeps the same exact bare refs and five-ref cap. Relay gains endpoint-owned associations with readable identity, plural exact participant lookup, explicit correction, and captured explicit-ref history enrichment. There is no current-work migration, old-source rewrite, search union, backfill, tracker integration, producer service, role/ownership model, transitive expansion, deep link, or composer.

One SQLite table is sufficient. Each `(endpoint_id, work_ref, origin)` row also stores the normalized readable `scope_ref` and `local_ref`, structural position, first-associated time, and last-confirmed time. `origin` is `explicit` or `structural`; one exact ref may have both. Endpoint identity owns rows, aliases never do. Structural refresh atomically replaces only structural rows; explicit attach/detach touches only explicit origin. Close retains rows; reopen of the same endpoint retains them; future physical endpoint deletion cascades.

### Readable identity and Minimap contract

Normal inputs and primary UI text are two understandable values:

- `scope_ref`: where this identifier is meaningful.
- `local_ref`: the ordinary identifier inside that scope.

Examples:

- roadmap scope `roadmap:v1:git:github.com/rore/pallium#roadmap` plus local ref `feature:add-relay-session-work-associations`
- tracker scope `tracker:v1:jira.example.test#pallium` plus local ref `ticket:PAL-412`
- repository structural scope `git:github.com/rore/pallium` plus local ref `git-branch:feat/relay-session-work-associations`

The boundary normalizes/validates both and deterministically forms the advanced exact key:

`work:v1:` + lowercase SHA-256 hex of `normalized_scope_ref + NUL + normalized_local_ref`

The key is fixed at 72 characters, so a currently valid 128-code-point local ref is never shortened or rejected merely to fit a prefix. Responses include all three fields. Dashboard chips and ordinary MCP input show `local_ref` with `scope_ref`; the hash is expandable/copyable for exact HTTP consumers and diagnostics.

Pallium does not parse feature, ticket, Minimap, Jira, branch, or Work Record semantics. Producers define canonical readable scopes. The shared Minimap rule is `roadmap:v1:<canonical-repository-ref>#<normalized-repository-relative-roadmap-root>`; its local ref is `<kind>:<item-id>`. The same repo/root/item therefore hashes identically across worktrees, while another repo or roadmap root differs. Repository identity reuses the credential-free container rules (`git:` remote; `repo:` root-commit fallback). Tracker producers supply a credential-free canonical authority/project scope. Absolute checkout paths, URL userinfo/secrets, NUL, redaction markers, and over-bound input fail validation.

Normal attach/find requires both `scope_ref` and `local_ref`. If the agent supplies only `PAL-412`, the tool asks for the missing tracker scope and changes nothing; it never guesses current repo or Jira authority. Pallium works standalone because a developer or agent can supply the current repository/roadmap scope and ordinary item identifier without Minimap. Minimap later uses the same published function. No independent producer service is required.

Existing recorded bare refs remain unchanged and exactly searchable. Structural registry rows use `(repository scope, existing bare structural local ref)`, but scalar injection and History continue storing that bare structural ref under today's container-scoped History contract. There is no automatic relation or widened search between the bare value and hashed registry key. Explicit feature/ticket associations add their fixed exact `work:v1:<hash>` keys to subsequent History metadata, after the independently discovered bare structural refs.

### Bounds and overflow

The first slice matches the actual journey and the existing cap: at most two distinct structural refs (the only shipped sources: branch and Work Record) plus at most three explicit refs per endpoint. The combined bound is five; origin overlap counts once. No successful attach can be omitted from a normal subsequent history snapshot.

- A fourth distinct explicit attach returns `409 association_limit` with the current readable refs and “detach one explicit reference first”; it writes nothing.
- Structural refresh accepts at most the two known sources and replaces them atomically. Over-limit/malformed refresh leaves prior registry structural rows unchanged and returns a warning, but local hook discovery still supplies the current bare structural refs to History.
- History composition is unchanged structural discovery order followed by confirmed explicit exact keys. It deduplicates and stays within five by construction. The response still reports included refs and capacity (`explicit_used: n`, `explicit_limit: 3`) so the user sees remaining room.
- A branch/Work Record switch replaces registry structural rows without touching explicit refs. No temporary old/new overlap is persisted and no explicit ref is evicted.

A broader association registry or migration of qualified structural refs into History is a separate product decision, not bundled here.

### Corrected HTTP contract

- Extend `POST /relay/turn` with optional ordered `structural_work_refs: [{scope_ref, local_ref}] | null`. `null` preserves old-client registry behavior; `[]` clears structural rows. Relay admission/claim happens independently from the best-effort association refresh. Response adds `work_associations: {status, refs, explicit_used, explicit_limit}`; refresh failure never blocks delivery.
- `GET /relay/sessions/work-refs?runtime=<r>&session_ref=<s>&container_ref=<c>` returns the exact endpoint's grouped readable snapshot without liveness/message side effects.
- `POST /relay/sessions/work-refs/attach` and `/detach` accept `{runtime, session_ref, container_ref, scope_ref, local_ref}` on the trusted integration boundary and return post-state. Attach confirms freshness, detach is idempotent and reports when structural origin keeps the association, and neither creates/reopens a session.
- `GET /relay/work-refs/participants` accepts either normal `scope_ref` + `local_ref` or the advanced exact `work_ref`, never both. It performs one service-global exact match and returns `contract: relay-session-work-associations/v1`, readable fields, canonical endpoint selector, alias/runtime/container, grouped origins/freshness, and the existing raw `state`, `lifecycle`, `destination_health`, and `last_seen_at`. Dormant active sessions remain in default results with honest age; only closed sessions require `include_closed=true`. No new inferred `available` field is added.
- Pagination defaults to 50 and caps at the existing dashboard maximum 200. Older services return route-not-found (unsupported); a consumer separately distinguishes unreachable, timeout, malformed, over-limit, successful empty, and success.
- Dashboard trusted-local correction uses one exact endpoint route with `{action, scope_ref, local_ref}` and the same RelayService operations. API/dashboard do not import storage.

### Corrected MCP contract

Current-session tools reuse the receive path's hidden runtime-owned request/environment resolver. The model supplies no runtime/session identity; optional `container_ref` is only the injected Relay scope and resolution fails closed.

- `pallium_relay_work_refs(container_ref=None)`
- `pallium_relay_attach_work_ref(scope_ref, local_ref, container_ref=None)`
- `pallium_relay_detach_work_ref(scope_ref, local_ref, container_ref=None)`
- `pallium_relay_participants(scope_ref, local_ref, include_closed=False, container_ref=None, offset=0)`

A missing/ambiguous scope returns an actionable error and no mutation. Bounded participants return plural exact selectors and never choose, send, wake, claim, or broadcast. Normal Relay send/reply remains unchanged.

### Failure-safe immutable snapshots

At user-prompt admission the hook discovers current bare structural refs first. Those refs are retained locally for scalar injection and SourceItem metadata regardless of Relay availability. It submits readable repository-scoped structural pairs in `/relay/turn`; on success, confirmed explicit exact keys from the returned snapshot are appended to the same user SourceItem. On refresh/read failure, the SourceItem still carries the unchanged bare structural refs plus `pallium_relay_work_refs_status: unavailable`; only unconfirmed explicit enrichment is omitted.

Immediately before constructing the assistant SourceItem, Stop repeats local structural discovery and performs the read-only current-association call. An attach/detach during the turn can therefore affect the assistant item but never the already captured user item. Delayed/retried ingestion resubmits captured metadata; ingestion never queries today's registry and never rewrites older turns. Failure tests assert ordinary Relay delivery and both user/assistant ingestion continue with their known structural context.

### Lightweight local UX mock and walkthrough

Agent input, Session A in the Pallium worktree:

```text
Developer: Associate this session with roadmap feature add-relay-session-work-associations.
Agent -> pallium_relay_attach_work_ref(
  scope_ref="roadmap:v1:git:github.com/rore/pallium#roadmap",
  local_ref="feature:add-relay-session-work-associations"
)
Result: Attached
  Feature: add-relay-session-work-associations
  Scope: github.com/rore/pallium / roadmap
  Origin: explicit · confirmed just now
  History: included · Explicit capacity 1/3
  Exact key: work:v1:4e012e357683c4d5202c658947097e4a1effcf0c4f0e075d450874f89f40b652
```

For the ticket, the agent calls with tracker scope `tracker:v1:jira.example.test#pallium` and local `ticket:PAL-412`; the exact key is `work:v1:bd4582cb3df958d50ca2d1db77e327976d4f3d562b2d03fed339a6598b328dd4`. If only `PAL-412` is supplied, the tool responds `Missing scope_ref; provide the tracker authority/project shown with the ticket. Nothing was attached.`

Session B in another worktree/container attaches the same readable roadmap scope/local pair. Its automatic branch and Work Record pairs differ. The dashboard Relay view contains:

```text
Work reference filter
Scope      [ github.com/rore/pallium / roadmap ]
Reference  [ feature:add-relay-session-work-associations ] [Apply] [Clear]
Advanced exact key ▸

2 associated sessions
Codex · RelayDev       Pallium container   recent   destination health unknown
  explicit · confirmed 2m ago             relay-session-...
Codex · reviewer       Minimap container   dormant  last seen 43m ago
  explicit · confirmed 39m ago            relay-session-...
[ ] Include closed sessions
```

Selecting a session shows readable structural and explicit chips. Explicit rows have Remove; structural rows say “Updated automatically from branch/Work Record” and cannot be removed optimistically. Removing an explicit origin that overlaps structural returns “Still associated: structural origin remains.” A failed request leaves the chip unchanged and shows a retryable error. A fourth explicit attach shows “3 of 3 explicit references used; remove one before adding another.” A failed refresh banner says “Relay association refresh unavailable; branch and Work Record were still recorded in Session History.”

An agent finds participants with the same scope/local pair, receives both exact endpoint selectors including the dormant reviewer, chooses one, and uses normal `pallium_relay_send`; the reviewer uses normal reply. No broadcast occurs. On work switch the next prompt replaces only Session A's structural rows. On leaving, explicit feature/ticket detach removes them from new snapshots while prior History stays unchanged. Closed participants appear only after Include closed.

### Shared files and review surface

Persistence/API: `storage/sqlite_schema.py`, `storage/sqlite_relay.py`, `core/relay.py`, `api/schemas.py`, `api/routes.py`.

Search/current-work coordination hotspots: `core/work_ref.py`, `core/service.py`, `app/mcp/client.py`, `app/mcp/server.py`, Codex and Claude `common.py`/`user_prompt_submit.py`/`stop.py`, `integrations/opencode/.opencode/plugins/pallium.mjs`, `tests/test_work_ref.py`, `tests/test_structural_work_refs_e2e.py`, `tests/test_exact_work_ref_search.py`, `tests/test_search_history_tool.py`, and hook parity tests. The correction deliberately leaves bare structural scalar/history semantics untouched; coordinate with `@pall-arc` only if implementation discovery finds an unavoidable core/history overlap.

Dashboard: `app/dashboard.py`, `app/dashboard.html`, `tests/test_dashboard.py`, `tests/dashboard_plain_language_renderer.mjs`. No new dependency or Minimap code.
## Implementation

2026-09-09 — Created isolated worktree `C:\Dev\rore\Pallium\.worktrees\relay-session-work-associations` on branch `feat/relay-session-work-associations` from `origin/main` `0dbb0691`; design discovery is in progress and no production file has been edited.

2026-09-09 — Architect rejected the first packet before production approval. Revised to readable scope/local inputs, fixed-length exact keys, unchanged bare structural current-work/history, five total refs (two structural plus three explicit), structural-history fallback on Relay failure, dormant-by-default discovery, and raw lifecycle/health facts. No production file has been edited.

## Plan review

Corrected architect design review and subsequent fresh clean-context smart plan review pending. The rejected first packet is not review evidence.
