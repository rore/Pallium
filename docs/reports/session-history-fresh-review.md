# Session History: expanded evidence review, 2026-09-30

## Decision

Correct one evaluator eligibility defect: `actor_ref` filters historical sources;
it is not the identity of the user request that caused a lookup. The evaluator
incorrectly required those actors to match, excluding valid linked searches.
Remove that equality check, preserving every other request and source guard.

Do not change ranking, duplicate collapse, response budgets, or agent guidance on
this evidence. The expanded census found too little demonstrably unprotected,
independent evidence for the prospective equivalent-result review. That review
remains open; this report does not close the search-quality umbrella.

## Population, expansion, and protection

The serving checkout and investigation base were `e0e38178`. Pickup verified the
installed service, its configured database, health, and embedding-provider status.
Inventory used SQLite read-only mode with `query_only=ON`, limited to this
repository's exact container. The cutoff was the investigation's first lookup;
that lookup and later events are excluded. This is a current retained-data census,
not a complete historical snapshot or a search replay.

| Period before the cutoff | Delivered lookups | Delivered expansions | Linked lookups passing metadata checks | Distinct linked requests / sessions |
|---|---:|---:|---:|---:|
| Through September 11 | 244 | 186 | 127 | 71 / 17 |
| September 12–22 | 21 | 39 | 8 | 3 / 3 |
| September 23 onward | 0 | 1 | 0 | 0 / 0 |
| Total | 265 | 226 | 135 | Not summed across periods |

The earlier period also contains 109 unlinked lookups and eight missing linked
requests. Its counts differ from earlier multi-container studies because this
census is container-scoped and observes currently retained rows. Do not subtract
these totals from an earlier study to infer data loss.

Fresh usage was insufficient, so the inventory expanded to all older retained
lookup metadata in scope. The 21 September 12–22 lookups include 13 without a
direct request link and one empty-result lookup, which is also unlinked. Keep
these in descriptive accounting, but do not infer task success or failure from
them. The eight linked lookups form three request/session groups, not eight
independent tasks. All have ten exposed source IDs.

The protocol was frozen before content review: batches of up to 12 eligible
episodes, at most 60, with independence grouping, protected confirmation cases,
and an explicit uncertainty stop on eligible-pool exhaustion. Exact previous
holdout manifests could not be recovered. Earlier source contents therefore
remained unopened; query metadata was processed only for overlap checks.
Five of the eight newer linked lookups share exposed source IDs with
pre-September-12 events; all three groups contain such overlap. None qualified
as demonstrably untouched confirmation. Source content and fingerprints remained
unopened; no content-grading batches or current-corpus retrieval replay ran.
The intended six-information-need/four-session coverage was not met.

Private protocol, inventory script, aggregate, case manifest, and hashes of located
earlier artifacts are retained under `.local/history-search-fresh-review/` on the
originating machine. They are deliberately not checkout dependencies or committed
corpus data. Query metadata and exposure IDs establish overlap, not content
equivalence. Missing original tool arguments also prevent exact historical replay.

## What the expanded groups establish

| Anonymous group | Lookups / distinct normalized queries | Exposed slots / unique source IDs | Parented expansions / lookups expanded |
|---|---:|---:|---:|
| A | 1 / 1 | 10 / 10 | 0 / 0 |
| B | 5 / 5 | 50 / 32 | 18 / 4 |
| C | 2 / 2 | 20 / 14 | 2 / 2 |

These groups show repeated source exposure across different queries and varied
expansion behavior. They do **not** establish redundant text, a bad query, an
unhelpful result, or verified downstream use. Group A is a counterexample to
treating expansion as inevitable; without task outcome it is neither a success
nor misuse. The unlinked empty result likewise cannot be classified as a miss.

| Failure class | Finding | Supported action |
|---|---|---|
| Request-link measurement | All eight newer linked events have an omitted search actor and a populated request actor. The evaluator adds an equality restriction absent from the caller contract. | Correct the evaluator and add a generic caller regression. |
| Candidate recovery / ranking | No new directly linked post-reliability-release lookup; older protected content and original arguments unavailable for this review. | No ranking comparison or quality estimate. |
| Equivalent-result presentation | Repeated source IDs across queries are observable; semantic equivalence and lost provenance are not established. | Keep prospective content-equivalence review open. |
| Navigation / query repair | Twenty expansions are parented to six of the eight linked lookups; eight distinct queries are observed. | Do not score source choice, repair benefit, or downstream use from counts. |
| Corpus and study provenance | Exact old holdout identities unavailable. | Restore lineage before reusing overlapping contents, or collect disjoint prospective cases. |

## Fix and regression evidence

`load_corpus` now admits valid request links regardless of an absent or different
source actor filter. It still validates request container, session, visibility,
role, lifecycle, content, and timing; source visibility, filtering, redaction, and
forgetting are unchanged. This is measurement alignment, not a production search
change. The eight observations identify the bad predicate; they are not claimed
as eight fully answerable or replay-eligible tasks.

The HTTP regression ingests two older sources with different Unicode actors,
links a user request, and performs both unfiltered and explicitly actor-filtered
searches. Persisted audit reads and evaluator loading assert exact event IDs,
request text, and source IDs in both `current_replay` and `as_of_lookup` modes.
The explicit filter exposes only its matching source. The regression failed on
the old evaluator with zero admitted cases, then passed after the one-condition
correction. Invalid-link attrition is also tested in both modes. Both affected
test files passed together: 58 tests. Whole-change validation and independent
review evidence belong in the linked Work Record.

No paid evaluation calls, model downloads, corpus/index writes, or candidate
ranking experiments were performed. Agent research/review consumed normal agent
execution; monetary cost was not measured. Counts above measure telemetry and
measurement eligibility only: **not candidate-recovery accuracy, injection
precision, or downstream task effect**. Tokens, search latency, evidence
sufficiency, and content-equivalence prevalence were not measured.

## Remaining next action

Recover the prior exclusion manifests, or collect clearly disjoint prospective
linked cases with original query options and complete caller payloads. Freeze
development/confirmation groups before opening contents. Review equivalence while
retaining dates, provenance, and every source-opening path. Only a remaining
rank-only question can trigger the existing zero-model fixed-candidate preflight;
paid scorer comparison and broader navigation/compression remain separate gates.

Owning [feature](../../roadmap/features/improve-session-history-search-quality.md)
and [Work Record](../../.agent-workflow/tasks/history-search-fresh-review.md).
