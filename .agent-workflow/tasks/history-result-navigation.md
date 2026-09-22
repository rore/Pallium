<!-- agent-workflow:start -->
**Outcome:**
An agent can inspect every retained high-count Session History result under the existing response budget without blind empty previews or losing lower-ranked candidates.

**Target:**
Pallium.

**Scope:**
Add stateless result-page continuation to both Session History MCP search tools in app/mcp/server.py; add focused and real MCP-to-HTTP tests; align docs/session-history.md and roadmap/features/fix-session-history-evidence-access.md for delivery slice 3.

**Constraints:**
Keep the 2,000-character search response cap, existing HTTP/core/storage/schema/dependencies, candidate membership and ordering, exact-work exactness, visibility/redaction/forgetting, response-local session labels, and historical-state warning unchanged. Do not alter ranking or candidate recovery. Retrieval alone must not update accessibility or ranking state. Finalize only the results delivered on each successful page. Never expose raw thread identity.

**Completion criteria:**
Each exposed hit has a recognizable preview or explicit stable expansion path; every retained candidate remains reachable in frozen order through bounded revision-checked pages; page telemetry matches delivered IDs; invalid and stale pages finalize nothing; existing History governance and semantics remain intact; required tests and workflow checks pass.

**Requirement baseline:**
{"source":"work-record-initial","outcome":"An agent can inspect every retained high-count Session History result under the existing response budget without blind empty previews or losing lower-ranked candidates.","scope":"Add stateless result-page continuation to both Session History MCP search tools in app/mcp/server.py; add focused and real MCP-to-HTTP tests; align docs/session-history.md and roadmap/features/fix-session-history-evidence-access.md for delivery slice 3.","constraints":"Keep the 2,000-character search response cap, existing HTTP/core/storage/schema/dependencies, candidate membership and ordering, exact-work exactness, visibility/redaction/forgetting, response-local session labels, and historical-state warning unchanged. Do not alter ranking or candidate recovery. Retrieval alone must not update accessibility or ranking state. Finalize only the results delivered on each successful page. Never expose raw thread identity.","completion_criteria":"Each exposed hit has a recognizable preview or explicit stable expansion path; every retained candidate remains reachable in frozen order through bounded revision-checked pages; page telemetry matches delivered IDs; invalid and stale pages finalize nothing; existing History governance and semantics remain intact; required tests and workflow checks pass."}

**Risk:**
High

**Complexity:**
Moderate

**Reason:**
Redline classifies `app/mcp/server.py` as gray/watch with no boundary risk, which sets an Elevated floor. Engineering judgment raises this to High because optional continuation inputs and paging metadata change a caller-facing MCP contract. Moderate complexity covers shared compaction, two tools, delivery telemetry, lifecycle edges, and E2E proof.

**Discovery:**
`_compact_history` currently projects up to `limit` hits, then globally removes cues and shrinks excerpts to empty before dropping tail hits under the 2,000-character cap. Both broad and exact-work tools share it and finalize only its surviving IDs. Existing HTTP search already returns the bounded candidate window, so MCP-local stateless paging can preserve retrieval semantics. A live ten-hit History search on 2026-09-22 returned nine empty excerpts while expansion recovered the first source; the owning roadmap reports 16 blind expansions, useful evidence as low as ranks 9-10, and rejects merely lowering the limit. Existing Relay/source paging provides repository conventions. Redline found gray + `app/**` watch, no checkpoint or boundary violation; the MCP contract is not presently classified by policy.

**Material assumptions:**
- Re-fetching the same bounded candidate window and validating a digest of its ordered projected hits is sufficient to keep continuation stateless. Disproof: unchanged request/data produces unstable membership or representation; action: stop and return to planning for a server-owned snapshot/token.
- One complete actionable hit can always fit the 2,000-character envelope after existing optional update-detail trimming. Disproof: a valid minimum hit cannot fit without emptying its preview or safety metadata; action: define a deterministic insufficient-budget error before implementation continues.
- Existing deferred-delivery finalization accepts a page subset and needs no HTTP/core change. Disproof: finalization cannot record only page IDs or cannot leave stale/error attempts unfinalized; action: stop, expand scope, and reclassify before editing other layers.

**Plan:**
1. Add red tests first for the currently observed empty-preview/high-count failure and for a real MCP-to-HTTP broad/exact search journey that must traverse all retained candidates in order.
2. Extend both MCP tools with strict optional `result_offset` and `result_revision` inputs. Refactor `_compact_history` only enough to build the existing projected candidate window once, hash its ordered visible representation, validate continuation, and greedily emit complete actionable hits within the existing envelope. Expose `effective_max_chars`, `result_offset`, `next_offset`, `has_more`, `total_count`, and `result_revision`.
3. Preserve source IDs as the explicit expansion path when a backend excerpt is genuinely empty; never create an empty excerpt through response compaction. Keep full candidate membership/order fixed and return a stale-revision restart error if any projected candidate changes between calls.
4. Finalize only the current page's IDs; errors and stale continuations finalize none. Keep broad/exact search, active-session grouping, replacement guidance, historical warning, and all visibility/forgetting gates unchanged.
5. Align user documentation and mark only delivery slice 3 complete in the owning feature. Stop if tests require HTTP/core/storage/schema/dependency changes or any ranking/candidate-selection change.

**Verification plan:**
- When ten high-pressure results include useful lower ranks, all retained IDs shall be reachable once in frozen order and no compaction-created empty excerpt shall be exposed → focused presentation tests plus real MCP-to-HTTP broad and exact-work E2E.
- When Unicode, escaped text, replacement metadata, and a genuinely empty backend excerpt are paged, responses shall remain within 2,000 characters and each hit shall have a preview or explicit expansion path → focused boundary tests.
- When offset/revision boundaries are exercised, malformed/negative/missing/stale/exact-end/over-end/retry cases shall be deterministic and advancing or terminal → FastMCP validation tests and caller-surface E2E.
- When pages succeed or fail, deferred delivery shall contain exactly delivered ordered IDs, and stale/error pages shall finalize none → mocked finalization tests plus persisted E2E audit reads.
- When existing broad/exact/scope/visibility/forgetting/warning paths run, behavior shall remain unchanged → existing History MCP/presentation/integration suites.
- Before review, all required checks shall pass → focused nodes, affected History subsystem files, `pytest --lf --lfnf=none -q -n 0`, one full `pytest tests/ -x -q`, agent-workflow checker, redline report, and `git diff --check`.

**Plan review:**
Pending clean-context review.

**Approvals:**
Approved by user 2026-09-22: "yes, i told you i approve all the work on this feature. i'm not here all the time so don't wait for me. continue with all the issues we need to fix"

**Exceptions:**
—

**State:** Blocked
<!-- agent-workflow:end -->

## Checkpoint: api-review

What is changing: add optional result-page continuation inputs and explicit paging metadata to both Session History MCP search tools while keeping the 2,000-character response cap.

Why: high-count searches currently compact previews to empty strings and can hide lower-ranked retained candidates, forcing blind expansions and rewritten searches.

Affected contract / model / boundary: additive MCP tool input/result semantics in `app/mcp/server.py`; no HTTP, core, storage, schema, visibility, or dependency change is planned.

Compatibility / migration risk: medium — existing calls remain valid, but new callers may depend on revision, terminal-page, and per-page delivery semantics.

Verification plan: tests-first focused compaction boundaries, strict FastMCP validation, real MCP-to-HTTP broad/exact lifecycle journeys, exact delivery audit assertions, affected suites, full suite, workflow, and redline checks.

## Implementation

Discovery and classification complete. No production or test files changed. The Windows sandbox constraint has not yet been encountered in this worktree.

## Evidence

Pending tests-first baseline.

## Result review

Pending.
