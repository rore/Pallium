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

**Material assumptions:** (1) A generic readable `scope_ref` plus NFC-preserved `local_ref`, hashed into fixed-length `work:v1:<sha256>`, is reproducible in Python and JavaScript without changing legacy work-ref normalization; shared vectors are a stop condition. (2) Existing bare structural scalar/history refs and caller-supplied `pallium_work_refs` keep their current precedence; registry explicit keys enrich only remaining per-turn slots with visible overflow and no search union. (3) The registry slice is the two structural sources shipped today plus at most three explicit associations; registry membership and per-turn history coverage are reported separately. (4) Existing Relay endpoint IDs remain the sole association owner; alias transfer never moves rows. (5) Trusted hook/MCP identity seams resolve the current endpoint without model-supplied runtime/session arguments; unsupported runtimes fail closed. (6) Dashboard correction remains trusted-local administration on one exact endpoint ID. (7) Close/reopen retention is in scope; physical endpoint deletion/pruning does not exist and cascade behavior is explicitly deferred.

**Plan:** Pending architect design review. After approval: (1) add the Work Record's reviewed API/persistence checkpoints and get clean-context smart plan review; (2) add one endpoint-owned origin table and generic qualification/validation helper; (3) extend Relay core/HTTP with atomic structural refresh, current-session explicit attach/detach/read, and exact-ref participant lookup; (4) expose four narrow MCP tools using the receive path's runtime-owned identity resolver; (5) make supported hooks refresh at turn admission and capture immutable post-refresh/current snapshots for user/assistant ingestion; (6) extend the existing dependency-free dashboard with exact-ref filtering and exact-endpoint explicit correction; (7) add focused persistence/API/MCP/hook/dashboard tests, then the required public-surface E2E, isolated synthetic demo, docs, screenshots, full suite, workflow/redline gates, and independent smart result review. Stop and return to planning on identity weakening, silent history overflow, container/history access widening, or a required tracker/runtime-specific Relay abstraction.

**Verification plan:** Public contract → E2E maps separately to HTTP registry/lifecycle/concurrency, runtime-owned MCP attach/find/send/reply, hook capture/History exact search, and dashboard filtering/correction. It covers valid and malformed non-blocking structural refresh, two structural plus three registry explicit associations, fourth-attach conflict, mixed legacy caller refs/duplicates/visible overflow, concurrent attach at capacity, origin overlap, alias transfer, restart, dormant/default and closed/opt-in participants, pagination plus container-filter intersections, closed mutation, missing/conflicting MCP identity, Unicode and cross-language canonical vectors, credential/local-remote fallback, unavailable association service with unchanged structural ingestion/delivery, early-return user turns, delayed prebuilt payload after detach, same-payload duplicate after lost response, and exact non-transitive/no-permission-side-effect lookup. Existing and separate Relay databases get schema-init coverage. Browser tests/screenshots cover readable inputs, advanced key, loading/empty/error/overflow/closed states, failed correction, and keyboard access. Run focused nodes, affected files, `--lf`, full `tests/ -x -q`, import/workflow/redline checks, then independent smart result review.

**Plan review:** Pre-edit classifier: MIXED -> API_CHANGE + SCHEMA_CHANGE, High/Large. Fresh smart review of revision 3 found one authority-port wording issue; remediation `60b1aeae` was verified APPROVE. Architect technical review approved implementation in Relay message `relay-reply-05b483e577024c416b6f42a4d71bdef950560a9a2bbdf99b8321da076843c066` with caller-selection, exact-key History guidance, existing repository-identity ownership, frozen-scope, and final-demo clarifications recorded below. Agent/manager approval is not human authorization; the user approval remains separately recorded. PR-time `api-reviewed` and `persistence-reviewed` labels or CODEOWNER approval remain required before merge.

**Approvals:** Approved by user 2026-09-09: "you're about to get assigned work from the architect agent, i approve this work and doing PRs"

**Exceptions:** —

**State:** Ready for review
<!-- agent-workflow:end -->

## Corrected design review packet (revision 3)

### Exact workspace and required gates

- Worktree: `C:\Dev\rore\Pallium\.worktrees\relay-session-work-associations`
- Branch: `feat/relay-session-work-associations`
- Work Record: `.agent-workflow/tasks/relay-session-work-associations.md`
- Base: `origin/main` `0dbb0691d60a98dda06702d6107645af8e842a08`
- Commits: Work Record `0b543f3e`; rejected first packet `72e609cc`; first correction `f42c5fc8`
- Classification: API_CHANGE + SCHEMA_CHANGE, Risk High / Complexity Large. Production remains blocked on architect contract approval, a clean corrected smart review, and recorded API-review plus persistence-review checkpoints. Only the user's verbatim statement in `Approvals` is human authorization; architect/manager/agent reviews do not substitute for it.

### Smallest product slice and persistence

Existing bare branch/Work Record scalar and History behavior stays unchanged. Relay adds endpoint-owned readable associations, exact plural participant discovery, current-session explicit correction, and best-effort explicit association enrichment of future turns. No current-work migration, old-source rewrite, implicit search union, backfill, tracker integration, producer service, ownership/role model, semantic expansion, deep link, or composer.

One new Relay table is sufficient. Each `(endpoint_id, work_ref, origin)` row also stores canonical readable `scope_ref`, `local_ref`, structural position, first-associated time, and last-confirmed time. `origin` is `explicit` or `structural`; the same exact ref may have both. Structural refresh atomically replaces only structural rows. Explicit attach/detach changes only explicit origin. Endpoint identity owns rows; alias transfer does not. Close retains rows and reopen of the same endpoint retains them.

Physical endpoint deletion/pruning does not exist today and cascade is not promised in this slice: SQLite connections do not enable foreign-key enforcement. A future deletion feature must remove association rows in its own transaction before deleting an endpoint. Schema implementation must add the table to `_RELAY_TABLE_NAMES` and `_initialize_relay_schema`'s explicit Relay list, and tests initialize both an existing upgraded database and a separate Relay database. Test cleanup removes only its isolated database.

### Reproducible readable identity

Normal tool inputs and primary dashboard text are two values:

- `scope_ref`: the canonical place where an identifier is meaningful.
- `local_ref`: the ordinary identifier in that scope.

The generic boundary validates these inputs and produces the advanced exact key:

`work:v1:` + lowercase SHA-256 hex of `UTF8(NFC(scope_ref)) + 0x00 + UTF8(NFC(local_ref))`

Before NFC, both runtimes reject any input containing an isolated UTF-16 surrogate; only well-formed Unicode scalar values proceed. Inputs containing NUL, C0/C1 controls, U+2028/U+2029, redaction markers, detected secrets, or leading/trailing ASCII whitespace are rejected rather than repaired. `scope_ref` is 1..512 UTF-8 bytes after NFC. `local_ref` is 1..128 Unicode scalar values and at most 512 UTF-8 bytes after NFC. Case and non-ASCII characters are preserved exactly; producers own semantic casing. The final 72-character lowercase-hex key alone passes through existing `_normalize_work_ref`, so legacy casefold/separator behavior is unchanged and JavaScript does not need Python `casefold`.

Repository identity gets one published Python/JavaScript contract rather than reusing today's inconsistent helpers:

1. Accept HTTPS/SSH URL and SCP-style Git remotes; reject local/file remotes and any password/token-bearing URL.
2. Remove scheme, safe SSH username, query/fragment, trailing slash, and final `.git`; lowercase the ASCII DNS host. Remove the default port (`443` for HTTPS, `22` for SSH/SCP) and preserve any explicit non-default port in the authority. Reject missing, malformed, out-of-range, or scheme-ambiguous ports.
3. For `github.com` only, lowercase owner/repository path. For other hosts, preserve path case.
4. Emit `git:<authority>/<path>`, where authority is the lowercase host plus any preserved non-default port. For example, `ssh://git@git.example.test:2222/team/repo.git` emits `git:git.example.test:2222/team/repo`, while port 22 emits `git:git.example.test/team/repo`. With no usable remote, emit `repo:<lowercase-root-commit-hex>`. With neither, repository-scoped automatic association is unavailable and explicit non-repository scope remains usable.
5. Roadmap roots are repository-relative: convert `\` to `/`, reject absolute/empty/`.`/`..` traversal segments, NFC-normalize each segment, and percent-encode UTF-8 bytes outside RFC 3986 unreserved characters with uppercase hex. Repository root is represented by `.`. Emit `roadmap:v1:<repository-ref>#<encoded-root>`.

Normal examples:

- scope `roadmap:v1:git:github.com/rore/pallium#roadmap`, local `feature:add-relay-session-work-associations`, exact key `work:v1:4e012e357683c4d5202c658947097e4a1effcf0c4f0e075d450874f89f40b652`
- scope `tracker:v1:jira.example.test#pallium`, local `ticket:PAL-412`, exact key `work:v1:50123c19c18153c5f77c954a37ef6257b27b57b11660e62f9e0980ab73132616`
- structural scope `git:github.com/rore/pallium`, local `git-branch:feat/relay-session-work-associations`

Pallium never parses feature/ticket/Jira/Minimap semantics. The Minimap contract is the roadmap scope rule above plus local `<kind>:<item-id>`. Same repo/root/item is stable across worktrees; another repo/root differs. A tracker producer supplies a credential-free canonical authority/project scope. If an agent supplies only `PAL-412`, attach/find asks for `scope_ref` and changes nothing; it never guesses current repository or tracker.

Shared Python/JavaScript golden vectors are required before implementation proceeds: HTTPS/SSH/SCP GitHub remotes; default-port equivalence and distinct non-default ports; malformed/out-of-range ports; non-GitHub path-case distinction; composed/decomposed Unicode equivalence; distinct non-ASCII case; lone high/low surrogate rejection, a supplementary scalar, and literal U+FFFD; `/` versus `\` roadmap roots; escaped Unicode/space; root-commit fallback; credential-bearing and local remotes; missing identity; 128/129-scalar local refs; and 512/513-byte scope/local boundaries.

### Compatibility, bounds, and visible overflow

Registry membership is bounded to the two structural sources shipped today plus three explicit associations per endpoint. The union is at most five; origin overlap counts once. A fourth distinct explicit attach returns `409 association_limit`, writes nothing, and says which readable explicit ref must be detached first. Structural refresh accepts at most branch and Work Record and never evicts explicit rows.

Per-turn History has three input classes, with existing behavior first:

1. current locally discovered bare structural refs in current order (also supplies unchanged scalar current-work);
2. existing caller/event `pallium_work_refs` in caller order;
3. confirmed registry explicit exact keys in association confirmation order.

The existing normalizer/deduplicator still selects the first five. New merge reporting examines at most the first 20 caller entries and never echoes rejected/secret input. It records at most five safe normalized omitted refs with source, plus `omitted_valid_count`, `invalid_count`, `caller_input_count`, `caller_examined_count`, and `caller_input_truncated`; counts and flags remain available when the omitted list is truncated. Invalid values are distinct from valid capacity omissions. SourceItem metadata uses bounded `pallium_work_refs_omitted` and `pallium_relay_work_refs_status: complete|partial|unavailable`. UserPrompt injection tells the agent which listed associated refs were not searchable and the additional omitted/unexamined counts; Stop emits the same bounded non-secret warning. Relay dashboard/current-session reads report registry persistence only and do not claim a latest History capture. Attach results say `association: persisted; history: evaluated per turn` and never claim guaranteed searchability.

Thus the normal four-ref journey (branch, Work Record, feature, ticket) is complete with one spare only when legacy caller refs do not consume it. Mixed legacy/registry overflow is truthful rather than silently evicting established inputs. Duplicates across classes consume one slot. A branch switch atomically replaces structural registry rows and local discovery immediately records the new bare branch; explicit associations survive. Full qualified-structural History migration is a separate decision.

### HTTP and MCP contract

HTTP:

- `POST /relay/turn` adds optional ordered `structural_work_refs: [{scope_ref, local_ref}] | null`; `null` leaves registry structural rows unchanged and `[]` clears them. Relay admission/claim commits independently; association refresh follows and can return a warning without blocking delivery.
- `GET /relay/sessions/work-refs?runtime=&session_ref=&container_ref=` returns one exact endpoint's grouped readable snapshot without liveness/message side effects.
- `POST /relay/sessions/work-refs/attach` and `/detach` accept trusted-integration `{runtime, session_ref, container_ref, scope_ref, local_ref}` and return post-state. They do not create/reopen a missing or closed agent session. Dashboard administration may correct a closed exact endpoint explicitly.
- `GET /relay/work-refs/participants` accepts either readable `scope_ref` + `local_ref` or advanced exact `work_ref`, never both. It performs one service-global exact match and returns `contract: relay-session-work-associations/v1`, readable fields, canonical endpoint selector, alias/runtime/container, origins/freshness, and existing raw `state`, `lifecycle`, `destination_health`, `last_seen_at`. Dormant active sessions remain visible by default; only closed sessions require `include_closed=true`. No inferred availability field.
- Pagination defaults to 50 and caps at 200. Older route-not-found means unsupported; consumers distinguish it from unreachable, timeout, malformed, over-limit, successful empty, and success.
- Dashboard trusted-local correction posts `{action, scope_ref, local_ref}` to one exact endpoint route and calls RelayService; API/dashboard never import storage.

MCP current-session tools hide `request_ctx` and reuse receive's runtime-owned identity resolution; no model-supplied runtime/session. Optional `container_ref` is only injected scope and resolution fails closed:

- `pallium_relay_work_refs(container_ref=None)`
- `pallium_relay_attach_work_ref(scope_ref, local_ref, container_ref=None)`
- `pallium_relay_detach_work_ref(scope_ref, local_ref, container_ref=None)`
- `pallium_relay_participants(scope_ref, local_ref, include_closed=False, container_ref=None, offset=0)`

Missing/conflicting scope or identity yields an actionable no-op. Participant reads are bounded, plural, and have no wake/claim/send/broadcast side effect. Normal exact send/reply is unchanged.

### Capture owner, delay, and failure

Each hook callback invocation owns one snapshot and one constructed SourceItem payload. It discovers bare structural refs before any Relay request, merges caller refs, and keeps them even when Relay fails. Successful association lookup adds confirmed registry explicit keys. Once the payload and source ID are constructed, a delayed submission or resubmission of those same bytes keeps the same snapshot. No durable retry queue or callback-spanning snapshot is added.

A later callback is a new event with a new source ID and captures current associations; it is not called a retry. A lost response after successful persistence can be checked through the existing SourceItem read/status path; resubmitting the identical ID/body returns the existing duplicate/conflict contract and cannot mutate the stored metadata. No Relay association table stores or orders capture outcomes. Tests assert the first stored item retains its captured refs after detach. The guarantee does not claim that today's Python/OpenCode hooks automatically retry.

UserPrompt callbacks that take the existing Relay-delivery early-return path create no user SourceItem, so there is no user snapshot to preserve; this is documented and covered. Stop still captures the assistant item normally. On association refresh/read failure, ordinary delivery and ingestion continue with bare structural plus caller refs and `pallium_relay_work_refs_status: unavailable`; only unconfirmed registry enrichment is omitted.

### Lightweight standalone UX mock

```text
Developer: Associate this session with roadmap feature add-relay-session-work-associations.
Agent -> pallium_relay_attach_work_ref(
  scope_ref="roadmap:v1:git:github.com/rore/pallium#roadmap",
  local_ref="feature:add-relay-session-work-associations"
)
Attached
  Feature: add-relay-session-work-associations
  Scope: github.com/rore/pallium / roadmap
  Origin: explicit · confirmed just now
  Registry capacity: 1/3 explicit
  History: evaluated separately on each captured turn
  Advanced exact key: work:v1:4e012e357683c4d5202c658947097e4a1effcf0c4f0e075d450874f89f40b652
```

A ticket uses tracker scope `tracker:v1:jira.example.test#pallium` plus local `ticket:PAL-412`. A missing scope returns “Provide the tracker/repository scope; nothing was attached.” Session B in another worktree/container supplies the same readable feature pair while retaining its own structural branch/Work Record pairs.

```text
Relay > Work reference
Scope      [ github.com/rore/pallium / roadmap ]
Reference  [ feature:add-relay-session-work-associations ] [Apply] [Clear]
Advanced exact key ▸

2 associated sessions
Codex · RelayDev    Pallium container   recent   destination health unknown
  explicit · confirmed 2m ago          relay-session-...
Codex · reviewer    Minimap container   dormant  last seen 43m ago
  explicit · confirmed 39m ago         relay-session-...
[ ] Include closed sessions
```

Session detail shows readable chips. Explicit rows have Remove; structural rows say “Updated automatically from branch/Work Record.” Origin overlap removal says structural remains. Failed correction leaves the chip unchanged. A fourth explicit attach says “3 of 3 explicit references used; detach one first.” Mixed-input overflow says “This turn recorded 5 refs; associated ticket:PAL-412 was omitted and is not searchable from this turn.” Association-service failure says “Branch, Work Record, and supplied refs were still recorded; Relay association enrichment was unavailable.”

The agent queries participants with the same readable scope/local pair, sees both exact endpoint selectors including dormant B, chooses one, and uses normal send; B replies normally. Work switch replaces A's structural rows only. Detach changes new captures; older History is immutable. Closed participants appear only when requested.

### Explicit public verification map

- HTTP E2E: register; valid/empty/malformed structural refresh while delivery still claims; attach/read/detach; origin overlap; two-container plural lookup; dormant/default and closed/opt-in; missing/closed agent mutation versus dashboard correction; pagination/filter intersections; concurrent third/fourth attach at capacity; alias transfer; restart; upgraded and separate Relay DB.
- MCP E2E: hidden current identity for Codex metadata and Claude/OpenCode environment; missing/conflicting identity fail closed; readable attach/list/find; plural exact selector; normal send/reply; no read side effects.
- Hook/History E2E: structural + legacy caller + registry merge order, cross-source duplicate, caller lists at 20/over-20, safe omitted-list cap/count/truncation, secret/invalid counts without echo, every capacity-overflow source, user warning/status metadata, exact search only for included refs, Relay unavailable with unchanged structural/caller ingestion, delivery early return, attach/detach between user and assistant captures.
- Snapshot E2E: build payload, detach, submit later; resubmit identical ID after simulated lost response and assert duplicate/conflict plus unchanged first item; later callback is a new snapshot.
- Identity contract tests: shared Python/JavaScript vectors listed above, including authority ports and malformed Unicode; unrelated repo/roadmap/tracker separation; same worktree-independent repo/root/item key; secret/local-remote rejection.
- Dashboard browser E2E/screenshots: understandable fields, advanced key, filter/container intersection, long/escaped text, keyboard access, loading/empty/unsupported/error/overflow/dormant/closed states, correction failure/no optimistic mutation.

### Files and coordination hotspots

Persistence/API: `storage/sqlite_schema.py`, `storage/sqlite_relay.py`, `core/relay.py`, `api/schemas.py`, `api/routes.py`. `storage/sqlite.py` is read/test context only because foreign-key enablement and cascade are deliberately not added.

Identity/search/history: additive helpers in `core/work_ref.py`; metadata merge/status in `core/service.py` only if the ingestion boundary requires it; `app/mcp/client.py`, `app/mcp/server.py`; Codex and Claude `common.py`/`user_prompt_submit.py`/`stop.py`; `integrations/opencode/.opencode/plugins/pallium.mjs`; and exact-search/structural/hook parity tests. Existing `_normalize_work_ref`, search visibility, scalar selection, and caller-ref precedence do not change. Coordinate this additive shared-file work with `@pall-arc`; stop on a conflicting implementation.

Dashboard: `app/dashboard.py`, `app/dashboard.html`, `tests/test_dashboard.py`, `tests/dashboard_plain_language_renderer.mjs`. No new dependency or Minimap implementation.
## Implementation

2026-09-09 — Created isolated worktree `C:\Dev\rore\Pallium\.worktrees\relay-session-work-associations` on branch `feat/relay-session-work-associations` from `origin/main` `0dbb0691`; design discovery is in progress and no production file has been edited.

2026-09-09 — Architect rejected the first packet before production approval. Revised to readable scope/local inputs, fixed-length exact keys, unchanged bare structural current-work/history, five total refs (two structural plus three explicit), structural-history fallback on Relay failure, dormant-by-default discovery, and raw lifecycle/health facts. No production file has been edited.

2026-09-09 — Fresh smart review of `f42c5fc8` returned REVISE. Revision 2 now preserves legacy caller-ref precedence with visible per-turn overflow, publishes exact cross-runtime identity bytes/vectors, bounds retry guarantees to an already-built payload, removes unenforced cascade claims, and maps the missing E2E cases. No production file has been edited.

2026-09-09 — Fresh smart review of `0fdbf21e` returned REVISE. Revision 3 now preserves non-default repository ports, rejects isolated surrogates, removes unowned latest-capture state, bounds omission lists/counts, and aligns the canonical roadmap with deferred product deletion/pruning. No production file has been edited.

2026-09-09 — Remediation `60b1aeae` changed the repository output grammar to port-bearing authority and added default/non-default expected vectors. Smart remediation verification returned APPROVE with no remaining design blockers. No production file has been edited.

2026-09-09 — Implemented the first approved vertical slice in the isolated worktree. Added the generic readable scope/local identity validator and exact SHA-256 key without changing _normalize_work_ref; added the endpoint-owned association table/index to shared and separate Relay schema initialization; added atomic structural refresh, explicit attach/detach/capacity, session read, and service-global participant storage; and exposed the additive /relay/turn projection plus HTTP read/attach/detach/participants routes. The turn is admitted before best-effort structural refresh, participant overlap is deduplicated by endpoint, dormant sessions are included, and closed sessions remain opt-in. Focused verification: 32 passed across tests/test_relay_work_ref_identity.py, tests/test_relay_work_ref_associations_e2e.py, and tests/test_sqlite_relay_isolation.py. The delegated identity slice initially landed in the shared checkout; RelayDev moved only those two agent-owned changes into this isolated worktree and reversed the exact patch from the shared checkout before review. apply_patch had already failed with machine-local CreateProcess error 1327, so all edits used deterministic named-file replacements as permitted by local instructions. No installed service, merge, or live state was touched.
2026-09-10 — Completed the approved end-to-end slice at implementation revision `b0bfd5dc`: endpoint-owned explicit/structural associations; exact participant lookup; additive HTTP/MCP surfaces; runtime hook refresh and immutable bounded History capture for Codex, Claude Code, and OpenCode; dashboard lookup/correction; roadmap/guide alignment; isolated demo; and two screenshots. The demo uses OpenCode identities so its temporary seeded database cannot invoke Codex/Claude wake adapters. No installed service, live database, merge, or live integration state was touched.

2026-09-10 — Smart result review initially returned four P2 findings: malformed diagnostics could raise on unhashable containers, a concurrent final detach could race participant projection and pagination, a valid five-participant MCP page could exceed its fixed output budget without continuation, and three raw Git URL forms differed between Python and JavaScript parsers. The shared sanitizer now rejects malformed diagnostic shapes, participant paging and origins use one snapshot-consistent joined statement, MCP trims only whole participant rows with truthful `next_offset`, and shared invalid vectors reject Unicode/percent-encoded hosts and backslash paths in both runtimes. Final independent remediation review returned PASS with no remaining actionable findings.

2026-09-10 — Agent Workflow skill-feedback trigger 1 fired because the full-suite gate was retried while legacy hook test doubles were updated, but it did not pass the actionability filter: the retries came from task-specific strict mocks and one host-injected actor environment value, not a repeatable gap in the workflow skill.

## Evidence

Verified implementation revision `b0bfd5dc` in the isolated worktree. Focused affected Python suite: 520 passed, 2 Windows skips. OpenCode serial suite: 51 passed, 7 intentional Windows skips. Final full repository suite with the host-injected `PALLIUM_HOOK_ACTOR_REF` cleared for hermetic identity tests: 4,781 passed, 33 skipped, 2 expected xfails. `scripts/run-import-linter.py` reported zero boundary violations; `git diff --check` passed. The isolated demo completed register → attach → participant discovery → exact send/claim/reply → History capture → detach → immutable exact History query → close without touching port 19836 or the installed database. The shipped dashboard JavaScript harness passed via `tests/test_dashboard.py`, and the two committed screenshots were visually inspected. The repository last-failure command found no cached failing nodes and therefore deselected the suite.

## Result review

Clean-context smart review by `association_result_review` examined the complete persistence/API/MCP/hook/dashboard/identity diff, reproduced four P2 failures, and reviewed each remediation. Final verdict: PASS. Remediation verification independently reported 47 focused Python tests and both JavaScript identity checks passing, with no remaining actionable finding. PR-time `api-reviewed` and `persistence-reviewed` labels or CODEOWNER approval remain intentionally unsatisfied until the PR exists; merge stays blocked until those repository checkpoints pass.

## Plan review

Architect technical review APPROVED revision 3 for implementation in Relay message `relay-reply-05b483e577024c416b6f42a4d71bdef950560a9a2bbdf99b8321da076843c066`. Acceptance clarifications: diagnostic inspection must not change legacy caller-ref selection; every read and successful attach returns the exact key plus readable fields and existing History-search guidance; repository identity additions stay at the existing owning boundary and do not change container identity; scope stays four tools, one table, simple UI; final evidence is a working isolated HTTP/MCP/send/reply/detach/History and browser journey, not the text mock. Stop before merge/live install.

## Checkpoint: api-review
What is changing: Add four Relay session-work HTTP operations, one optional ordered structural field and additive response projection on `/relay/turn`, plus four MCP wrappers. Existing request fields, scalar work refs, recipient/send/reply routes, and status codes remain unchanged.
Why: Sessions need readable explicit association mutation and exact plural participant discovery through existing caller surfaces.
Affected contract / model / boundary: `api/schemas.py`, `api/routes.py`, `app/mcp/client.py`, `app/mcp/server.py`; additive HTTP/MCP surface and validation only. Existing consumers are Codex/Claude/OpenCode hooks, MCP agents, dashboard, and future Minimap HTTP read-through. No committed OpenAPI artifact exists; generated schema diff will be inspected.
Compatibility / migration risk: low — new endpoints and optional fields are additive; legacy caller-ref selection and scalar/history semantics are frozen. New malformed structural input degrades association refresh without blocking Relay admission.
Verification plan: HTTP/MCP contract E2E, generated OpenAPI comparison, old-client `/relay/turn` tests, invalid/missing/conflicting identity tests, pagination/empty/unsupported behavior, and redline `api-review` satisfaction on the PR.

## Checkpoint: persistence-review
What is changing: Add one Relay association table and exact-key index to schema-as-code; no existing row changes.
Why: Endpoint-owned explicit/structural origins need durable atomic membership and exact lookup across sessions.
Affected contract / model / boundary: `storage/sqlite_schema.py` and `storage/sqlite_relay.py`; table initialization must be included in both primary and separate Relay database paths. No foreign-key/cascade or retention behavior is added.
Compatibility / migration risk: low — schema-only forward addition on an initially empty table, no data rewrite or information loss. Rollback can drop the new table/index; existing Relay/history data is untouched. Index creation is on the new empty table, so no deployed-table lock scan. This installation is not multi-tenant.
Verification plan: fresh database, existing upgraded database, separate Relay database, restart, atomic concurrent origin/capacity tests, import boundaries, and redline `persistence-review` satisfaction on the PR.

## Approved implementation file list

Primary agent owns the high-risk persistence/core/API contract: `core/relay.py`, `storage/sqlite_schema.py`, `storage/sqlite_relay.py`, `api/schemas.py`, `api/routes.py`, plus this Work Record and roadmap/docs. Bounded delegated changes may touch `core/work_ref.py` with new identity tests; supported integration hook files and parity tests; and `app/dashboard.py`/`app/dashboard.html` with dashboard tests. MCP changes are `app/mcp/client.py`, `app/mcp/server.py`, and Relay MCP tests. Synthetic demonstration may add one file under `examples/` or `tests/fixtures/`. Any production path outside this list or any change to existing container identity, `_normalize_work_ref`, visibility, retention, roles, or orchestration returns to review.
