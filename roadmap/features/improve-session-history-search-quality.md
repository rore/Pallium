---
id: improve-session-history-search-quality
title: Improve Session History search and agent search guidance from real usage
status: queued
priority: high
commitment: committed
milestone: pallium-vnext-session-history
lane: investigation
---

## Summary

Improve the path from an agent's need for earlier work to the right, inspectable
evidence. Investigate existing data more widely than the initial ten-case diagnostic,
then implement the smallest supported fixes. The question is how to improve history
search and its use, not whether history can help in principle.

Separate retrieval quality, result/excerpt usability, and agent search behavior.
Different failure classes need different fixes. The preliminary suggestions below
are hypotheses to test, not a predetermined implementation plan.

## What we know already

A September 7 diagnostic used four earlier real user questions with selected relevant
sources and six logged agent queries. It tested current source-only search at limit 3,
limit 10 on misses, three exact-work variants, one focused retry, and two bounded
expansions. No paid model calls. Findings:

1. **Finding hidden by excerpt.** A qualification source ranked third, but its short
   excerpt showed approval/planned actions; the result was later in the same source.
   Another mechanism answer ranked first after query repair, but its excerpt ended
   before the evidence-fetch details. Expansion exposed both. Investigate messages
   combining progress and final output, and query-focused excerpts; do not invent
   summaries or claims.
2. **Query repairs help selectively.** Naming source expansion moved its selected
   answer from outside top ten to rank one. A focused applicability query recovered
   its anchor at rank two. Other rewrites lost evaluation/qualification anchors.
   Neither longer nor keyword-only queries are universally better.
3. **Limit affects candidates and ranking.** One query omitted a source at limit
   three but returned it at rank two when requesting ten. Sampled fusion candidate
   pools grew from 12 to 40 per channel. Verify current behavior and compare bounded
   candidate budgets independently of displayed count. Prefix stability is a
   hypothesis, not an already agreed production contract.
4. **A hard-retrieval case exists.** A filtering-evidence source was eligible and
   visible in lexical-stage traces but missed top ten for both initial variants.
   A focused follow-up recovered it at rank six. Investigate candidate truncation,
   fusion, term handling, and competing documents before prescribing a fix.
5. **Old exact-work misses can be expected.** Broad search recovered older hook
   plans without work-reference metadata; exact search excluded them. A source with
   matching metadata was recovered exactly. Work references were recently introduced:
   this is not evidence that scoped search is defective.
6. **Anchor misses are not necessarily answer misses.** Newer/alternative evaluation
   summaries ranked above a selected old source. One selected lifecycle source was
   background, not the requested final result. Review evidence sufficiency rather
   than scoring every exact source-ID miss as failure.

Limits: small purposive sample, predominantly Pallium, shared sessions, one
target-assisted query, current moving corpus rather than historical replay, and
checkout MCP formatting rather than a complete installed-agent journey. No overall
accuracy or downstream benefit claim follows from it.

## Completed investigation: fixed-candidate density window

The 2026-09-09 [Session History search-quality study](../../docs/reports/session-history-search-quality-study.md)
completed one bounded hypothesis test without changing production behavior. It held candidate
membership and order fixed, compared the existing excerpt with one deterministic query-density
window, and stopped before opening the reserved holdout.

The density window is rejected. Across 23 judgeable development lookups it produced 11 wins,
9 ties, and 3 losses, but the wins remained partial and it lost required facts in 16 results
and qualifiers in 3. Its adversarial 50,021-character candidate case also missed the frozen
5 ms p95 latency gate. The strict rubric measured whether one excerpt contained every fact and
qualifier needed to answer the request; zero fully sufficient excerpts is not a relevance or
expandability score. Baseline-helper latency was not measured, so no incremental-overhead claim
is available.

A follow-through traced the 20 empty excerpts in the reconstructed payloads to the existing
2,000-character MCP compactor: four 10-result responses kept every source ID but emptied five
excerpts each after optional work references and session cues were removed. The reconstruction
omitted `recorded_at` and `recorded_at_source`, although the production formatter conditionally
retains both before excerpt trimming, so these counts do not establish the complete current
production response shape or empty-preview rate. The associated blind grades likewise compare
incomplete reconstructed inputs, not complete current-production caller payloads. These were
empty-text hits, not omitted results.
Separately, 12 replay inputs had no result: the 10 sampled no-answer lookups and two linked
lookups whose single exposed source was absent from the snapshot source join. Responses with two to
six results had no empty excerpt. The broader feature remains queued because ranking, query repair,
expansion/navigation, telemetry coverage, multilingual prevalence, and independent-task evidence
remain unresolved.

The next evidence-backed question was narrow and is evaluated in the following completed investigation: for high-count responses under the fixed MCP budget,
can per-stage instrumentation identify a bounded allocation or explicit expansion/navigation flow
that keeps every retained hit recognizable while preserving source/lookup IDs, essential
provenance, exact-work scope, result count, and the historical-state warning? Start with the generic
10-results-by-160-characters reproduction; do not repeat or tune the rejected density window.

## Completed investigation: high-count response packaging

The 2026-09-10 development-only follow-up rejected one rank-prioritized minimum-preview
allocation. On the four incomplete reconstructed 10-result replies it converted all 20 empty
excerpts to
nonempty text within the existing 2,000-character budget and preserved source/lookup
identity, order, count, warnings, and expansion handles. Blind source-choice review
found only 13 of those 20 new fragments useful, however, while the candidate caused
17 useful-preview losses and at least 8 material context or qualifier losses. Row
wins/ties/losses were 13/10/17 (net -4), below the required +8 with zero qualifier
loss.

The candidate also failed declared boundary cases. A 24-character floor fit with
36-character IDs, but not with 64- or 128-character IDs or with a Unicode/escaped-text
current-replacement fixture. The 128-character baseline could retain only seven hits,
making the fixed-budget identity-versus-preview tradeoff explicit. Generic latency
passed, but the broader predeclared latency matrix was not run after the decisive
quality and boundary failures.

A later live caller-flow check reran three existing development queries in one current
session. Each returned ten source IDs with nine empty excerpts. Expanding rank 1 with
the same search's lookup ID returned a nonempty anchor and matching parent lineage in
all three cases for one additional MCP call capped at 2,400 characters. This proves
only that rank-1 expansion worked for those examples. It does not establish that rank
1 was the best source, that agents can choose among empty previews, that other ranks
work, or that guidance/product behavior needs no improvement. The live calls were not
a paired same-input replay, so the omitted timestamp fields are not claimed to fully
explain the five-to-nine difference.

A development-only follow-up then compared the complete caller-parity forms of 10
results / 2,000 characters, 5 / 2,000, and 10 / 4,000 on exactly the same four cases.
Before grading, the architect clarified that one case with no useful source should be
kept as a negative control rather than treated as a feasibility failure. Three
isolated low-cost graders each saw one opaque variant per query. On the three positive
cases, first-choice usefulness / best-source-first was 2/3 / 0/3 for 10 / 2,000,
3/3 / 3/3 for 5 / 2,000, and 3/3 / 2/3 for 10 / 4,000. No selected first choice was
wrong; under the current variant, the grader abstained in one case. The five-result
variant removed all
three uniquely useful below-rank-five sources across two cases. Both ten-result
variants retained them, but graders selected one under 2,000 characters and none
under 4,000. The negative control produced abstention under the current response and
tentative inspection—not a support claim—under both alternatives.

Actual response sizes were 1,999 characters for 10 / 2,000, 1,950–1,979 for
5 / 2,000, and 3,947–3,992 for 10 / 4,000. Every variant still raised qualifier
concerns on all three positive cases, and one case's required deadline, timeout,
usage-audit, and full acceptance details were absent from all sources. This tiny,
dependent development comparison therefore supports no rollout: this sample showed
poorer source selection under 2,000 characters, five results discard unique evidence
by truncation, and 4,000
characters roughly doubles response size without resolving qualifier adequacy.
Latency, holdout behavior, adaptive-agent behavior, injection precision, and
downstream task effect were not measured.

Do not tune this allocation on the same development split or open its reserved
holdout. The unresolved question is how agents choose a useful source when multiple
retained hits have empty or insufficient previews; the three rank-1 expansions do not
settle it. Any next representation work should use full caller-payload field parity
or explicitly verify parity before comparing on-demand navigation, rather than
redistribute the same fixed reply budget. Ranking, exact-work scope, visibility, and
historical cautions remain unchanged.

### Closed incomplete investigation: downstream 4,000-character response-budget validation

A 2026-09-10 bounded follow-up did not validate increasing the agent-facing search response budget from 2,000 to 4,000 characters. It froze 15 broad fixed-candidate cases without replacement. Prior development, holdout, comparison-query, and retrievable-neighbor protection made six ungradable before variants; those cases were redacted and excluded to prevent evidence leakage, not because of quality. The remaining nine comprised six answerable, one partial, and two negative cases. Frozen anchors were source-disjoint, but work/thread dependence remained.

Among eight pressure cases, three were protected/ungradable and two were negative, leaving exactly three answerable or partial cases that could improve: the ship threshold had no margin. Ten of 18 journeys produced outputs, but tool-output transport failures invalidated the only case with both variants dispatched and a separate pressure baseline. The first was a Windows stdout Unicode encoding failure on a persisted second expansion; the second, after the UTF-8 fix, persisted its expansion but delivered no readable output to the model for an unknown transport reason. The phase had only 924 input tokens left, below either affected journey reservation, and the fixed protocol prohibited reruns. No valid completed pair remained, so downstream effect, baseline losses, safety, negative regression, and the 125% retrieval-text gate were not estimated.

Operational decision: **DO NOT SHIP / NOT VALIDATED**. Production stays at 2,000 characters, but the incomplete run is not evidence that 4,000 regressed or failed a quality or cost gate. This closes only this fixed trial; the response-budget hypothesis remains unresolved. PR #160 preserves and supersedes PR #159. Continue with independently justified navigation, instrumentation, ranking/query-repair, and diverse-task evidence; revisit the budget only with a new design, new evidence, and explicit execution budget.

## Completed infrastructure qualification: reliable paired runner

Before any new model-backed search experiment, a deterministic 2026-09-10 pilot
qualified a reusable paired runner. It creates an isolated persistent SQLite fixture
from frozen raw sources, exercises the production History search and expansion routes
plus exact MCP formatters, lets a subprocess chooser select expansions from actual
search text, and persists every tool/driver attempt with lookup lineage. It completes
baseline and candidate for one case before advancing, reserves input and output budget
for the full pair plus bounded retries, rejects incompatible resumes, and distinguishes
valid abstention/product outcomes from transport-invalid, indeterminate, permanent,
and cannot-start-pair states.

Focused acceptance covered real process termination and restart, conservative charging
of the crash-after-execution-before-persist window, completed-step reuse, transient and
permanent transport failure, malformed and invalid UTF-8 output, Unicode content crossing
the subprocess boundary, input/output and pair budget boundaries, strict pack validation,
all-invalid reporting, ordering, and report reconciliation. The corrected suite passed 45 tests, including production-format truncation, finalized audit-set parity and retryable resume, malformed manifests, bounded inherited pipes, artifact-kind bounds, and finite timeout/cost validation.
The independently runnable no-model pilot produced one usable scripted pair, zero invalid
pairs, two completed attempts, 40 charged input tokens, 10 charged output tokens, and
USD 0.00.

This is infrastructure qualification only: it measures no agent quality, search quality,
candidate effect, or downstream task effect. Production remains unchanged. The feature
stays queued, and no real model evaluation may begin until the architect separately
verifies the pilot artifacts and authorizes the adapter/run.

## Exact-work scope contract

Exact-work search must remain exact. Never silently broaden, mix outside-work hits,
infer missing membership, or treat a session as one work item. Missing old work
references are a coverage limitation; separately investigate failures recording new
references where they should exist.

Potential skill guidance is conditional, not a default fallback: when the task needs
related background and exact evidence is insufficient, the agent may explicitly
choose a separate broad search. Broad hits are related evidence, not confirmed
members of the requested work scope. For “what happened in this work item?”, retain
scope and acknowledge insufficient evidence. For “help resume this work”, related
background may be appropriate. Respect explicit user scope in both cases.
Cross-container Relay does not widen Session History visibility.

## In Scope

### Wider research before implementation

1. Inventory existing lookup/expansion events, requests, sources, work metadata,
   index health, and reports using read-only access. Establish which checkout and
   configuration actually serve requests. Call out code/docs/skill/roadmap drift.
   Reuse public search/debug/expansion surfaces and existing eval seams rather than
   creating a parallel retrieval stack.
2. Reuse the completed bounded inventory and density-window study rather than repeating
   it. Freeze a modest budget, sampling method, and stopping conditions for each remaining
   question. Default to zero paid model calls and reduce samples when independent tasks are
   scarce; report exclusions. Any paid step needs an explicit call/token ceiling and a reason
   local checks cannot resolve it. Reuse reliable prior evidence.
3. Include successes, failures, no-answer cases, misleading near-matches, and several
   tasks/sessions/projects/runtimes and languages where available. Separate actual
   agent queries from user prompts used as queries; exact from broad; same-session
   recovery from cross-session recall; old untagged from newly tagged history;
   target-assisted/oracle rewrites from queries based only on task context.
4. For each reviewed case, identify the information needed, eligible relevant sources
   (possibly several or none), original parameters, candidate/ranking traces, visible
   excerpt, and expansion opportunity. Inspect preceding context before judging the
   agent's query. Prefer authoritative conversation positions/event time to ingestion
   time. Full stored sources are not exact historical exposure. Label current-corpus
   diagnostics and later evidence explicitly.
5. Investigate additional failure classes rather than merely confirming the examples:
   - capture/index coverage versus relevance failures;
   - identity/filter/request-link errors versus valid scope-empty results;
   - lexical/vector contributions, fusion, overfetch, deduplication, and limit effects;
   - paraphrases, identifiers, multilingual queries, and lost qualifiers;
   - repeated/same-session/current-request echoes, progress-only sources, stale
     decisions, and newer alternative answers;
   - excerpt budgets, query-focused windows, answer visibility, and result diversity;
   - expansion anchor/context bounds, evidence sufficiency, and token/latency cost;
   - tool descriptions/skills: when to search, exact versus broad, context-aware
     queries, recognition of insufficient results, bounded retries, and uncertainty.
   Missing expansion telemetry alone does not prove agent misuse.
6. Produce a traceable failure taxonomy with sample prevalence, confidence, competing
   explanations, successful counterexamples, and ranked small improvements. Look for
   evidence against the preliminary hypotheses. Do not turn selected-source misses
   or expected metadata boundaries into false relevance-failure rates.

### Implement the smallest supported improvements

Choose backend retrieval, presentation, and/or skill/tool guidance changes from the
research. Evaluate their effects separately. The initial findings are not a mandate
to implement every suggestion. Do not preselect a new embedding model, LLM reranker,
automatic query rewriter, semantic index, summary layer, or dependency.
Guidance-only or presentation-only changes are valid if that is what evidence supports.

Freeze development and held-out cases by independent task/session where feasible.
Compare before/after at equal or explicitly reported result/token budgets. Preserve
successes and no-answer behavior. If independence is unavailable, report the
limitation rather than manufacturing confidence.

Promote minimal anonymized reproductions into regression tests. Private corpus
text, local IDs, transcripts, credentials, and raw reports remain uncommitted.
If local evidence is unavailable elsewhere, reproduce generalized failure classes
with generic fixtures and state what those fixtures do not validate.

## Out of Scope

- Re-proving general productivity or rerunning the small history-benefit pilot.
- Automatic scope relaxation, guessed work-reference backfills, or weaker governance.
- Reopening the old proactive derived-memory injection optimization program.
- Dashboard work or new navigation/compression architecture without its separate
  comparison. No parallel roadmap tracker.

## Done When

1. A wider bounded report records data, sampling/exclusions, query provenance,
   serving code/configuration, findings, uncertainty, and costs. It investigates
   additional failure classes rather than only confirming the ten examples.
2. The smallest justified improvements ship with reproducible before/after and
   held-out checks, or an explicit independent-evidence limitation. Unresolved
   findings remain labeled. Research chooses the implementation, not the reverse.
3. Report candidate recovery, agent-visible evidence precision/sufficiency, scope
   correctness, returned/expanded tokens, and latency separately. Downstream task
   effect is reported only if measured. Retrieval alone never changes accessibility,
   use counters, ranking priors, or source relevance.
4. Preserve redaction, forgetting, retention, actor/container isolation, exact-work
   boundaries, derived-packages-disabled operation, and historical/current-state
   distinctions. Do not weaken the existing caution guidance.
5. Caller-surface E2E covers changed behavior: empty/no-answer, invalid filters or
   request links, missing/mismatched work references, scope isolation, duplicates,
   Unicode, result/character boundaries, and search → expansion → forgotten-source
   exclusion. Include actual MCP formatting for presentation changes. Follow
   AGENTS.md and docs/testing-conventions.md for the full required coverage.
6. Any skill/tool guidance changes remain consistent across supported integrations
   and explicitly preserve user scope. Document rollout/recheck instructions and
   align related roadmap work without silently expanding this feature.

## Notes and starting points

Read README.md, docs/context/strategy-vnext.md, docs/context/lessons.md, current history
tool contracts, and retrieval/expansion tests. Inspect app/mcp/server.py,
app/mcp/client.py, api/routes.py, core/query.py, configured retrieval providers, and
integration pallium-memory skills.

Optional local evidence on the originating machine, NOT required checkout files:
.local/history-search-diagnostic/REPORT.md, cases.json, summary.json, and saved
query traces/expansions in that directory. The baseline is summarized above so this
feature is self-contained. Its cases.json includes reviewed corrections beyond the
initial selection helper. .local/history-benefit-pilot/REPORT.md and
.local/corpus-retrieval-study/REPORT.md are earlier context, not current benchmarks.
Do not assume those files exist or copy private contents into Git. The exact-work
scope contract above supersedes any unconditional broad-fallback wording in the
initial local diagnostic report.

Related: [navigation and on-demand compression](investigate-history-navigation-and-on-demand-compression.md)
compares access/representation alternatives; share cases and baselines without
duplicating research. [Dashboard redesign](add-dashboard-operations-and-relay-workspace.md)
may display diagnostics but is not a dependency.
