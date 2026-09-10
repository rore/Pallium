# Session History search-quality study

**Measures:** fixed-candidate agent-visible evidence sufficiency. Candidate recovery is unchanged by construction; injection precision and downstream-task effect are unmeasured.

## Outcome

Do not ship the tested query-density excerpt window. It found more partial evidence in some results, but under the frozen answer-completeness rubric neither variant produced a single excerpt containing every fact and qualifier needed to answer its request. The candidate also lost required facts or qualifiers in other results and missed the frozen worst-case latency gate. The holdout stayed unopened because the candidate had already failed the development gates. This does not imply that search is useless: a short excerpt can still identify a relevant source worth expanding.

A follow-up also rejected one high-count response-allocation candidate: it recovered visible fragments but lost useful source-choice context and failed declared identifier and qualifier boundaries. This remains a report-only result. No retrieval, ranking, API, MCP, skill, integration, storage, or injection behavior changed.

## Serving baseline and cost

The study used a validated SQLite-backup snapshot of the healthy installed service. The service ran from the clean dedicated installed checkout at `94934667`; the study branch started at `0dbb0691`, and the relevant history-search files were identical. Vector search was ready, the embedding provider and queue were healthy, and derived-memory packages were disabled.

The snapshot contained 336 delivered history lookups from 94 requesting sessions, 13 containers, and 296 distinct recorded query texts, plus 230 linked or unlinked expansions. Fourteen lookups were exact-work searches and 61 returned no answer. There were 749 distinct exposed sources; 707 exceeded 240 characters. That last number is truncation exposure, not an excerpt-failure rate.

No external evaluator/provider calls were purchased. The study did not restart or write to the live service. Private queries, transcripts, source IDs, snapshots, and grading packets remain ignored under `.local/history-search-quality-study/`.

## Method

The experiment was a fixed-candidate presentation replay, not a retrieval replay. Recorded post-gate source IDs fixed result membership and order. A validated snapshot supplied the corresponding source text. Baseline and candidate variants then passed through the production 160-character excerpt helper and MCP compactor, but with the incomplete reconstructed row fields described below. Candidate recovery was therefore unchanged by construction; vector ranking and embedding behavior were not replayed.

Before text review, lookup events were joined into components when they shared a requesting session, normalized query, work reference, linked request lineage, exposed source ID, or normalized source-content fingerprint. Previously inspected diagnostic cases were barred from holdout. The selected development partition contained 36 lookups from 10 components: all 14 exact-work lookups, 10 no-answer lookups, and 24 initially judgeable candidates. Blind requirements review retained 23 judgeable lookups and excluded 13: 10 lacked request context and three lacked an evidence-bearing returned source.

Twelve linked, result-bearing events were reserved without text inspection in a component disjoint from development. They belong to one connected component, however, so they are not 12 independent tasks. The candidate failed development gates before freeze; the study therefore preserved this holdout unopened instead of using it to rescue a failed hypothesis.

For each judgeable development lookup, a clean-context reviewer recorded required facts and material qualifiers before seeing either excerpt variant. Variants were then graded blind as:

- `sufficient`: all required evidence and qualifiers, without contradiction;
- `partial`: some required evidence, but a necessary fact or qualifier is missing;
- `insufficient`: none of the required evidence is present;
- `misleading`: omission or framing supports a wrong or falsely current inference.

The frozen rubric measured answer completeness within one excerpt. It did not grade source relevance, recognizability, or whether the excerpt provided a useful lead for expansion. The original grades remain unchanged; zero fully sufficient excerpts means only that neither 160-character variant could complete the frozen requests by itself.

Only after blind grades were sealed was the candidate key opened. An initial grading pass was discarded when review found that anonymized 64-character identifiers had been compacted in place of real identifiers. The corrected replay compacted with real private identifiers first, checked the reconstructed response budget, then anonymized the already-compacted payload.

That reconstruction was still incomplete relative to the production caller payload. Its rows included source identity, role, `occurred_at`, thread and match metadata, work references, historical updates, and excerpts, but omitted `recorded_at` and `recorded_at_source`; production `_history_fields` conditionally retains both before excerpt trimming. The counts and blind grades below therefore describe the reconstructed inputs, not the complete current production response shape or empty-preview rate.

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

The candidate met the net-win threshold but failed the sufficient-rate and zero-regression gates. Its wins were partial under the answer-completeness rubric: clustered query terms sometimes moved a useful fragment into view, but no tested 160-character excerpt contained all frozen evidence requirements. Distributed facts and qualifiers were the counterexample: concentrating terms in one window removed other necessary evidence. These grades do not measure whether an excerpt was relevant or sufficient to choose a source for expansion.

Ten no-answer development lookups remained descriptive preservation cases. Result IDs, order, and count were identical in every baseline/candidate pair.

### Size and latency

| Measure | Baseline | Candidate |
|---|---:|---:|
| Returned excerpts | 115 | 115 |
| Excerpt characters | 14,873 | 14,866 |
| Excerpt UTF-8 bytes | 15,046 | 14,970 |
| Excerpt whitespace-token proxy | 2,168 | 2,054 |
| Mean excerpt characters | 129.33 | 129.27 |
| Empty excerpts after reconstructed MCP compaction | 20 | 20 |
| Compact MCP JSON characters, total | 49,650 | 49,620 |
| Compact MCP JSON whitespace-token proxy | 2,975 | 2,858 |
| Maximum compact MCP JSON characters | 3,158 | 3,158 |

The MCP JSON size rows measure the anonymized research packets after compaction; replacing private UUIDs with longer hashes inflated those stored packets beyond the live 2,000-character limit. The replay separately asserted that its pre-anonymization reconstructed payloads fit the budget, but did not include every field retained by the current production formatter.

The bounded follow-through measured those pre-anonymization compactor outputs by input result count:

| Input results | Responses | Baseline output characters | Candidate output characters | Empty excerpts per response |
|---:|---:|---:|---:|---:|
| 0 | 12 | 110–255 | 110–255 | 0 |
| 2 | 2 | 916–970 | 915–970 | 0 |
| 3 | 10 | 1,116–1,505 | 1,118–1,504 | 0 |
| 5 | 7 | 1,766–2,000 | 1,767–1,995 | 0 |
| 6 | 1 | 1,814 | 1,811 | 0 |
| 10 | 4 | 1,998–1,999 | 1,999 | 5 |

The 12 zero-result replay inputs are a different population from the 10 preselected no-answer lookups. Those 10 had no exposed row and no linked request; two additional linked lookups each referenced one exposed source that was absent from the snapshot source join, so reconstruction had no result or expansion handle. By contrast, the 20 empty excerpts were empty text fields inside retained hits: no hit was removed, and every source ID remained available for expansion.

Whitespace splitting is only a token proxy; no tokenizer-specific token count was claimed. Expansion content was not replayed because the candidate did not alter expansion. The existing expansion contract remained capped at 4,000 characters.

Latency timing covered only the candidate density helper; the baseline helper was not timed, so incremental overhead was not measured. No new benchmark run was made for this correction. Observed source/query p50, p90, and max candidate cases stayed under the 5 ms p95 limit. The 50,021-character adversarial candidate case reached 6.244 ms p95 and 9.568 ms maximum over 2,000 calls, failing the p95 gate despite passing the 20 ms maximum. The aggregate candidate p95 was 4.155 ms.

### Additional failure taxonomy

The wider inventory and earlier diagnostic support several distinct classes; they should not be collapsed into one accuracy number:

1. **Unjudgeable telemetry.** Fifteen recorded lookups lacked query text, and many lacked a directly linked request. Missing context cannot establish evidence sufficiency.
2. **Valid no-answer and exact-scope boundaries.** Sixty-one lookups returned no answer. Older untagged sources can be broad-search candidates while correctly absent from exact-work results. Exact search must not silently broaden.
3. **Truncation exposure.** Most exposed sources were longer than the excerpt budget, but length alone does not prove that answer evidence was hidden.
4. **Response-budget compaction.** Within the incomplete reconstructed payloads, a bounded follow-up traced all 20 empty excerpts to the unchanged 2,000-character MCP response compactor, not either excerpt helper: pre-compaction empties were 0 in both variants, while each of four 10-result responses retained all 10 hits but trimmed five excerpts to empty in both variants. The shared compactor therefore explains those reconstructed baseline and candidate empties; neither helper produced them. The 20 reconstructed responses with two to six results had no empty excerpt. On the empty rows, all 20 source IDs and roles survived, as did each parent lookup-event ID, so expansion handles remained usable; 15 rows that originally carried work references and all 20 original session cues lost those optional fields in earlier compaction passes. A generic 10-by-160-character synthetic response reproduced the same five empty excerpts at 1,999 serialized characters. These counts are not a current-production prevalence claim because `recorded_at` and `recorded_at_source` were omitted from the replay.
5. **Selective query-repair effects.** Earlier cases showed that focused query repair or expansion can recover evidence, while other rewrites lose qualification anchors. There is no supported universal rewrite.
6. **Candidate/ranking failures.** Earlier traces included an eligible lexical candidate outside the displayed top results. The fixed-candidate experiment did not test fusion, overfetch, or ranking changes.
7. **Coverage gaps.** Current recorded queries contained no non-ASCII text; linked Claude evidence was sparse and OpenCode was absent. Unicode behavior remains covered by generic tests and adversarial checks, not real-query prevalence.
8. **Chronology limits.** Source timestamps were unavailable in the graded packet. Review preserved explicit proposal/completion/correction wording but did not infer cross-source currentness.

## Follow-up: high-count response packaging

A 2026-09-10 development-only follow-up tested one allocation candidate against the
same frozen 36-lookup replay. This measures fixed-candidate agent-visible
presentation/navigation. Candidate recovery was unchanged; injection precision and
downstream-task effect remain unmeasured. No external evaluator calls, production
changes, service changes, or holdout evaluation occurred.

The baseline reproduced the prior incomplete reconstruction exactly: 115 input and
output hits, no empty input excerpts, and 20 empty output excerpts across the same
four 10-result replies. Their serialized responses were 1,998–1,999 characters.
Responses with 0, 2, 3, 5, or 6 results remained separate preservation cases. These
are reconstructed-payload counts and sizes, not measurements of the complete current
production formatter.

The single candidate activated only when a 10-hit reply remained over the unchanged
2,000-character budget after existing optional-field removal. It first reserved a
24-character prefix for each nonempty excerpt, then spent the remaining serialized
budget in rank order using bounded binary search. Lower-count and already-fitting
responses delegated to the current compactor byte-for-byte. On the four reconstructed
10-result development replies, the candidate preserved the checked identity, lineage,
warning, and expansion-handle fields present in the reconstruction; each reply
serialized to exactly
2,000 characters and all 20 formerly empty excerpts became nonempty.

Blind source-choice review rejected the candidate:

| Measure | Result |
|---|---:|
| Formerly empty rows that became useful expansion previews | 13 / 20 |
| Row wins / ties / losses | 13 / 10 / 17 |
| Net row wins required / observed | at least 8 / -4 |
| Lookup wins / ties / losses | 3 / 1 / 0 |
| Useful source-choice preview losses | 17 |
| Material qualifier or context-loss rows | at least 8 |

The short floors often preserved a recognizable noun phrase but removed why it
mattered. Lost context included pending approval, coordinate-before-edit
restrictions, stale-receipt conditions, restart safety conditional on measurements
not having started, failed or observability-only work, and benchmarks still running.
Source IDs still allowed expansion, but the presentation made some expansion choices
less informed. This fails the zero-qualifier-loss and positive-net-row gates even
though 13 formerly empty rows became useful.

Declared boundary fixtures also rejected promotion. With otherwise ordinary
10-result fields, the serialized 24-character-floor payload was 1,794 characters for
36-character IDs, 2,102 for 64-character IDs, and 2,806 for 128-character IDs. The
36-character case fit. The 64-character case fell back to the baseline with nine
empty previews. The 128-character case fell back to the baseline, which could retain
only seven hits under the current budget. A Unicode, JSON-escaping, and current-
replacement qualifier fixture required 2,148 characters and also fell back with nine
empty previews. These are normal boundary inputs, not the separately classified
mathematically impossible 300-character identity diagnostic. They show that identity
and qualification fields alone can leave too little room for the proposed preview
floor without increasing the budget or dropping results.

Generic per-call timing passed the declared incremental and absolute limits. The
10-by-160 case measured 1.2866 ms candidate p95 and 2.3202 ms maximum versus
1.0717/1.8171 ms for baseline. The harness did not run the predeclared latency suite
over frozen observed sizes, Unicode/escaping, long IDs, or the impossible diagnostic;
because quality and boundary gates had already failed, those missing timings were not
used to rescue or promote the candidate.

The holdout selection and holdout packet were not opened or graded. The harness did
load each complete frozen snapshot through the old inventory loader before filtering
to the 36 published development hashes, so it did not prove access-level holdout
sealing. Both snapshots regenerated the published development packets exactly. This
limitation does not weaken the no-change decision, but it prevents a stronger claim
that non-development snapshot content was never loaded.

No caller-surface search-to-expansion E2E was added because production behavior did
not change. The offline navigation check established source-anchor and lookup-ID
field preservation only; it did not exercise a real source retrieval with
parent_lookup_id.

A later diagnosis exercised the unchanged live caller flow without opening the
holdout or changing the candidate. Three existing development queries were rerun in
one current session with `limit=10`. Each current response retained ten source IDs
but exposed nine empty excerpts. Expanding rank 1 with the lookup ID returned by that
same search, `before=1`, `after=1`, and `max_chars=2400` returned one nonempty
anchor and the matching parent lookup ID in all three cases. This costs one additional
MCP call and at most 2,400 response characters for the selected source. The check
proves only that the rank-1 expansion path worked for these three queries. It did not
test other ranks, whether rank 1 was the best source, whether an agent can choose
among empty previews, population-level call cost, or downstream task effect. Because
the live calls were not a paired replay of the same complete inputs, the omitted
`recorded_at` fields are a fidelity defect but are not claimed to fully explain the
change from five to nine empty previews.

## Exploratory result-count and response-budget comparison

An architect clarification made before grading accepted “none of these sources is
useful” as valid gold for a separately scored negative control. This changed the
earlier feasibility interpretation, which had stopped on that case; it did not change
the four cases, variants, or frozen source evidence. Gold was fixed from complete
expanded content before three isolated low-cost graders each saw one opaque variant
per query. The replay queried only the 36 frozen development event IDs and used
production historical-metadata assembly plus the current MCP compactor. All 40 input
rows included `recorded_at` and `recorded_at_source`; none had a historical update.

| Variant | Actual response chars (rough chars/4 tokens) | First useful / best first, 3 positive cases | Unique useful ranks >5 visible | Negative control |
|---|---:|---:|---:|---|
| 10 results / 2,000 chars | 1,999 (500) | 2/3 / 0/3 | 3/3; one selected | abstained |
| 5 results / 2,000 chars | 1,950–1,979 (488–495) | 3/3 / 3/3 | 0/3 | tentative inspection |
| 10 results / 4,000 chars | 3,947–3,992 (987–998) | 3/3 / 2/3 | 3/3; none selected | tentative inspection |

No positive first choice was wrong. Under 10 results / 2,000 characters, the
grader abstained in one case and never put the best source first. Under five
results, the grader put the best source first in all three positive cases, while
truncation removed three uniquely useful lower-ranked sources across two cases. Four thousand characters retained those
sources and improved first-choice success, but approximately doubled response size
without causing the grader to select them.

Every variant drew qualifier concerns on all three positive cases. One case was only
partially answerable even from full sources: its deadline, timeout policy, usage-audit
details, and complete acceptance thresholds were absent. Fixed, non-adaptive expansion
choices totaled 4 calls / 8,696 characters for the current variant, 6 / 14,400 for
each alternative across the positive cases. On the negative control, the current
variant made no call; each alternative proposed two tentative inspections totaling
4,800 characters. Tentative inspection is not a false relevance claim, and no grader
asserted that the negative sources supported the request.

This four-case development comparison does not show that 2,000 characters is clearly
sensible or that either alternative should ship. It exposes a direct tradeoff:
this sample showed poorer selection under current packaging; five results lose
uniquely useful evidence; and 4,000 characters costs roughly twice as much while
leaving qualifier adequacy
unresolved. The cards are dependent development cases with one judgment per
case/variant; latency, holdout generalization, adaptive agent behavior, injection
precision, and downstream task effect remain unmeasured.

## Recommendation

Keep the existing excerpt and response-packaging behavior. Do not change the shared `build_excerpt` helper: normal retrieval also feeds derived-memory routing, work-signal classification, and disclaimer suppression, so a global window change is not presentation-only. Do not add the tested history-specific density window or the tested 24-character-floor/rank-allocation policy based on this evidence.

The remaining questions are separate investigations, not bundled implementation:

1. determine how an agent should choose which source to expand when several retained hits have empty or insufficient previews, preserving the current response budget, result identity, exact-work scope, and stale-history cautions; the three rank-1 checks do not establish that current guidance or presentation is adequate, and the rejected allocation must not be retuned on this development split;
2. study candidate-pool, fusion, and query-repair failures on a genuinely task-independent set, reporting candidate recovery separately from excerpt sufficiency.

The roadmap item remains queued. This study and its packaging follow-up resolve two presentation hypotheses; they do not establish the broader feature as done.

## Reproducibility and limits

The ignored harness used only repository code and the Python standard library around existing snapshot/MCP helpers. Public-safe artifact hashes were:

- development evidence: `2A7D0AFB786483171511AE07FB37229324E681F6B6B6A4063F22E466E3BAB41B`;
- corrected blind variants: `3C1659887D3908F6292952982F0524A033A11B6662A6191B96D17B981ACE67D2`;
- pre-variant requirements: `D98C57B4126218C5444F6B5ECFFC109BCCE7DB2386935C84FB8DD899FD98DE41`;
- final aggregate grade summary: 2D3B0EBA231E1481DD6D0276258C5F10B95089B4441627A3CC3874148B510815;
- aggregate-only public-claim verification: 59008D205FAAF6CDC5DA9DD56A04EC02BE4356CB14DD5ED9B113019DFA390C76;
- compaction follow-through aggregate: 07846FF802969BDAA2F7FEBBA6827471EF990641FE46BCC6C8AE3238E7564202.
- exploratory result-count/budget aggregate: CE43A610E61490193E686AE76D3F5C4A9E8C33397A333A2D3DF6C1DA0948BBA2.

The replay used current snapshotted source rows with historical exposed IDs, not an atomic historical vector-index snapshot, and omitted `recorded_at` plus `recorded_at_source` from the reconstructed caller payload. It cannot estimate ranking changes, past source contents, the complete current response shape, downstream task effect, or population-level accuracy. Development lookups are dependent within components, and the reserved holdout is one independent component rather than 12 independent tasks. These limits preserve the conservative rejection of the tested candidates but prevent a broader product or current-production claim.
