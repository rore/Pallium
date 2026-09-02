<!-- agent-workflow:start -->
**Outcome:** Historical search no longer spends a visible result slot on a duplicate database row representing the active user request.

**Target:** Pallium.

**Scope:** Internal source-only query exclusion using the already validated request source identity, focused HTTP/query E2E tests, the private 12-case audit rerun, and aligned roadmap evidence.

**Constraints:** No public API, schema, authorization, ranking-score, ingestion, visibility, or integration change; do not hide identical wording from a different stable source identity; preserve top-K refill, response budgets, and zero additional storage reads beyond the existing request-link lookup; no paid/model calls; do not restart the live service while unrelated wake work is active.

**Completion criteria:** When `request_source_item_id` is supplied, every candidate with the same canonical `(source_type, source_id)` shall be excluded before visible top-K selection and the next distinct eligible result shall fill the slot; a different source identity with identical text shall remain eligible; missing/invalid/out-of-scope request links shall retain current fail-closed behavior; the same 12-case local audit shall report zero request-identity slots and quantify direct/background/irrelevant top-three results.

**Risk:** Elevated

**Complexity:** Moderate

**Reason:** Pre-edit redline marks `core/service.py` red and `core/query.py` gray/watch with architecture review required, but detects no API, schema, security, persistence, runtime-config, or boundary change. The change is narrow but spans validated service context and pre-limit ranking.

**Discovery:** A production-shaped, zero-model-call audit reran 12 historical requests across five sessions against an isolated paired SQLite/vector snapshot. All 12 searches succeeded, current result pages had zero internal duplicate slots and complete session metadata, but all 12 ranked a second row for the active request at #1. Each duplicate matched the linked request on source type, source ID, event and ingest times, actor, role, container, thread, and normalized content; only the internal row ID differed. `request_source_item_id` is validated and loaded in `PalliumService.query` but is not passed to `QueryExecutor`; source-only selection limits after `_collapse_source_duplicates`. The schema defines `(source_type, source_id)` as canonical unique identity, while the local corpus contains legacy duplicates from before that index could be enforced.

**Material assumptions:** `(source_type, source_id)` identifies one logical source across duplicate rows, as expressed by `uq_source_items_source_type_source_id` and `find_source_item`; invalidate if review finds a supported case where the same pair represents different logical turns, then return to planning. Filtering before collapse/limit can reuse fields already present on `QueryResultItem`; invalidate if any provider omits either field for source hits, then add a conservative exact-ID fallback rather than a storage scan.

**Plan:** Reuse the linked `SourceItem` already loaded by `PalliumService.query` and pass its canonical `(source_type, source_id)` through a new optional internal `QueryExecutor.query` argument only for source-only search. Filter matching source hits immediately after retrieval and before normalized-content collapse and top-K slicing, so overfetch naturally fills the freed slot and trace/result summaries continue to reflect visible output. Keep `request_source_item_id=None` and non-source-only behavior bit-for-bit unchanged. Add focused executor coverage for same identity/different row ID, identical text/different identity, empty/max/over-max refill, Unicode IDs, and absent exclusion; extend public HTTP lifecycle coverage to prove valid linked request duplicates are absent while invalid scope still fails closed. Rerun focused/performance/full tests proportionately, then rerun and manually label the same private 12-case audit with no model calls. Stop and re-plan on API/schema changes, an added storage read, provider contract gaps, or any different-identity suppression.

**Verification plan:** When retrieval returns the linked request plus a legacy row with the same source identity, neither shall be visible and the next distinct candidate shall fill the requested limit -> QueryExecutor unit/integration test and HTTP source-only E2E. When identical Unicode content belongs to a different source identity, it shall remain eligible -> focused boundary test. When no request link is supplied, existing normalized duplicate behavior and ranks shall remain unchanged -> regression test. When request linkage is missing, forgotten, wrong-role, or cross-scope, the HTTP endpoint shall retain its existing 422 fail-closed contract -> existing plus focused lifecycle E2E. When the local 12-case replay runs, all calls shall succeed with zero request-identity slots and the private manual sheet shall report injection-precision categories without model calls -> isolated snapshot audit and aggregate-only evidence.

**Plan review:** Pending clean-context review.

**Approvals:** Not required at this risk level.

**Exceptions:** —

**State:** Ready to implement
<!-- agent-workflow:end -->

## Implementation

- 2026-09-02: Created isolated branch `codex/fix-history-request-identity-exclusion` from merged main. Completed read-only production-shaped audit and pre-edit redline classification; no repository code was edited before this Work Record.

## Evidence

- Private audit artifacts remain under the local temporary audit directory and must not be committed. Pre-fix aggregate: 12 cases, five sessions, zero query failures, 12/12 top-one request-identity duplicates, zero post-collapse duplicate slots, and zero unknown-session slots.

## Plan review

- Pending.

## Result review

- Pending.