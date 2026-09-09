# Session History search-quality study

**Measures:** fixed-candidate agent-visible evidence sufficiency. Candidate recovery is unchanged by construction; injection precision and downstream-task effect are unmeasured.

## Outcome

Do not ship the tested query-density excerpt window. It found more partial evidence in some results, but it produced no fully sufficient excerpts, lost required facts or qualifiers in other results, and missed the frozen worst-case latency gate. The holdout stayed unopened because the candidate had already failed the development gates.

This is a report-only result. No retrieval, ranking, API, MCP, skill, integration, storage, or injection behavior changed.

## Serving baseline and cost

The study used a validated SQLite-backup snapshot of the healthy installed service. The service ran from clean `C:\Dev\rore\Pallium-installed` at `94934667`; the study branch started at `0dbb0691`, and the relevant history-search files were identical. Vector search was ready, the embedding provider and queue were healthy, and derived-memory packages were disabled.

The snapshot contained 336 delivered history lookups from 94 requesting sessions, 13 containers, and 296 distinct recorded query texts, plus 230 linked or unlinked expansions. Fourteen lookups were exact-work searches and 61 returned no answer. There were 749 distinct exposed sources; 707 exceeded 240 characters. That last number is truncation exposure, not an excerpt-failure rate.

No external evaluator/provider calls were purchased. The study did not restart or write to the live service. Private queries, transcripts, source IDs, snapshots, and grading packets remain ignored under `.local/history-search-quality-study/`.

## Method

The experiment was a fixed-candidate presentation replay, not a retrieval replay. Recorded post-gate source IDs fixed result membership and order. A validated snapshot supplied the corresponding source text. Baseline and candidate variants then passed through the real 160-character provider excerpt budget and unchanged MCP compaction. Candidate recovery was therefore unchanged by construction; vector ranking and embedding behavior were not replayed.

Before text review, lookup events were joined into components when they shared a requesting session, normalized query, work reference, linked request lineage, exposed source ID, or normalized source-content fingerprint. Previously inspected diagnostic cases were barred from holdout. The selected development partition contained 36 lookups from 10 components: all 14 exact-work lookups, 10 no-answer lookups, and 24 initially judgeable candidates. Blind requirements review retained 23 judgeable lookups and excluded 13: 10 lacked request context and three lacked an evidence-bearing returned source.

Twelve linked, result-bearing events were reserved without text inspection in a component disjoint from development. They belong to one connected component, however, so they are not 12 independent tasks. The candidate failed development gates before freeze; the study therefore preserved this holdout unopened instead of using it to rescue a failed hypothesis.

For each judgeable development lookup, a clean-context reviewer recorded required facts and material qualifiers before seeing either excerpt variant. Variants were then graded blind as:

- `sufficient`: all required evidence and qualifiers, without contradiction;
- `partial`: some required evidence, but a necessary fact or qualifier is missing;
- `insufficient`: none of the required evidence is present;
- `misleading`: omission or framing supports a wrong or falsely current inference.

Only after blind grades were sealed was the candidate key opened. An initial grading pass was discarded when review found that anonymized 64-character identifiers had been compacted in place of real identifiers. The corrected replay compacted with real private identifiers first, checked the actual response budget, then anonymized the already-compacted payload.

The predeclared promotion gates required at least 10 judgeable holdout lookups, at least a 10 percentage-point sufficient-rate gain, at least two net lookup wins, no slice regression, no required-fact or qualifier loss, no misleading result, unchanged IDs/order/count and response budgets, and per-call p95/max latency no greater than 5/20 ms.

## Results

### Evidence sufficiency

| Measure | Baseline vs candidate |
|---|---:|
| Judgeable development lookups | 23 |
| Lookup wins / ties / losses | 11 / 9 / 3 |
| Result wins / ties / losses | 27 / 77 / 6 |
| Fully sufficient results | 0 / 0 |
| Fully sufficient lookups | 0 / 0 |
| Candidate required-fact losses | 16 results across 12 lookups |
| Candidate qualifier losses | 3 results across 3 lookups |
| Established affirmative truth regressions | 0 |
| Exact-work lookup wins / ties / losses | 3 / 6 / 0 |
| Broad lookup wins / ties / losses | 8 / 3 / 3 |

The result wins/ties/losses cover 110 graded pairs; five of the 115 emitted rows belonged to excluded lookups. A lookup is a loss when its worst changed result loses an ordinal rubric level, even if another result improves.

The candidate met the net-win threshold but failed the sufficient-rate and zero-regression gates. Its wins were partial: clustered query terms sometimes moved a useful fragment into view, but no tested 160-character excerpt contained all frozen evidence requirements. Distributed facts and qualifiers were the counterexample: concentrating terms in one window removed other necessary evidence.

Ten no-answer development lookups remained descriptive preservation cases. Result IDs, order, and count were identical in every baseline/candidate pair.

### Size and latency

| Measure | Baseline | Candidate |
|---|---:|---:|
| Returned excerpts | 115 | 115 |
| Excerpt characters | 14,873 | 14,866 |
| Excerpt UTF-8 bytes | 15,046 | 14,970 |
| Excerpt whitespace-token proxy | 2,168 | 2,054 |
| Mean excerpt characters | 129.33 | 129.27 |
| Empty excerpts after actual MCP compaction | 20 | 20 |
| Compact MCP JSON characters, total | 49,650 | 49,620 |
| Compact MCP JSON whitespace-token proxy | 2,975 | 2,858 |
| Maximum compact MCP JSON characters | 3,158 | 3,158 |

Whitespace splitting is only a token proxy; no tokenizer-specific token count was claimed. Expansion content was not replayed because the candidate did not alter expansion. The existing expansion contract remained capped at 4,000 characters.

Observed source/query p50, p90, and max cases stayed under the 5 ms p95 limit. The 50,021-character adversarial case reached 6.244 ms p95 and 9.568 ms maximum over 2,000 calls, failing the p95 gate despite passing the 20 ms maximum. The aggregate p95 was 4.155 ms.

### Additional failure taxonomy

The wider inventory and earlier diagnostic support several distinct classes; they should not be collapsed into one accuracy number:

1. **Unjudgeable telemetry.** Fifteen recorded lookups lacked query text, and many lacked a directly linked request. Missing context cannot establish evidence sufficiency.
2. **Valid no-answer and exact-scope boundaries.** Sixty-one lookups returned no answer. Older untagged sources can be broad-search candidates while correctly absent from exact-work results. Exact search must not silently broaden.
3. **Truncation exposure.** Most exposed sources were longer than the excerpt budget, but length alone does not prove that answer evidence was hidden.
4. **Response-budget starvation.** In this replay, 20 of 115 rows had empty excerpts after real MCP compaction in both variants. This is a presentation-limit issue separate from ranking and deserves a focused experiment before changing budgets or result count.
5. **Selective query-repair effects.** Earlier cases showed that focused query repair or expansion can recover evidence, while other rewrites lose qualification anchors. There is no supported universal rewrite.
6. **Candidate/ranking failures.** Earlier traces included an eligible lexical candidate outside the displayed top results. The fixed-candidate experiment did not test fusion, overfetch, or ranking changes.
7. **Coverage gaps.** Current recorded queries contained no non-ASCII text; linked Claude evidence was sparse and OpenCode was absent. Unicode behavior remains covered by generic tests and adversarial checks, not real-query prevalence.
8. **Chronology limits.** Source timestamps were unavailable in the graded packet. Review preserved explicit proposal/completion/correction wording but did not infer cross-source currentness.

## Recommendation

Keep the existing excerpt behavior. Do not change the shared `build_excerpt` helper: normal retrieval also feeds derived-memory routing, work-signal classification, and disclaimer suppression, so a global window change is not presentation-only. Do not add a history-specific density window based on this evidence either.

The smallest worthwhile follow-ups are separate investigations, not bundled implementation:

1. measure why real MCP compaction produced empty excerpts at high returned counts and compare bounded allocation strategies without increasing the response budget;
2. evaluate explicit source expansion or on-demand navigation when a short excerpt is incomplete, preserving the current scope and stale-history cautions;
3. study candidate-pool, fusion, and query-repair failures on a genuinely task-independent set, reporting candidate recovery separately from excerpt sufficiency.

The roadmap item remains queued. This study resolves one hypothesis; it does not establish the broader feature as done.

## Reproducibility and limits

The ignored harness used only repository code and the Python standard library around existing snapshot/MCP helpers. Public-safe artifact hashes were:

- development evidence: `2A7D0AFB786483171511AE07FB37229324E681F6B6B6A4063F22E466E3BAB41B`;
- corrected blind variants: `3C1659887D3908F6292952982F0524A033A11B6662A6191B96D17B981ACE67D2`;
- pre-variant requirements: `D98C57B4126218C5444F6B5ECFFC109BCCE7DB2386935C84FB8DD899FD98DE41`;
- final aggregate grade summary: 2D3B0EBA231E1481DD6D0276258C5F10B95089B4441627A3CC3874148B510815;
- aggregate-only public-claim verification: 59008D205FAAF6CDC5DA9DD56A04EC02BE4356CB14DD5ED9B113019DFA390C76.

The replay used current snapshotted source rows with historical exposed IDs, not an atomic historical vector-index snapshot. It cannot estimate ranking changes, past source contents, downstream task effect, or population-level accuracy. Development lookups are dependent within components, and the reserved holdout is one independent component rather than 12 independent tasks. These limits strengthen the no-change conclusion and prevent a broader product claim.
