---
id: fix-session-history-evidence-access
title: Make Session History evidence reliably inspectable
status: done
priority: high
commitment: committed
milestone: pallium-vnext-session-history
lane: stabilization-usability
---

## Outcome

An agent can find a plausible History result, decide whether it is worth opening,
read all of one oversized source through bounded continuation, apply an explicit
source-thread scope when requested, and diagnose a miss without confusing historical
evidence with current state. The feature closes the concrete caller-contract failures
seen in real recap work before Pallium spends more effort on reranking or generated
compression.

## Roadmap relationship

This completed reliability sub-feature belongs to the open
[`improve-session-history-search-quality`](improve-session-history-search-quality.md)
umbrella. No delivery slice remains here. Its results are the caller baseline for
future search-quality work, but they do not close the umbrella or validate ranking,
generated compression, or downstream task improvement. The broader
[`investigate-history-navigation-and-on-demand-compression`](investigate-history-navigation-and-on-demand-compression.md)
study remains separately queued.

## Why this was prioritized

One extended recap used four progressively narrower searches and 18 expansions. Sixteen
expansions were driven primarily by empty excerpts, one by an insufficient excerpt, and
one repeated the same oversized source in an unsuccessful attempt to reach its tail.
Every major historical fact was present on the first page of some targeted query, usually
at ranks 1–10. Ten of 40 result slots repeated an exact source across queries, and roughly
six expansions covered semantically overlapping coordination or status material.

The strongest reproducible defect is same-source truncation. `pallium_expand_source`
silently clamps caller requests to 4,000 characters, returns only a prefix marked
`content_truncated`, and provides no offset or continuation handle. Requests for 18,000
and 50,000 characters therefore reached effectively the same cutoff. The omitted tail
could not be recovered through neighbor expansion. This is an evidence-access failure,
not a ranking failure.

The usage evidence is private and must stay uncommitted. Preserve only the anonymized
failure classes and aggregate counts above. Use deterministic synthetic fixtures or a
redacted local replay when validating behavior.

## Delivery order

### 1. Freeze failures at the caller surface

Before or alongside each production slice, add the smallest regression that fails on
the current behavior. PR evidence records the baseline failure and the passing fix.
Credit existing coverage instead of cloning tests. Every changed behavior also receives
an E2E journey through the same HTTP or MCP surface used by an agent.

Required regression matrix:

| Failure class | Required observable regression |
|---|---|
| Oversized source has unreachable tail | Search → expand an oversized source whose required evidence is beyond the first 4,000 characters. Continue until complete without repeating or skipping text. Assert bounded pages, stable source identity, Unicode/escaped-text boundaries, `parent_lookup_id` lineage, invalid/negative/over-max offsets, end-of-content idempotence, and forgotten/unauthorized source behavior on every page. |
| Requested expansion budget is silently clamped | The response exposes the effective page budget and whether more content exists. A request above the supported maximum cannot appear to have honored the larger value. Minimum, maximum, and over-maximum requests have explicit deterministic results. |
| High-count search returns blind hits | Under the maximum supported result and character pressure, every exposed hit has either a non-empty recognizable preview or an explicit stable navigation path to obtain one without rerunning search. No result silently presents `excerpt: ""`. If fewer hits are shown per page, continuation preserves the frozen candidate order and access to every retained candidate. |
| Requesting-session identity and source-thread scope are conflated | Broad search without a source-thread filter spans eligible container history; an explicit source-thread filter remains exact. Request-session identity is used only for telemetry and response-local `current`/`other-N`/`unknown` labels. Raw thread IDs never leak. Cover same-thread, other-thread, unknown-thread, exact-work combinations, and empty scope. |
| History miss cannot be explained | A read-only History diagnostic path reports requested/effective filters, lexical/vector candidate stages, match channel or score information, bounded exclusion reasons, and final rank sufficiently to distinguish capture, scope, candidate-recovery, ranking, and packaging failures. Diagnostics remain caller-scoped and redacted: unauthorized or forgotten source identities, text, and thread metadata never appear, including when a saved diagnostic is read after forgetting. It must not update accessibility, use counters, or ranking priors. Invalid links, valid empty results, timeouts, and transport failures remain distinct. |
| Rewritten searches cause repeated work | Agent guidance tracks each opened `source_item_id` plus continuation position across bounded retries. It must not restart a completed source or already-delivered page, but must allow unseen continuation offsets and retry-safe failed deliveries. A deterministic replay includes a partially read source recurring after query repair and records searches, unique versus repeated candidates, pages, expansions, and evidence recovered. Do not add cross-query suppression or collapse semantically similar sources unless the replay shows guidance is insufficient and provenance/date/expansion paths remain available. |
| History is mistaken for proof of completion | Search and expansion retain the historical-state warning and lookup lineage at every budget boundary. The E2E journey verifies current repository/service state separately and asserts that retrieval alone changes no accessibility or ranking state. |

### 2. Add bounded continuation for one source item

Implement the smallest cursor or character-offset contract that can continue the anchor's
content. Reuse the source-context path and its visibility, redaction, forgetting, and
delivery-finalization checks. Do not split ingestion records or introduce generated
summaries to solve a transport paging problem. The continuation contract must be stable
under Unicode and JSON escaping and must not let a later page bypass a newly forgotten or
unauthorized source.

Implementation evidence (2026-09-22): the first continuation PR adds MCP-local
Unicode-code-point paging for one oversized anchor, an explicit effective response cap,
and a caller-carried revision over the freshly authorized redacted content. Real
MCP-to-HTTP coverage reconstructs a multi-page Unicode/escaped source without gaps,
proves retry and terminal behavior, rejects equal-length stale rewrites, and rechecks
wrong-container and forgotten sources. The HTTP/core/storage contracts remain unchanged.
At that checkpoint, only delivery slice 2 was complete; the feature remained queued for result navigation,
scope separation, diagnostics, and guidance/replay. Integration-skill guidance remains
owned by slice 6.

### 3. Make search results actionable under the existing budget

Stop tuning the rejected density window and minimum-preview allocation. Choose the
smallest caller contract that prevents blind result selection while retaining access to
the useful rank-9/rank-10 cases observed in real work. A stable paged result view is a
candidate; merely lowering the result count without continuation is not, because prior
development cases contained uniquely useful evidence below rank five.

Hold candidate membership and ordering fixed when evaluating presentation. Report this
as agent-visible evidence sufficiency and navigation cost, not candidate recovery or
downstream task effect.

Implementation evidence (2026-09-22): delivery slice 3 is implemented in both Session History MCP search tools. `limit` is bounded to 1–50; stateless `result_offset`/`result_revision` continuation binds the complete ordered candidate window and requires restart on stale revisions. Pages report the effective budget, offsets, `has_more`, total count, and per-page lookup lineage. Hits retain recognizable previews or `preview_unavailable` with a stable expansion path; singleton fit errors do not finalize or skip candidates. Exact-end and over-end offsets return empty terminal pages. Retrieval, ranking, accessibility, scope, redaction, forgetting, and historical-state semantics remain unchanged. Focused and caller-surface tests cover boundaries, multi-page traversal, stale restart, Unicode/escaped text, replacement metadata, terminal behavior, and page audit lineage. At that checkpoint, only slice 3 was complete; slices 4–6 were still planned.
### 4. Separate active-session attribution from source scope

Define distinct names and semantics for the requesting session used by telemetry and the
optional historical source thread used as a filter. Keep container, actor, visibility,
exact-work, and forgetting enforcement unchanged. Broad search remains broad when no
source-thread filter is requested; exact-work search never broadens.

Implementation evidence (2026-09-22): delivery slice 4 separates the active
requesting session from optional historical source scope across MCP, HTTP, query
orchestration, audit attribution, and result-page revisions. Broad History omits
the source-thread filter, `source_thread_ref` is exact when supplied, and
exact-work search intersects it. Source-only filter resolution no longer
consumes runtime-context relaxation; proactive queries are unchanged. Lookup
lineage and `session_id` use `active_session_ref`, while response grouping
remains `current`/`other-N`/`unknown` without raw session IDs. Focused
payload, schema, broad/exact/empty, exact-work, lineage, audit, visibility,
forgetting, and MCP-to-HTTP lifecycle tests cover the split. Delivery slices
2–5 were implemented; slice 1's regression matrix remained active through the then-planned
guidance/replay slice 6.

### 5. Expose bounded History diagnostics

Reuse the existing query trace and debug machinery instead of creating a second ranking
stack. Keep verbose scores and exclusion details off the normal search response. The
diagnostic surface is for investigation and replay, remains caller-scoped, and
revalidates forgetting on read. Normal callers receive only compact match cues that
survive response compaction when useful.
Implementation evidence (2026-09-23): slice 5 is implemented through `POST /history/diagnostics` and `POST /history/diagnostics/{id}/read`, plus `pallium_create_history_diagnostic` and `pallium_read_history_diagnostic`. Creation and reread require the requester tuple (`container_ref`, non-empty `active_session_ref`, and `visibility`); saved source filters are separate and do not identify the requester. Snapshots are bounded, versioned, persisted outside lookup/expansion telemetry, and idempotent by request key. Both operations apply the same live authorization/forgetting sanitization, so forgotten or unauthorized source details are removed without revealing ID existence. Invalid requests, valid-empty results, corrupt snapshots, persistence failures, timeouts, and transport failures remain distinct. Diagnostics are observational only: they do not mutate lookup/accessibility, forgetting, ranking, or delivery state.

### 6. Tighten retry guidance and run the end-to-end replay

Update all supported Pallium-memory skill copies consistently so agents reuse lookup
lineage, remember completed source pages during query repair, continue unread pages,
bound retries, and separate a historical recap from live verification. Re-run one
anonymized deterministic version of the observed recap. Compare searches, unique
candidates, exact repeats, expansions, returned characters, latency, and recovered
required evidence. This is a downstream
caller-efficiency check only if an agent actually performs the task; otherwise label it
navigation or presentation evidence.

Implementation evidence (2026-09-23): slice 6 is implemented without production API, storage, retrieval, ranking, or dependency changes. Every supported skill copy, generated/global guidance block, the OpenCode command, and the Claude/Codex integration docs now require a delivered-page ledger across query repair, identical bounded retry of failed pages, unread-page continuation, page-specific lookup lineage, content-revision revalidation, and separate live verification; each compact surface links to the full byte-identical procedure. The deterministic replay compares restart-from-zero and revision-aware ledger policies through the real MCP search/expansion tools over the in-process HTTP app. Focused tests cover partial and completed recurrence, more than two pages, Unicode/escaped content, typed and untyped transport errors, stale-revision exhaustion, equal-length replacement, empty-to-empty, empty-to-nonempty, lineage, no gap/duplicate, and the two-query-repair bound. The slow real-MCP oracle requires the complete unique ordered source after the first query exhausts all delivery retries, so a prefix, gap, reordering, or truncated repair cannot pass.

One anonymized single-run comparison measured navigation/presentation only:

| Metric | Restart baseline | Revision-aware ledger |
|---|---:|---:|
| Searches / search-result pages | 2 / 2 | 2 / 2 |
| Candidate occurrences / unique / exact repeats | 2 / 1 / 1 | 2 / 1 / 1 |
| Expansion attempts / delivered pages | 87 / 84 | 86 / 83 |
| Repeated delivered expansion pages | 1 | 0 |
| Returned characters | 5,657 | 5,584 |
| Observed latency | 0.949 s | 0.950 s |
| Required evidence recovered | yes | yes |

Latency is observational and has no pass/fail threshold. This replay does not measure candidate recovery, injection precision, or downstream-task effect. A separate live check confirmed the installed service was healthy, vector and embedding providers were ready, no items were pending, and no recent queue failures existed; no restart was needed because this slice changes no runtime service code.

## Budget-aware execution

- Default to deterministic fixtures and zero paid model calls. Do not repeat the rejected
  excerpt-allocation studies or the unvalidated 4,000-character search-response trial.
- Deliver in the ordered slices above. Stop after any slice whose evidence invalidates the
  next assumption and return the feature to planning rather than carrying stale scope.
- Delegate mechanical fixture/test work to a lower-cost agent. Use a stronger clean-context
  reviewer for the paging, scope, visibility, and API-contract decisions and for final
  cross-slice review. The primary agent owns integration, reviews every delegated change,
  and keeps the Work Record and this feature aligned.
- Run focused test nodes during development, affected History subsystem files after each
  coherent slice, known failures with `--lf`, and the full non-slow suite once before each
  PR. Run slow-marked replay/eval targets only when their slice needs them.
- Prefer separate coherent PRs for continuation, result navigation, scope semantics,
  diagnostics, and guidance/replay. Do not combine unrelated retrieval-model work.

## Non-goals

- Selecting or shipping a cross-encoder, late-interaction model, vector store, automatic
  query rewriter, generated recap service, or persistent history index.
- Treating the observed recap as evidence that ranking generally fails. The local
  reranking study in `improve-session-history-search-quality` remains conditional on a
  candidate-availability preflight that finds enough rank-only failures.
- Collapsing semantically similar sources when they have distinct provenance, dates, or
  expansion paths.
- Weakening visibility, actor/container isolation, exact-work scope, redaction,
  forgetting, retention, or the historical-versus-live-state distinction.
- Replacing the broader work-grouping, index-first navigation, or on-demand-compression
  comparison. That investigation follows this reliability work.

## Done when

1. Every row in the regression matrix is linked to existing or new focused tests and at
   least one caller-surface E2E journey. New failure reproducers demonstrably fail before
   the fix and pass after it; existing tests are cited rather than duplicated.
2. An authorized caller can page an oversized source to completion with stable identity,
   explicit effective limits, correct lookup lineage, and no gap or overlap. Empty, exact
   boundary, over-boundary, Unicode, stale cursor, forgotten, visibility, and lifecycle
   cases are covered.
3. High-count search never leaves an exposed result silently indistinguishable because
   its excerpt is empty, and every retained candidate remains reachable in frozen order
   under an explicitly reported response/token budget.
4. Active-session attribution and optional source-thread filtering are separate contracts
   with tests for broad, thread-exact, and exact-work behavior. No raw session identity is
   exposed by response-local grouping.
5. History diagnostics can classify capture/scope/candidate/rank/presentation failures
   without changing accessibility or ranking state. Normal responses remain bounded.
6. The anonymized replay reports exact-repeat and expansion cost before and after without
   claiming candidate recovery, injection precision, or downstream task effect unless
   that layer was actually measured. Live verification remains a separate explicit step.
7. Documentation, tool descriptions, every installed skill template, roadmap state, and
   the shipped contract agree. All required E2E edge cases from `AGENTS.md` pass.

## Dependencies and ordering

This completed Session History delivery item converted the actionable caller-contract
findings from `improve-session-history-search-quality` into tested behavior. It now
provides the reliability baseline for
`investigate-history-navigation-and-on-demand-compression`. It reused PR #169's
response-local labels and expansion handoff, PR #166's qualified paired runner when a
paired agent journey was justified, and current raw History search/expansion telemetry.

With this feature closed, resume the remaining search-quality umbrella. Run the local
reranking preflight only if real cases still show necessary evidence present in the fixed
candidate window but ranked too low.
