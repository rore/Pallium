# Session History evaluation readiness: reconciliation and next slice

## Conclusion

The bounded investigation is complete. No general retrieval change earned a
deployment recommendation: lexical, current-CLS hybrid and model-conformant
mean-pooling hybrid each recovered5/8 predefined evidence groups at10 on the same
revalidated development corpus. All passed the original four controls and missed
the same three harder groups. This is candidate recovery, not graded answer
failure, broad non-regression or proof of downstream usefulness.

Reuse the small frozen comparison and existing evaluation seams. No new telemetry
store, derived memory, dependency or production search change was added. The
synthetic-qualified exporter preserves supported records, but the broader product
gate still lacks complete natural-task replay and downstream confirmation. The
original incident remains unresolved; these new controls do not replace it.

## Original commitments versus evidence

| Obligation | Evidence | Disposition |
|---|---|---|
| Record formatter-selected search/expansion sources, including anchor/neighbor roles | `core/service.py` delivery finalization, `app/mcp/server.py` receipt calls, existing caller E2E | Shipped IDs/roles contract. Finalization is not proof of transport receipt or model consumption. |
| Replay exact delivered search plus linked expansion context | Original feature Done-when 3 and Work Record outcome; ordinary event schema lacks returned text, page offsets and content revisions | Unresolved fidelity gap. Historical source rows cannot reconstruct every delivered page. |
| Preserve scope and time semantics | Existing `real_corpus_pull_eval.py` current/as-of modes and explicit request-link rejection | Reuse safeguards. A cutoff does not recover historical source/index revisions. |
| Reliable paired execution | `reliable_pair_runner.py`, PR166 qualification and `docs/benchmarks.md` | Infrastructure done. Do not rerun its qualification as new product evidence. |
| Full original caller context and independent answer sufficiency | Runner driver starts with query, tool text and budgets; pack gold uses required substrings | A verified adapter and independent rubric remain necessary for downstream-task claims. |
| Preserve test identities and untouched confirmation cases | October 1 evidence-recovery report: aggregate reports/hashes survived, some private exclusion manifests did not | Do not infer old exclusions or label familiar cases held-out. New prospective packs need durable identities and inspection history. |
| Demonstrate useful, safe real-world search | Product gate remains in-progress; authored tests and incident development experiments are not independent confirmation | Not complete; more event rows alone do not satisfy it. |

Important correction: the original approved implementation plan explicitly chose
IDs/roles-only delivery receipts without schema expansion. Its broader outcome
and roadmap used stronger exact-replay wording. This is a mismatch between the
declared outcome and the narrower implementation contract, not evidence that a
developer ignored an approved requirement to store full payload bytes. Preserve
the shipped component evidence while making the remaining obligation explicit.

Evidence references: `.agent-workflow/tasks/fix-real-corpus-memory-access-and-evaluation.md`,
`roadmap/features/fix-real-corpus-memory-access-and-evaluation.md`,
`docs/reports/session-history-evidence-recovery.md`,
`docs/reports/history-evidence-selection.md`, `docs/benchmarks.md`.

## Smallest next deliverable

1. Invoke Agent Workflow and classify the exact intended paths before code edits.
2. Add one `evals/history_episode_export.py` CLI and its focused
   `tests/test_history_episode_export.py`. Input is an explicitly named native
   transcript, explicit request/answer record identities and ordered call IDs,
   optional named frozen-pack artifacts, and an explicit destination. No directory
   discovery, inferred missing identity, live service access or automatic capture.
3. Preserve selected raw records and exact tool-return strings with hashes,
   original arguments, lookup/page/expansion lineage and observed failures. Reuse
   existing parsing/pairing where sound, but do not treat its normalized output as
   complete caller context: current Codex parsing drops `turn_context` and truncates
   metadata. Unsupported, missing, duplicate or ambiguous records fail closed or
   produce an explicitly incomplete evidence report, never invented fields.
   Claim context-complete only when required caller-context records and their
   order/identities are established. Unsupported or missing system/developer or
   compaction context is incomplete, even when all tool calls are paired. Preserve
   the exact raw tool-result string/record bytes, not normalized parser text.
4. Write an atomic, versioned local episode plus manifest/readiness report.
   No overwrite of incompatible existing output; identical repeat verifies and
   reuses it. Record selected IDs and content hashes, input hashes, parser version,
   explicit development/confirmation designation and prior-inspection declaration.
   A declaration is an audit record, not proof that a case was never inspected.
   Store raw content once; the manifest indexes and hashes it, not a second copy.
5. Independently verify one zero-model synthetic journey through the CLI: multiple
   search pages, query repair, linked expansion, Unicode, an error, and final answer.
   Reopen it in a new process and compare tool text and lineage exactly. Inject
   missing records, duplicate IDs, parent mismatch, modified inputs and output
   corruption; these must not become successful or historically faithful cases.

This is not a new evaluation engine. Leave `reliable_pair_runner.py` unchanged in
this slice. Preserve its existing pack alongside the episode if supplied; do not
silently convert incomplete episodes into supported runner input. No model calls,
rank tuning, embedding runs or new dependencies. Bound input/output sizes explicitly
and reject over-limit records rather than silently clipping evidence.

## Readiness is per question

| Intended claim | Additional evidence required |
|---|---|
| What did this recorded caller receive? | Complete selected call/result records with exact text, IDs and explicit transport gaps. Recorded output still does not prove model consumption. |
| Could another retriever find the necessary evidence? | Frozen eligible corpus, inclusion/exclusion membership, stable source mapping, versioned text/lifecycle, code/config and embedding/index identity. Delivered sources alone are insufficient. |
| Did it improve the answer? | Original task and available caller context, independently held expected evidence/answer or valid abstention, verified paired driver and honest budgets/usage. |
| Does it generalize without regressions? | Diverse task/session groups, negatives, disjoint development/confirmation cases and independent grading. One incident or repeated queries are not independent cases. |

Missing history/config must be marked unavailable. Today’s content/config cannot
repair a historical replay by relabeling it. Generated summaries are not needed.

## Privacy, preservation and implementation gate

Build and qualify the first slice using anonymized synthetic fixtures only. No
private session is exported as part of this approval request, and no runtime
retention/forgetting behavior changes. Real use requires explicitly authorized
episode files and a user-chosen private durable location outside disposable
worktrees, outside Git and not automatically synced or uploaded. Validate the
destination accordingly; do not silently fall back to the repository.

An exported raw record can contain more than Pallium's redacted view. Do not
describe exact raw preservation as automatically redacted. Private export needs
a reviewed authorization/redaction policy; transformed data is a distinct artifact,
not byte-identical evidence. Never copy unrelated transcript records by default.

Current standalone exports are not covered by service forgetting. No real private
capture is ready until deletion/revocation and retention are explicitly resolved.
Forgetting must not be bypassed by an untracked archive. A future private pilot
must define which copies/indexes/backups are deleted or invalidated, who owns them,
and how that is verified. A checksum is integrity evidence, not a backup: preserve
the actual authorized artifacts and case/exclusion identities before retirement.

The concrete code slice requires independent plan review and separate human plan
approval before implementation. Completing it qualifies evidence export only;
the product gate and broader readiness task remain open until the later evidence
requirements are met. No deployment or new always-on logging is proposed.

Independent review: /root/comparison_review approved the planning-only slice on
2026-10-06, requiring explicit incomplete-context classification and synthetic-only
execution until private destination/deletion/redaction policy is approved. Those
conditions are incorporated above. Human implementation approval was received on
2026-10-06 ("i approve,") for this synthetic-only slice. Private export and human
result review remain separate gates.

## Synthetic exporter usage

Run from the checkout with explicitly prepared synthetic files:

```powershell
python -m evals.history_episode_export --transcript C:/scratch/synthetic.jsonl --selection C:/scratch/selection.json --destination C:/scratch/episode --synthetic
```

Selection version 1 names `source_format` (`codex` or `claude`), `synthetic: true`,
`designation` (`development` or `confirmation`), `prior_inspection` (`declared` or
`not_declared`), `request`, `answer`, ordered `context`, and ordered `calls`.
Each record reference contains its zero-based `record_index` and SHA-256 of the
original JSONL line, including its newline. Each call names `call_id` and `kind`
(`search`, `expansion`, or `other`). The synthetic tests provide complete examples.

The output stores selected raw records once in `records.jsonl`; `manifest.json`
indexes their byte offsets and hashes, exact returned strings and readiness gaps.
Publication uses an exclusively created directory and writes the manifest last as
the commit marker. Directory visibility is not atomic; an interrupted directory
without a complete matching manifest is rejected, never reused as a valid episode.
Selection is at native-record granularity: a selected multi-block record retains
all its blocks. Repeating an identical export verifies every output before reuse.
Optional `--frozen-artifact FILE` inputs are preserved without claiming they form
a valid replay pack. The synthetic declaration is not proof of provenance.

This tool does not reconstruct missing context, collect new live evidence, grade
answers, or make the episode ready for the paired runner. Those limits are part
of the output, not assumptions left to the evaluator.

## Implementation result

The synthetic-only exporter and 70 focused CLI tests are implemented and pass;
independent review accepted the corrected code. Tests cover both native formats,
real History formatter output, pagination, Unicode, errors, damaged evidence,
repeated exports and publication failure/races. Publication requires filesystem
hard-link support and fails closed when it is unavailable. No private invocation
of this synthetic-only CLI ran; the later separate observation is described below.
These checks measure evidence-preservation correctness, not search quality.

At the earlier synthetic-stage checkpoint, the full non-slow suite stopped at an unchanged
Relay lock-budget test (1 failed, 1136 passed, 2 skipped, 1 xfailed). The required
serial failed-test rerun reproduced it. Do not claim full validation or completion;
see the Work Record for the exact test and evidence. The later approved private
policy and updated validation failures are recorded below. Human result review
and broader benchmark readiness remain open. No running service or
existing evaluation runner changed.

## Approved private pilot preparation

User approved local-only real-case selection on October 6. A directory outside
Git now contains the explicit storage/revocation/reuse policy
and a private metadata ledger. Initially it contained no selected raw records.
The initial20 recent file headers were delegated/guardian sessions. Four explicitly
identified user chats were then checked under independent review; all exceeded
the exporter's8MiB whole-file limit. Bounded one-MiB tails of those same files
contained no History search calls, so zero episodes qualified. This narrow finding
does not establish absence of usable cases in their complete histories.

Do not repeat this scan or build more capture machinery. The next selection needs
an exact known lookup/call location; bounded original-byte-window support would be
needed to export from large native sessions without copying entire chats. No
private-mode code or raw export was added merely to report progress. Context,
source lifecycle, corpus and benchmark qualification remain unresolved.

After incorporating the merged Relay fix from current main, full validation hit
two different unchanged integration tests. Evidence was handed to pallium-manager;
this task neither repairs them nor treats the incomplete suite as passing.

## Lookup-led real evidence

The earlier sampling stop was not a task blocker. Exact finalized lookup IDs
located three native request groups without another recent-chat census. Two had
all referenced sources currently accessible; one was excluded from raw capture
because three of ten referenced sources were missing. Missing does not establish
why they disappeared, and no inaccessible content was captured.

One independently reviewed partial development observation is now preserved
outside Git: five original records, 9,033 bytes (request, injected identity,
native call, exact returned blocks, final answer). Request identity is linked by
the injected source ID and native turn ID, not approximate time; the stored
request differs by one trailing newline, retained unchanged in the raw record.
Source lifecycle and selected-byte hashes were checked before capture; saved
bytes and manifest were reopened and verified. Existing October 13 review and
revocation/forgetting policy applies. Prior inspection is unknown before this
selection, and it is not held out.

Independent review detected sandbox ACL entries added to the pilot root. The raw
observation directory now has protected current-user-only access, verified on
both saved files. Root ACL correction failed with a privilege error; it retains
sandbox access to metadata/scripts, disclosed in policy. Reuse requires ACL checks.

This is not a complete episode or a replay benchmark: other calls influenced the
answer, full caller context and historical corpus are not frozen, and no answer
grade or search-quality number is claimed. The artifact is explicitly nonsynthetic,
partial and not replay-ready; it was not forced through the synthetic-only CLI.

The real format also exposed a concrete compatibility gap: Codex uses custom
`exec` calls and list-of-text outputs, sometimes followed by `wait`. The current
exporter originally handled direct function-call pairs but not these wrappers.
The minimal correction now preserves custom inputs and individual output blocks
as opaque `other` calls; false search/expansion claims are rejected, including
qualified and unqualified `wait` names. Seventy focused CLI tests pass. Private
mode, large-transcript selection and inner JavaScript interpretation were not added.
Preserving wrapper bytes does not establish inner History arguments or lineage.

## Frozen current-corpus development baseline

The user explicitly approved retaining the presented source dataset locally and
continuing routine preparation without repeated approval. A single read-only
transaction captured6,429 current non-forgotten private source rows in the
authorized container:9,300,866 content bytes,12,886,361 serialized bytes. Two
ordinary rows arrived after the earlier metadata-only count. This is selected
source data, not a whole live database, index, configuration or historical-state
copy. Raw source text may still contain sensitive data; it is not certified
credential-free.
Content/file hashes, exact membership, timestamps and scope are retained privately.
The October13 review/revocation policy applies to all corpus and fixture artifacts.

An independent non-implementer authored four concrete questions from recorded
evidence in four threads and froze query/expected source/content hashes before
retrieval. These are prospective development questions, not untouched real-user
queries or a held-out confirmation set. Exact-content duplicates count as one
evidence group; finding any identical copy succeeds. Other relevant answers may
exist, so a target-source miss alone would not prove answer failure.

The private one-off driver reuses SQLite source indexing, LexicalRetrievalProvider
and the service's source-only path, preserving source IDs/timestamps/thread order.
It disables embeddings, semantic plugins, query telemetry and retention workers;
the installed service is untouched. Frozen inputs are individually ACL-protected;
fixture/results were written under a pre-protected current-user-only parent and
their permissions rechecked. Source lifecycle was revalidated before and after.

| Development case | Required evidence found in top10 | First matching rank |
|---|---|---|
| 1 | Yes | 1 |
| 2 | Yes | 4 |
| 3 | Yes | 1 |
| 4 | Yes | 1 |

Measurement: **known-evidence candidate recovery**,4/4 (100%) at10 on these four
authored development cases. Each query ran twice with identical ranked IDs.
No provider/model calls ran. Corpus, cases, code and configuration hashes accompany
the private results. No retrieval change or candidate improvement was tested.

Limits: lexical-only/default configuration, no actor filter (actor metadata was
not retained), no historical index/config reconstruction, no negative-relevance
labels, no precision or downstream-task-effect measurement. These checks can
catch regressions on their predefined evidence but cannot establish broad absence
of regressions. The original dict-manager actual-recovery gate remains separate
and failed; these four successes do not replace it. Further proposed retrieval
changes should preserve the fixed gold and queries and receive additional
task-sufficiency checks where needed. Later lifecycle revalidation invalidated
corpus-01 for reuse; its score must not be paired with a revised-corpus arm.

## Bounded investigation: what the existing experiments establish

The earlier incident investigation is reused, not rerun. Its tested variants
included larger candidate pools, alternate fusion/semantic ordering, neighboring
message text, question-first retrieval, request-prefixed text, corrected E5
pooling, and a local cross-encoder with and without additional caller context.
None established complete recovery within the original caller limits. Some
authored controls regressed. These results do not justify deploying a combined
ranking change merely because its components sound complementary.

Three generic corrections addressed evidenced failures: source-only lexical
refill, continued context selection past oversized neighbors, and content-first
expansion packaging. The saved answer-aware path could deliver the needed later
messages within the original total character budget, but the fresh blind caller
still failed. Delivery capacity and finding the right discussion are different
claims. The corrections do not establish that the incident is resolved.

The current ONNX provider still uses CLS pooling where the E5 model contract
calls for masked mean pooling. This is a separate correctness concern, not a
demonstrated incident remedy: the earlier mean-pooling experiment did not recover
the incident. Any eventual correction needs matching document/query embeddings
and an index transition, not a query-side-only switch.

The evidence therefore does not support either extreme: that another generic
ranking tweak will necessarily solve this, or that the agent's query is solely
at fault. Ambiguous references can require clarification, but that explanation
must not hide candidate selection, indexing, or delivery defects.

The prior development experiments and their limits are recorded in
`docs/reports/history-retrieval-investigation-2026-10-05.md` on the separate
`feat/history-planning-retrieval` branch at `db74865a6f4e9a34e8bd4a4f163ec9d59350c942`;
that report is not part of this branch. No derived memories,
new ranking runtime, paid calls, downloads, or installed-service changes were
introduced by this investigation.

## Revised-corpus comparison

Before further inference, lifecycle validation found eleven corpus-01 source IDs
missing from the live store. All required evidence IDs remained present. The
missing messages had crossed the ordinary thirty-day raw retention boundary;
routine retention is plausible, not a proven deletion cause. No observed
forgotten, scope-changed or visibility-changed rows remained in that check.

One independently approved corpus-02 derivative retains6,418 exact original rows,
with private exclusion/parent-hash lineage, protected access and the same expiry.
No new live content or revised gold/questions entered it. Both methods were run
afresh against this identical corpus; corpus-01's earlier score is not their
paired baseline. Any further lifecycle divergence ends the cycle, not another
amendment. Both before/after checks passed for the completed comparison.

The original four controls were joined by four harder source-grounded authored
questions from four additional threads, plus two fabricated exact-label absence
controls. Each was frozen before its first retrieval outputs; all remained fixed
for this comparison. This remains a small development set,
not held-out natural-user evaluation or a general non-regression guarantee.

| Known-evidence candidate recovery at10 | Lexical | Production-pooling hybrid |
|---|---:|---:|
| Original four positive controls | 4/4 | 4/4 |
| Four harder positive controls | 1/4 | 1/4 |
| All eight positive controls | 5/8 | 5/8 |

Both methods missed the same three predefined evidence groups. Finding another
sufficient answer is possible, so these target-source misses are not independently
graded answer failures. Hybrid changed ranks but showed no group-recovery gain:
the original four ranks changed from1/4/1/1 to1/1/1/8; the recovered harder case
changed from1 to4. Repeated queries returned identical ordered IDs.

The complete private hybrid index used5,953 eligible passages, the pinned cached
multilingual E5-small ONNX/tokenizer, production CLS pooling, prefixes/truncation,
similarity floor and fusion. Sixteen probe vectors were reused. Rebuild, persistence,
queries and formatting took469.470seconds, excluding initial fixture/model setup;
the whole worker completed inside its1,200-second cap. No external calls or
downloads occurred. This is a complete rebuilt development index, not the live
index: a metadata census had pending/missing entries and could not certify exact
live-vector/content/model-revision binding.

Each absent-label question still returned ten related candidates from each method.
That is not itself an error: search is not a claim that the requested fact exists.
It demonstrates why returned hits alone cannot establish supported attribution.
No hallucination, abstention, injection-precision or downstream-effect score was
measured.

Direct compact formatting preserved all100 returned handles across the ten cases
per arm, using32 lexical pages versus40 hybrid pages. First pages contained35
versus29 handles in aggregate; these are packaging observations, not answer scores.
None of the four longer frozen required spans appeared verbatim in previews;
three exceeded the240-character excerpt ceiling by construction. The only
recovered harder-case handle per arm was then expanded with no neighbors and a
4,000-character cap. Each1,356-character output contained its required span.
The three unrecovered handles were not supplied secretly to expansion. This is
answer-aware delivery feasibility, not blind navigation, actual MCP receipt or
proof of complete answer sufficiency. Redaction/clipping can also affect spans.

## Final option and decision

Exactly one additional generic option was tested: documented attention-masked
mean pooling plus L2 normalization consistently for both documents and queries.
Its justification was the preexisting E5 encoding-contract mismatch, not tuning
to these outputs. It rebuilt all5,953 passage vectors in a separate protected
index; no CLS vectors were reused. Cases, corpus, K10, similarity floor, fusion,
prefixes, tokenizer and truncation stayed fixed. The unchanged lexical results
were reused, not rerun. Before/after lifecycle checks passed.

Mean-pooling hybrid again recovered5/8 groups: original4/4, harder1/4, same three
misses. It improved the recovered originals to ranks1/1/1/1 and the recovered hard
case to1, but recovered no additional predefined evidence group. Across ten cases
it used40 compact pages and preserved100 handles; those aggregate page counts
are not a per-task budget or an injection-precision score. The one recovered hard
case again exposed its span on bounded expansion; the three missing handles were
not expanded. Rebuild/persistence/query/final-check duration was517.758seconds,
excluding initialization, within the whole-worker1,200-second cap. No paid or
external model calls, downloads, production edits or further variants followed.

Decision:

- Do not deploy a ranking, context, reranker or combined heuristic change on this
  evidence. None demonstrated the required complete recovery, and eight authored
  positives cannot establish safety across other searches.
- Keep the pooling mismatch as a separate correctness concern. Better ranks here
  do not make it an incident fix; any implementation must version/rebuild both
  sides of the index and satisfy its own broader regression and rollout gates.
- Keep the proven delivery corrections distinct from discovery. Once a required
  handle was found in this check, bounded expansion exposed its evidence. Finding
  the correct discussion remains unresolved, and ambiguity alone is not a proven
  sole cause.
- Use the preserved cases and exact provenance for future concrete failure-led
  comparisons, subject to lifecycle and retention revalidation. Do not resume
  speculative sweeps or label the pack a complete benchmark. Genuine linked user
  tasks, complete caller context and independent answer grading remain necessary
  for downstream claims.

The bounded research cycle is finished; the broader product and original recovery
gates remain open. In the subsequent authorized delivery, the user accepted this
evaluation deliverable and requested merge. Fresh full validation on current main
plus the unchanged exporter/tests passed6,084 tests (34 skipped,2 xfailed);
independent result review accepted the sanitized five-file diff. Earlier failed
runs above remain historical evidence, not claims of a diagnosed Relay fix.
PR CI/review still governs delivery. No installed-service change or rollout is
part of this merge.
