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

A follow-through traced the 20 empty replay excerpts to the existing 2,000-character MCP
compactor: four 10-result responses kept every source ID but emptied five excerpts each after
optional work references and session cues were removed. These were empty-text hits, not omitted
results. Separately, 12 replay inputs had no result: the 10 sampled no-answer lookups and two linked
lookups whose single exposed source was absent from the snapshot source join. Responses with two to
six results had no empty excerpt. The broader feature remains queued because ranking, query repair,
expansion/navigation, telemetry coverage, multilingual prevalence, and independent-task evidence
remain unresolved.

The next evidence-backed question is narrow: for high-count responses under the fixed MCP budget,
can per-stage instrumentation identify a bounded allocation or explicit expansion/navigation flow
that keeps every retained hit recognizable while preserving source/lookup IDs, essential
provenance, exact-work scope, result count, and the historical-state warning? Start with the generic
10-results-by-160-characters reproduction; do not repeat or tune the rejected density window.

### Completed investigation: 4,000-character response budget

A 2026-09-10 bounded follow-up rejected increasing the agent-facing search response budget from 2,000 to 4,000 characters. It froze 15 broad fixed-candidate cases without replacement. Prior development, holdout, comparison-query, and retrievable-neighbor protection made six ungradable, leaving nine eligible cases: six answerable, one partial, and two negative. Frozen anchors were source-disjoint, but work/thread dependence remained.

Exactly three pressure cases could possibly improve. During the separate-context paired run, an expansion transport failure invalidated one of those pairs; the maximum possible added resolutions fell to two, below the fixed requirement of three. The run stopped after 10 of 18 planned journeys, with no rerun, tuning, or replacement. Other safety, negative-regression, and 125% retrieval-text gates were not estimated after the decisive early failure. Production stays at 2,000 characters. Private evidence remains under `.local/history-budget-4000-trial/`; the public report records the method, exclusions, token cost, and limits.

This closes the response-budget hypothesis, not the broader roadmap item. Continue with independently justified navigation, instrumentation, ranking/query-repair, and diverse-task evidence; do not reopen the same budget trial without a new design and new evidence.
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
