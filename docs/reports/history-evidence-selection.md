# Session History evidence-selection readiness

## Decision scope

The search-quality corrections shipped in PR #272 remain complete. This follow-up
asks whether an agent can select enough historical evidence to answer a task.
Successful search, paging, and expansion do not establish answer sufficiency.
This report records readiness, not a new search-quality score.

The owning [navigation investigation](../../roadmap/features/investigate-history-navigation-and-on-demand-compression.md)
retains its unperformed access-structure and representation comparisons. No
preview, index, compression, reranker, or production change is selected here.

## Bounded evidence checks

The prior [recovery report](session-history-evidence-recovery.md) established that
old private exclusion identities cannot be reconstructed from surviving hashes.
This assessment did not repeat that recovery or open unknown protected content.

The metadata-only delta used the previous census cutoff, exclusive
`2026-09-30 19:39:59.320519 UTC`, through the frozen inclusive cutoff
`2026-10-01 05:48:51 UTC`. It used read-only SQLite, exact repository-container
scope, and excluded the assessment's active thread. There were zero new scoped
History events, hence zero new lookup-linked requests in that interval.
These are readiness counts, not candidate-recovery, injection-precision, or
downstream-task-effect measurements. They do not prove that no new tasks exist.

A separately reviewed alternative inventories at most 100 newly recorded user
requests, ordered by creation time and ID, without reading their text. Ingestion
time alone cannot establish original creation or independence from old protected
sources. Every request, supporting source, and accessible expansion neighbor must
pass that provenance gate before content assessment.

That alternative found 40 non-forgotten user rows across one thread; all fit under
the cap. None had an `occurred_at` value or top-level metadata keys matching the
four inspected patterns (`provider_created`, `event_created`, `origin_created`,
`source_created`), and none linked to a recorded History lookup. This narrow check
does not prove that no other provenance fields exist. Earlier
same-thread rows exist, but that does not establish a task/support relationship.
Thus zero candidates qualified for content opening under the approved gate. This
does not mean the requests are unanswerable or that search failed.

The API accepts caller-supplied source metadata and optional event timestamps;
`created_at` records ingestion. A recent ingestion timestamp cannot rule out old
or backfilled content. The initial source-type filter excluded actual Codex rows
and was discarded; only the corrected all-source-types, `role=user` result above
is evidence. No request or supporting-source text was read.
The request inventory used read-only statements without an explicit multi-query
transaction; it is not claimed as an atomic snapshot. Its earlier-source aggregate
contains overlapping per-request matches, not a distinct-source count, and is not
used to infer sample diversity.

## Reuse and alternative routes

`evals/reliable_pair_runner.py` already captures production History HTTP results,
exact MCP formatting, expansion lineage, and driver transcripts against an
isolated frozen corpus. It keeps answer keys outside the chooser protocol. Reuse
these seams; do not build another retrieval stack.

It is not a ready native-agent baseline adapter: it requires both baseline and
candidate variants and numeric input/output token usage. Native delegated-agent
token usage has not been established here. Its substring scorer also does not
replace independent answer-sufficiency grading. Do not fabricate token counts,
duplicate a baseline into a supposed comparison, or label character counts tokens.
Its existing scripted qualification was not rerun.

Two official public dataset cards were inspected as alternative development
sources: [WildBench](https://huggingface.co/datasets/allenai/WildBench) and
[WildChat](https://huggingface.co/datasets/allenai/WildChat-4.8M). Their viewers
also exposed example rows; those inspected examples are not blind cases.
No raw dataset was downloaded. These sources would require a frozen task pack,
privacy/licensing checks, and suitable answer evidence; generated reference answers
are not automatically factual gold. A public development study cannot substitute
for independent evidence about this installation's session usage.

## Measurement limits and next gate

**Decision: do not run or select a representation change from this sample.**
The readiness slice is complete; the broader study remains evidence-gated.
The next useful input is a prospectively frozen task/source pack with original
creation provenance and a separately held answer key, or recovery of exact old
exclusion identities. Repeating this census without new evidence will not help.
For real-usage confirmation, retain original caller options and full responses as
well. The choice of a verified evaluator adapter and honest cost units remains a
separate execution gate, not a demonstrated product defect.

No source-content assessment, paid evaluator/provider call, or model download ran.
No candidate-recovery gain, evidence-sufficiency score, downstream benefit, or
latency improvement is claimed. Agent execution cost was not measured.

Before any content run, freeze eligible task groups and source IDs, exclusions,
current caller settings, answer rubric, numeric call/opening/character/time
ceilings, and stop rules; independently review them. Use at most six episodes,
separate the chooser from the answer-key grader, and preserve exact responses.
Label the result a current-corpus task assessment, not historical replay or
independent confirmation. Unknown provenance rejects a candidate; it is not a
reason to inspect it and replace it after seeing the answer.

Private readiness scripts and results remain outside Git. The
[Work Record](../../.agent-workflow/tasks/history-evidence-selection.md) records
review, validation, delivery, and the final readiness disposition.
