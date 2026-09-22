<!-- agent-workflow:start -->
**Outcome:**
An authorized caller can create and later reread a bounded Session History diagnostic that explains scope, candidate, rank, and packaging behavior without exposing forgotten or unauthorized history or changing retrieval state.

**Target:**
Pallium.

**Scope:**
Add a source-only History diagnostic create/read contract over the existing query trace; persist bounded versioned snapshots in a dedicated diagnostic store that is outside lookup-delivery telemetry; expose two additive HTTP operations and two MCP tools; add focused storage/core/API/tool tests and caller-surface E2E coverage; align Session History docs and roadmap slice 5.

**Constraints:**
Reuse the existing retrieval/ranking trace and History compaction path; no second ranking stack, dependency, normal-search payload growth, raw requester/source-thread identity, unbounded trace, lookup/expansion event, or change to accessibility, use counters, ranking priors, visibility, forgetting, search order, delivery finalization, historical-state warnings, or evaluator denominators. Diagnostic creation is an explicit operation, never a side effect of `include_trace=True`.

**Completion criteria:**
The diagnostic reports requested/effective scope and bounded capture/index, lexical/vector, fusion/ranking, query-limit, and MCP-packaging observations, using `unknown` or `not_observed` instead of unsupported causal claims. Create and reread use the same allowlisted live-sanitization boundary; unavailable IDs are non-oracular; valid-empty, invalid request, corrupt snapshot, persistence/service failure, timeout, and transport outcomes remain distinct; deterministic idempotent retry and all AGENTS.md boundary/error/lifecycle cases pass through HTTP and MCP.

**Requirement baseline:**
{"source":"roadmap-slice-5","outcome":"An authorized caller can create and later reread a bounded Session History diagnostic that explains scope, candidate, rank, and packaging behavior without exposing forgotten or unauthorized history or changing retrieval state.","scope":"Add a source-only History diagnostic create/read contract over the existing query trace; persist one bounded snapshot on the existing historical lookup event; expose it through HTTP and MCP; add focused storage/core/API/tool tests and caller-surface E2E coverage; align Session History docs and roadmap slice 5.","constraints":"Reuse the existing retrieval/ranking trace and historical lookup event; no second ranking stack, new table, dependency, normal-search payload growth, raw thread identity, unbounded trace, or change to accessibility, use counters, ranking priors, visibility, forgetting, search order, delivery finalization, or historical-state warnings.","completion_criteria":"A diagnostic distinguishes missing/invalid, valid-empty, scope exclusion, candidate recovery, ranking, packaging, timeout, and transport outcomes; reports requested/effective scope, bounded lexical/vector/fusion evidence, exclusions, and final rank; rereads are deterministic and revalidate live forgetting/authorization; all AGENTS.md boundary/error/lifecycle cases pass through HTTP and MCP."}

**Behavior changes:**
[{"target":"task-context.scope","classification":"equivalent","before":"Add a source-only History diagnostic create/read contract over the existing query trace; persist one bounded snapshot on the existing historical lookup event; expose it through HTTP and MCP; add focused storage/core/API/tool tests and caller-surface E2E coverage; align Session History docs and roadmap slice 5.","after":"Add a source-only History diagnostic create/read contract over the existing query trace; persist bounded versioned snapshots in a dedicated diagnostic store that is outside lookup-delivery telemetry; expose two additive HTTP operations and two MCP tools; add focused storage/core/API/tool tests and caller-surface E2E coverage; align Session History docs and roadmap slice 5.","reason":"Discovery disproved lookup-event reuse: diagnostics are not delivered History evidence and sharing that funnel can contaminate evaluator denominators or delivery finalization."},{"target":"task-context.constraints","classification":"equivalent","before":"Reuse the existing retrieval/ranking trace and historical lookup event; no second ranking stack, new table, dependency, normal-search payload growth, raw thread identity, unbounded trace, or change to accessibility, use counters, ranking priors, visibility, forgetting, search order, delivery finalization, or historical-state warnings.","after":"Reuse the existing retrieval/ranking trace and History compaction path; no second ranking stack, dependency, normal-search payload growth, raw requester/source-thread identity, unbounded trace, lookup/expansion event, or change to accessibility, use counters, ranking priors, visibility, forgetting, search order, delivery finalization, historical-state warnings, or evaluator denominators. Diagnostic creation is an explicit operation, never a side effect of `include_trace=True`.","reason":"A tiny dedicated table is the smallest boundary that preserves the approved no-telemetry-mutation behavior; the revision makes the unchanged funnel and explicit-operation constraints testable."},{"target":"task-context.completion_criteria","classification":"equivalent","before":"A diagnostic distinguishes missing/invalid, valid-empty, scope exclusion, candidate recovery, ranking, packaging, timeout, and transport outcomes; reports requested/effective scope, bounded lexical/vector/fusion evidence, exclusions, and final rank; rereads are deterministic and revalidate live forgetting/authorization; all AGENTS.md boundary/error/lifecycle cases pass through HTTP and MCP.","after":"The diagnostic reports requested/effective scope and bounded capture/index, lexical/vector, fusion/ranking, query-limit, and MCP-packaging observations, using `unknown` or `not_observed` instead of unsupported causal claims. Create and reread use the same allowlisted live-sanitization boundary; unavailable IDs are non-oracular; valid-empty, invalid request, corrupt snapshot, persistence/service failure, timeout, and transport outcomes remain distinct; deterministic idempotent retry and all AGENTS.md boundary/error/lifecycle cases pass through HTTP and MCP.","reason":"The revision maps each approved failure class to observable evidence, removes unsupported causal claims, and resolves the prior error-contract contradiction without weakening the diagnostic outcome."}]

**Risk:**
High

**Complexity:**
Moderate

**Reason:**
Pre-edit Redline classifies the change RED/contract-sensitive: `core/service.py`, `core/query.py`, `api/routes.py`, and `api/schemas.py` require architecture/API review; the additive dedicated table requires persistence review; and a saved caller-scoped trace requires security review. Retrieval and authorization policy stay unchanged, but the new durable read boundary must fail closed.

**Discovery:**
`/query/debug` already produces requested/effective filters, lexical/vector stages, visibility exclusions, fusion scores, and result summaries through `QueryTrace`, but serializes raw query/filter/candidate identities and never persists a trace ID. Source-only queries bypass `QueryStats.record_query`, yet `PalliumService.query` always writes lookup funnel events; a diagnostic must bypass that service-side write rather than introduce a broad speculative no-mutation mode. `historical_lookup_reuse_event` is documented and evaluated as a lookup/expansion funnel; at least one evaluator scans all rows, so diagnostic rows or payloads there can contaminate denominators or become delivery parents. Field-filter exclusions are discarded before trace accounting, an unavailable vector index yields no stage trace, and capture/index completeness and MCP character packaging are not currently observed. Existing `matches_filters`, `is_visible`, forgetting, lifecycle, source retrieval, query trace, and MCP compaction code remain the authoritative reusable boundaries.

Failure-signal map:
- Capture/index: authorized live source count in requested/effective scope plus lexical/vector indexed counts and explicit provider availability. This is observational; absent expected-source provenance is reported `not_observed`, never guessed as capture failure.
- Scope: requested/effective filter presence, deterministic scope counts, and bounded fixed-enum filter/visibility exclusion counts. No raw container, actor, session, work, or thread value is returned.
- Candidate recovery: provider availability, lexical/vector candidate and selected counts, match channel, finite scores, and bounded omitted counts.
- Ranking: bounded fusion membership, channel ranks/scores, final rank, dedup count, and final-limit omission count.
- Packaging: API reports query-limit selection; MCP additionally applies the existing History character/result compaction path and reports retained final ranks and omitted count. The saved snapshot contains pre-MCP bounded evidence; reread recomputes live sanitization and MCP packaging.
- Unknown: any cause unsupported by the recorded observations is returned as `unknown` or `not_observed`; it is not inferred from an empty stage.

Requester and saved-filter contract:
The required requester tuple is canonical `container_ref` + non-empty `active_session_ref` + explicit `visibility`. Creation rejects a missing tuple; container canonicalization uses the existing resolver before persistence and comparison. `actor_ref`, source-thread, source-item/request lineage, and exact-work are optional source filters, persisted separately from requester scope; omission and exact values remain distinct. Reread accepts only diagnostic ID plus the current required requester tuple, exact-matches it after canonicalization, and does not accept filter overrides. Public/global source visibility does not broaden access to the private diagnostic. Every stored stage/fusion/final candidate passes live existence, forgetting/lifecycle, visibility, and saved-filter checks on create serialization and every reread; a mid-query forget/delete therefore removes the candidate before any public response.

Bounds and format:
Snapshot schema version is exactly `1`; at most 200 ordered stage/fusion candidates and 50 final candidates are stored, every stored string is at most 512 Unicode code points, and canonical serialized JSON is at most 65,536 UTF-8 bytes. Only fixed allowlisted fields and fixed-enum reasons/statuses are stored; no raw `QueryTrace` serialization, query text/tokens, source content, thread/actor/container/work values, index-entry IDs, or exception bodies. Truncation is stable input order with per-section omitted counts. Non-finite scores, malformed/oversized JSON, unknown keys/types/version, or impossible counts make an authorized snapshot corrupt and fail closed. Repeated reads are byte-shape deterministic while live authorization/lifecycle state is unchanged.

Error contract:
| Condition | HTTP | MCP `error_kind` / result |
|---|---:|---|
| Invalid request schema, filter, or link | 422 | `invalid_request` |
| Malformed, missing, or requester-scope-mismatched diagnostic ID | 404 | `diagnostic_unavailable` |
| Valid query with no candidates | 200 | success with `status=ok`, empty bounded stages/results |
| Authorized malformed/oversized/unknown-version snapshot | 500 | `diagnostic_corrupt` |
| Snapshot persistence failure | 503 | `diagnostic_persistence_failed`, no usable diagnostic ID |
| Query/service failure | 500 | `diagnostic_failed`, no raw exception body |
| Deadline exceeded | 504/client timeout | `timeout` |
| Connection/HTTP transport failure | client-side | `transport_unavailable` without HTTP body or raw ID |

Create requires a caller-generated opaque idempotency key (1–128 safe characters), unique within the requester tuple. The row becomes visible only after a complete valid snapshot is committed. Retrying the same key after an ambiguous timeout returns the same diagnostic ID and snapshot; a failed transaction exposes no ID. The MCP client preserves the key across its one bounded retry and otherwise reports timeout without claiming whether the first attempt committed.

**Material assumptions:**
- Slice 5 remains restricted to source-only Session History diagnostics; proactive-memory diagnostics are out of scope. Disproof: canonical acceptance requires proactive traces; action: return to planning before broadening the store.
- A dedicated `history_diagnostic` table with one versioned JSON snapshot is the smallest correct semantic boundary because it cannot count as a lookup/expansion event or become an expansion/delivery parent. Disproof: schema and evaluator tests prove an existing non-funnel store preserves the same guarantees with less code; action: revise before implementation.
- The required requester tuple is container + active session + visibility; actor and historical identifiers remain source filters, not credentials. Disproof: an existing supported integration authorizes diagnostic reads differently; action: stop for security/API replanning.
- Diagnostic-specific storage aggregates and trace counters are observational only and do not alter retrieval order, ranking, filters, use state, or funnel telemetry. Disproof: a focused before/after test detects mutation or result drift; action: fix at the shared read-only boundary before proceeding.

Target files:
Production: `core/models.py`, `core/query.py`, `core/service.py`, `retrieval/vector.py`, `storage/base.py`, `storage/sqlite.py`, `storage/sqlite_schema.py`, `storage/sqlite_search.py`, `api/schemas.py`, `api/routes.py`, `app/mcp/client.py`, `app/mcp/server.py`. Documentation: `docs/http-api.md`, `docs/session-history.md`, `roadmap/features/fix-session-history-evidence-access.md`. Tests: new `tests/test_history_diagnostics_e2e.py`; focused additions to `tests/test_historical_lookup_storage.py`, `tests/test_api.py`, `tests/test_mcp_client.py`, `tests/test_mcp_server.py`, `tests/test_mcp_integration.py`, and evaluator/funnel regression in `tests/test_historical_lookup_funnel_e2e.py`. Files may be removed from this list when reuse makes them unnecessary; adding a new architectural surface requires plan review.

**Plan:**
1. Commit red tests before production edits: schema/idempotency/bounds/corruption; query observations; exact requester/filter contract; error table; non-mutation; and real MCP-to-HTTP create→forget/delete→reread. Credit existing edge coverage instead of cloning it.
2. Add a dedicated `history_diagnostic` table with opaque ID, idempotency key, canonical requester tuple, separately stored saved filters, schema version, and bounded JSON snapshot. It has no foreign key or path to lookup/expansion finalization and no evaluator consumes it.
3. Add the minimum diagnostic-only observations to existing trace/search paths: field-filter exclusion counts, explicit vector-provider availability, authorized scope/index aggregate counts, dedup/final-limit counts, and stable final ranks. Preserve candidate membership, ordering, scores, and normal `/query/debug` behavior.
4. Add explicit service create/read methods. Create invokes the existing source-only executor directly enough to avoid the lookup-event write, builds the version-1 allowlisted snapshot, commits it atomically, and serializes its response through the same live-sanitization method used by read. Read exact-matches the requester tuple, never accepts filter overrides, validates size/schema, and revalidates every stage/fusion/final candidate against current lifecycle, visibility, and saved filters.
5. Add two HTTP operations and schemas. Enforce the bounds and error table above; use the same non-oracular 404 for malformed/missing/out-of-scope IDs; return no diagnostic ID on failed persistence; preserve normal `/query`, `/query/debug`, and History response shapes.
6. Add MCP client methods and two narrow tools. Derive the requester tuple from trusted context, keep optional actor/thread/work/request-lineage values as source filters only, reuse the History deadline, preserve idempotency on bounded retry, suppress HTTP bodies/raw identifiers in errors, and apply the existing History compaction path to report actual caller-visible packaging.
7. Cover empty/min/max/over-max escaped Unicode, duplicate candidates, invalid/non-finite scores, corrupt/oversized/unknown-version JSON, requester tuple mismatch/missing values/canonical container, actor omission versus exact actor, source-filter override rejection, public/global visibility, mid-query and post-save forget/delete, repeated deterministic reads, persistence/service/timeout/transport failure, and full create→mutate→reread lifecycle. Assert lookup/evaluator/finalization rows, accessibility, memory usage audit, query counters, and ranking priors are unchanged.
8. Align docs and mark slice 5 implemented only when every signal is either observed with a named field or explicitly `unknown`/`not_observed`, the real MCP packaging journey passes, and all workflow/review/CI gates are green.

**Verification plan:**
- When a diagnostic query runs against captured/indexed, scope-excluded, lexical-only, vector-only, fused, ranked-out, query-limited, MCP-compacted, or valid-empty fixtures, its named observations shall distinguish the stage at which evidence disappeared without asserting an unobserved cause → `tests/test_history_diagnostics_e2e.py`, focused API/MCP tests.
- When create or reread returns evidence, every candidate shall have passed the same live allowlisted sanitizer; forgetting/deleting during or after creation shall remove identity/text/thread metadata from every stage/fusion/final section → HTTP and real MCP lifecycle E2E.
- When requester scope or diagnostic ID is invalid/unavailable, responses shall follow the error table without becoming an oracle; authorized corruption, persistence failure, service failure, timeout, and transport failure remain separately typed → API/client/tool tests.
- When an ambiguous create times out and retries with the same idempotency key, at most one committed row and one stable diagnostic ID shall exist; failed persistence returns no usable ID → storage/API E2E.
- When diagnostics execute, historical lookup/expansion denominators and delivery finalization, accessibility, memory usage audit, query counters, ranking priors, and ordinary History/debug response shapes shall remain unchanged → before/after DB assertions plus `tests/test_historical_lookup_funnel_e2e.py`.
- When schema initialization runs on fresh and legacy databases, the dedicated table and uniqueness constraint shall be added idempotently without rewriting existing events → `tests/test_historical_lookup_storage.py`.
- Before PR: focused exact nodes, affected subsystem files, `pytest --lf --lfnf=none -q -n 0`, full `pytest tests/ -x -q`, Import Linter, Redline, Workflow, diff checks, and CI shall pass and be recorded.

**Plan review:**
Rejected 2026-09-22 by clean-context high-reasoning reviewer `/root/history_diagnostics_plan_review`: diagnostic/lookup telemetry contamination, unsupported causal claims, underspecified requester/filter authorization, insufficient bounds/redaction, contradictory error handling, and missing target files. The plan above addresses each finding. Revised-plan approval is pending from the same reviewer.

**Approvals:**
Approved by user 2026-09-22: "yes, i told you i approve all the work on this feature. i'm not here all the time so don't wait for me. continue with all the issues we need to fix"

**Exceptions:**
—

**State:** Blocked
<!-- agent-workflow:end -->

## Checkpoint: architecture-review

What is changing: a source-only diagnostic service reuses the existing query executor/trace, adds only missing observational counters, and persists a bounded allowlisted snapshot outside lookup-delivery telemetry.

Why: an in-memory raw debug trace cannot explain a past miss safely, and a diagnostic is not delivered History evidence.

Affected contract / model / boundary: `core/service.py`, `core/query.py`, retrieval trace assembly, and the new diagnostic persistence boundary. Retrieval/ranking/visibility behavior and lookup/expansion funnel semantics remain authoritative and unchanged.

Compatibility / migration risk: medium; normal query/debug/History payloads stay unchanged, while diagnostic creation bypasses lookup-event writes and must preserve candidate ordering exactly.

Verification plan: red core/API lifecycle tests, evaluator-denominator/delivery-finalization regressions, real MCP packaging journey, full suite, and clean-context result review.

## Checkpoint: api-review

What is changing: two additive bounded History diagnostic HTTP operations plus two MCP tools with an explicit requester/filter split, idempotent create, and the documented error table.

Why: verbose evidence must stay off normal History responses and a saved investigation must be safely reread.

Affected contract / model / boundary: new optional surfaces only; `/query`, `/query/debug`, and existing MCP History response shapes remain compatible.

Compatibility / migration risk: medium; caller-visible error/status and retry semantics are new but isolated.

Verification plan: schema/route/client/tool contract tests plus end-to-end create/read/forget/error/timeout/transport cases.

## Checkpoint: persistence-review

What is changing: add a dedicated `history_diagnostic` table containing opaque ID, requester tuple, saved source filters, idempotency key, version, and bounded JSON; no index beyond the uniqueness/access keys required by create/read.

Why: reuse of lookup/expansion telemetry would contaminate semantic denominators and create an invalid delivery/finalization path.

Affected contract / model / boundary: additive schema only; existing rows/tables are untouched, evaluators remain bound to historical lookup events, and diagnostic rows cannot be expansion parents.

Compatibility / migration risk: low-medium; forward-only additive table. Rollback ignores/drops no existing data; old binaries ignore it.

Verification plan: fresh/legacy/idempotent schema tests, transaction/persistence-failure tests, exact scope/idempotency tests, and explicit evaluator/finalization non-interference E2E.

## Checkpoint: security-review

What is changing: saved diagnostics are private to canonical container + active session + visibility, retain source filters separately, and return only fixed allowlisted observations after live reauthorization of every referenced candidate.

Why: raw or stale traces can expose identities after forgetting, deletion, filter change, or requester mismatch.

Affected contract / model / boundary: new narrower boundary than raw `/query/debug`; existing source authorization policy is reused, not broadened.

Compatibility / migration risk: high if incorrect because a snapshot could become an identity oracle.

Verification plan: wrong/missing requester tuple, container canonicalization, actor omission/exact filter, filter-override rejection, public/global visibility, mid-query/post-save forget/delete, malformed/oversized/unknown-version snapshot, raw-identity absence, and deterministic-reread E2E.

## Implementation

Established task context, completed trace/persistence discovery and pre-edit Redline, and received a rejected clean-context plan review. Revised the plan to separate diagnostics from lookup telemetry, enumerate observable signals and bounds, define requester/filter/error/idempotency contracts, and name exact implementation/test files. No test or production code has been edited; implementation remains blocked pending revised-plan approval.

## Evidence

Pre-edit classification: RED with architecture/API/persistence checkpoints and security-sensitive behavior; no intended boundary violation. Clean-context plan review rejection is preserved above with its corrections incorporated.

## Result review

Pending.
