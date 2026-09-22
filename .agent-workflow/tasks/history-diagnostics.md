<!-- agent-workflow:start -->
**Outcome:**
An authorized caller can create and later reread a bounded Session History diagnostic that explains scope, candidate, rank, and packaging behavior without exposing forgotten or unauthorized history or changing retrieval state.

**Target:**
Pallium.

**Scope:**
Add a source-only History diagnostic create/read contract over the existing query trace; persist one bounded snapshot on the existing historical lookup event; expose it through HTTP and MCP; add focused storage/core/API/tool tests and caller-surface E2E coverage; align Session History docs and roadmap slice 5.

**Constraints:**
Reuse the existing retrieval/ranking trace and historical lookup event; no second ranking stack, new table, dependency, normal-search payload growth, raw thread identity, unbounded trace, or change to accessibility, use counters, ranking priors, visibility, forgetting, search order, delivery finalization, or historical-state warnings.

**Completion criteria:**
A diagnostic distinguishes missing/invalid, valid-empty, scope exclusion, candidate recovery, ranking, packaging, timeout, and transport outcomes; reports requested/effective scope, bounded lexical/vector/fusion evidence, exclusions, and final rank; rereads are deterministic and revalidate live forgetting/authorization; all AGENTS.md boundary/error/lifecycle cases pass through HTTP and MCP.

**Requirement baseline:**
{"source":"roadmap-slice-5","outcome":"An authorized caller can create and later reread a bounded Session History diagnostic that explains scope, candidate, rank, and packaging behavior without exposing forgotten or unauthorized history or changing retrieval state.","scope":"Add a source-only History diagnostic create/read contract over the existing query trace; persist one bounded snapshot on the existing historical lookup event; expose it through HTTP and MCP; add focused storage/core/API/tool tests and caller-surface E2E coverage; align Session History docs and roadmap slice 5.","constraints":"Reuse the existing retrieval/ranking trace and historical lookup event; no second ranking stack, new table, dependency, normal-search payload growth, raw thread identity, unbounded trace, or change to accessibility, use counters, ranking priors, visibility, forgetting, search order, delivery finalization, or historical-state warnings.","completion_criteria":"A diagnostic distinguishes missing/invalid, valid-empty, scope exclusion, candidate recovery, ranking, packaging, timeout, and transport outcomes; reports requested/effective scope, bounded lexical/vector/fusion evidence, exclusions, and final rank; rereads are deterministic and revalidate live forgetting/authorization; all AGENTS.md boundary/error/lifecycle cases pass through HTTP and MCP."}

**Risk:**
High

**Complexity:**
Moderate

**Reason:**
Pre-edit Redline classifies the change RED/contract-sensitive: `core/service.py`, `api/routes.py`, and `api/schemas.py` require architecture/API review, while the additive `historical_lookup_reuse_event` column requires persistence review. Caller-scoped saved reads are authorization-sensitive even though the shared visibility predicate remains unchanged.

**Discovery:**
`/query/debug` already produces requested/effective filters, lexical/vector stages, visibility exclusions, fusion scores, and result summaries through `QueryTrace`, but serializes raw query/filter/candidate identities and never persists a trace ID. Source-only `PalliumService.query` already writes an always-on historical lookup event with caller scope and exposed source IDs; its `exposed_json` shape is evaluator-facing and must not change. No existing table stores the complete trace. Existing shared `matches_filters`, `is_visible`, source forgetting, and lifecycle gates can revalidate referenced source IDs on read. Source-only overfetch/dedup/request-exclusion/final-limit counts are not traced and must be added to the existing routing diagnostics. Ordinary MCP POST errors conflate timeout with generic transport and need diagnostic-specific distinct handling.

**Material assumptions:**
- Slice 5 is restricted to source-only Session History diagnostics, not proactive memory-query diagnostics. Disproof: canonical roadmap or caller cases require proactive traces; action: return to planning before broadening the historical event model.
- A nullable `diagnostic_json` column on `historical_lookup_reuse_event` is the smallest compatible persistence change; `exposed_json`, event types, lookup lineage, and evaluators remain unchanged. Disproof: migration/eval tests show semantic coupling; action: stop and design a dedicated store rather than overload the row.
- Persisted snapshots may contain bounded internal source IDs solely for live revalidation, but public diagnostic responses expose only currently authorized source IDs and no raw thread, actor, container, query text/tokens, index-entry IDs, or source content. Disproof: a requirement needs raw identity/text; action: require explicit security review and revised authorization contract.
- Diagnostic snapshot creation is append-only observability, while diagnostic reads are product-state read-only. Neither may update accessibility, usage audit, retrieval counters, or ranking priors. Disproof: existing shared query execution mutates one of those states; action: add an explicit diagnostic no-mutation mode at the shared boundary before shipping.

**Plan:**
1. Commit red focused tests first for bounded snapshot persistence/migration, create/read scope, empty/invalid/error distinctions, forgetting/authorization reread, non-mutation, and real MCP-to-HTTP lifecycle behavior.
2. Extend source-only trace routing with bounded counts for retrieved, request-identity excluded, deduplicated, final-limit omitted, and final results; do not alter ranking or result selection.
3. Add nullable `diagnostic_json` to the existing historical lookup event and its additive idempotent schema migration. When and only when a source-only query requests trace, persist a compact internal snapshot capped at the existing History maximum; leave normal searches and `exposed_json` unchanged.
4. Add one core read method that exact-matches stored caller scope, parses the snapshot fail-closed, reuses current filter/visibility/forgetting gates for every referenced source, removes stale identities, and returns a bounded identity-safe diagnostic with requested/effective filter presence, lexical/vector/fusion channel/score evidence, exclusion counts, and final ranks.
5. Add additive HTTP create/read routes and schemas. Missing/malformed/out-of-scope IDs return the non-oracular missing contract; valid empty returns 200; corrupt stored snapshots fail closed. Keep `/query` and normal MCP History responses unchanged.
6. Add MCP client methods and two narrow tools: diagnose a History query and reread a saved diagnostic. Reuse context-derived requester scope, explicit optional source filters, and the existing History deadline; return distinct timeout and transport error kinds.
7. Cover empty/min/max/over-max, Unicode, visibility/actor/container/session/work/thread scope, forget-after-save, repeated read, corrupt/missing snapshot, timeout/transport/storage failure, and full create→forget→reread lifecycle. Assert database counters/state are unchanged by reads and normal History contracts remain byte-shape compatible.
8. Align HTTP/MCP/Session History docs and mark only roadmap slice 5 implemented. Stop if correctness requires a new table, ranking change, dependency, public raw identity, or authorization-policy relaxation.

**Verification plan:**
- When a diagnostic is created for lexical, vector, fused, empty, filtered, or truncated History, it shall expose bounded requested/effective scope presence, stage/channel/score counts, exclusions, and final rank without raw thread/text/index identities → focused core/API tests plus caller-surface E2E.
- When a saved diagnostic is reread after a source is forgotten, hidden, moved out of exact filters, or deleted, it shall omit that identity and report bounded read-time exclusion → HTTP lifecycle E2E and MCP-to-HTTP journey.
- When a diagnostic ID is missing, malformed, corrupt, out of caller scope, valid-empty, timed out, or transport-failed, each outcome shall remain distinct without becoming an identity oracle → API/client/tool tests.
- When diagnostic create/read runs, accessibility, memory usage audit, query usage counters, ranking priors, lookup delivery semantics, and ordinary History response shapes shall remain unchanged → before/after database assertions and existing History regression suites.
- When schema initialization runs on new and legacy databases, the nullable snapshot column shall be added idempotently without rewriting existing events → storage migration tests.
- When implementation is ready for review, focused nodes, affected subsystem files, `pytest --lf`, full suite, Import Linter, Redline, Workflow, diff checks, and CI shall pass → recorded commands and PR evidence.

**Plan review:**
Pending clean-context high-reasoning review.

**Approvals:**
Approved by user 2026-09-22: "yes, i told you i approve all the work on this feature. i'm not here all the time so don't wait for me. continue with all the issues we need to fix"

**Exceptions:**
—

**State:** Blocked
<!-- agent-workflow:end -->

## Checkpoint: architecture-review

What is changing: source-only History query orchestration persists a bounded trace snapshot and serves a live-revalidated diagnostic without changing retrieval or ranking.

Why: an in-memory debug trace cannot explain a past miss or remain safe after forgetting.

Affected contract / model / boundary: `core/service.py` historical lookup orchestration and `core/query.py` source-only trace metadata; existing retrieval and visibility models remain authoritative.

Compatibility / migration risk: medium; normal search behavior is unchanged, but a new saved diagnostic read boundary must fail closed.

Verification plan: red core/API lifecycle tests, real MCP-to-HTTP journey, existing History suites, full suite, and clean-context review.

## Checkpoint: api-review

What is changing: additive bounded History diagnostic create/read endpoints, response schemas, client methods, and MCP tools.

Why: verbose diagnostics must stay off normal History responses and be replayable by stable ID.

Affected contract / model / boundary: new optional surfaces only; `/query`, `/query/debug`, and existing MCP History response shapes remain compatible.

Compatibility / migration risk: low-medium; additive contracts with explicit missing/scope/timeout/transport semantics.

Verification plan: schema/route/tool contract tests plus end-to-end create/read/forget/error cases.

## Checkpoint: persistence-review

What is changing: add one nullable `diagnostic_json` column to `historical_lookup_reuse_event` through the existing idempotent additive-column mechanism.

Why: no current store retains the complete bounded History trace needed for safe replay.

Affected contract / model / boundary: schema-only, no data rewrite or index; existing rows remain valid with NULL and `exposed_json` is unchanged.

Compatibility / migration risk: low; forward-only additive nullable column. Rollback can ignore the column; no information is destroyed.

Verification plan: fresh-schema and legacy-column upgrade tests, idempotent initialization, event/evaluator regression tests.

## Checkpoint: security-review

What is changing: a new read operation returns saved diagnostic evidence only after exact caller-scope matching and live visibility/filter/forgetting revalidation.

Why: a stored trace can otherwise become a historical identity oracle after authorization or forgetting changes.

Affected contract / model / boundary: authorization behavior is narrower than raw `/query/debug`; no existing access is broadened and `core/visibility.py` is unchanged.

Compatibility / migration risk: medium-high if incorrect because stale identities could leak.

Verification plan: wrong container/actor/visibility/session/work/thread tests, forget/delete after save, corrupt snapshot fail-closed, raw-identity absence assertions.

## Implementation

Established task context from canonical roadmap slice 5, completed focused trace/persistence discovery, and obtained clean-context pre-edit Redline classification. Planning is blocked only until the required clean-context plan review resolves findings; no production code has been edited.

## Evidence

Pre-edit classification: RED with architecture/API/persistence checkpoints and security-sensitive behavior; no intended boundary violation.

## Result review

Pending.