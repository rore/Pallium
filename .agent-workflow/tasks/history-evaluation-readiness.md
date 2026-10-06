<!-- agent-workflow:start -->
**Outcome:**
Session History evaluation can preserve and reuse trustworthy cases without changing search behavior or reintroducing derived memories.

**Target:**
Pallium Session History evaluation readiness.

**Scope:**
Reconcile prior evaluation commitments with shipped behavior, select the smallest missing capture/replay/preservation slice, review its privacy and verification contract, and implement only after required approval.

**Constraints:**
Reuse existing evaluation and History seams. No ranking changes, derived memories, paid model calls, new dependencies, live service mutation or private content in Git. No automatic expanded retention of private content without explicit approval. Preserve visibility, redaction, forgetting and retrieval-is-not-use; protect existing private experiments and PR278.

**Completion criteria:**
Original requirements map to evidence and named gaps; a reviewed bounded plan defines preserved case data, privacy/deletion, replay fidelity, costs and end-to-end acceptance; any approved implementation passes that acceptance before evaluation readiness is claimed.

**Requirement baseline:**
{"source":"077fd084-935b-40b5-880b-d99b2493f6a4","outcome":"Session History evaluation can preserve and reuse trustworthy cases without changing search behavior or reintroducing derived memories.","scope":"Reconcile prior evaluation commitments with shipped behavior, select the smallest missing capture/replay/preservation slice, review its privacy and verification contract, and implement only after required approval.","constraints":"Reuse existing evaluation and History seams. No ranking changes, derived memories, paid model calls, new dependencies, live service mutation or private content in Git. No automatic expanded retention of private content without explicit approval. Preserve visibility, redaction, forgetting and retrieval-is-not-use; protect existing private experiments and PR278.","completion_criteria":"Original requirements map to evidence and named gaps; a reviewed bounded plan defines preserved case data, privacy/deletion, replay fidelity, costs and end-to-end acceptance; any approved implementation passes that acceptance before evaluation readiness is claimed."}

**Risk:**
High

**Complexity:**
Moderate

**Reason:**
Evidence capture design affects private-content persistence and forgetting. High
judgment floor while choosing that contract. Approved implementation touches only
the blue evaluation/test surfaces named below; no runtime target is changed.

**Discovery:**
Prior read-only audit found ordinary lookup events preserve source identities and
lineage but not exact formatted pages/options/revisions. Explicit diagnostics and
the qualified reliable_pair_runner already exist. Some old private exclusion
manifests were not recovered. See the upcoming reconciliation report for evidence.

**Material assumptions:**
No new evaluation framework is needed; inspect existing pack/runner seams first.
No installed revision is inferred from a healthy status endpoint. Historical
reports do not establish current capture coverage or usable-case counts.

**Plan:**
First implementation step: invoke /agent-workflow to create the Work Record and
classify risk before any code edit. This record started that process before human
approval of the concrete slice below. Compare original Done-when requirements to source and
reports. Prepare docs/reports/history-evaluation-readiness-2026-10-06.md and
reconcile the owning roadmap/ideas/idea-pull-real-corpus-validation.md, preserving
completed component evidence. Choose the smallest privacy-conscious slice with
independent review; obtain separate approval for its concrete High-risk contract.
Do not open private historical content or rerun old censuses/experiments.
Concrete proposed implementation is the report's one evals/history_episode_export.py
CLI and tests/test_history_episode_export.py, synthetic-only qualification. Existing
runner remains unchanged; real private invocation is a separate explicit gate.

**Verification plan:**
Requirement reconciliation -> source/report references for each kept or missing obligation.
Bounded privacy/replay design -> independent technical review with explicit trade-offs and rejection paths.
Approved implementation -> real caller and existing runner E2E including pagination, truncation, Unicode, retry, source mutation, forgetting, scope and preservation across worktree retirement; no claim before it runs.

**Plan review:**
Agent technical review: /root/comparison_review approved the concrete planning
slice at3093df26 plus these three docs on2026-10-06. Require provable complete
caller-context identity/order or an explicit incomplete classification; preserve
raw exact tool strings, avoid duplicate raw copies, and keep execution synthetic
until private destination/deletion/redaction authority is approved. Conditions
incorporated in the report. Separate human implementation approval received below.

**Approvals:**
Approved by user 2026-10-06: "so yes, merge this in" (request source
`d0b9310f-36b6-4467-91f8-ed819aff58ee`). Human result acceptance and authorization
to push, create/review the PR and merge the evaluation-readiness deliverable after
required validation and review. Excludes PR278 retrieval fixes, private evidence,
installed-service changes and any waiver of failing checks or broader product gates.
Approved by user 2026-10-06: "ok, so go through it, don't stop each time. go through the plan and give me a final result"
authorizes the presented bounded investigation through final recommendation:
full-path comparison where reproducible, a few difficult/irrelevant controls,
evidence-led experiments only, no production changes/paid calls/derived memories.
Approved by user 2026-10-06: "let's do this, you don't need to ask on each step"
authorizes the presented local corpus snapshot (metadata count6427records/about
9.3MB), up to four concrete retrieval cases and existing deletion policy. Routine
selection/validation proceeds without repeated approval; no upload/paid model calls.
User continuation 2026-10-06: "so why are you stopping?" Proceed with the already
authorized local-only selection; exhausted arbitrary-file sampling is not a task
blocker. No additional privacy or export authority is inferred.
Approved by user 2026-10-06: "yes," in response to selecting a small set of real
search episodes for local-only evaluation outside Git, without uploads or paid
calls, establishing explicit storage/deletion rules before export.
User direction 2026-10-06: "so don't stop"; then "don't fuss about relay tests,
it's not your responsibility. if there's a relay problem tell pallium-manager
to check it". Continue evaluation work, but do not change or investigate Relay tests.
Approved by user 2026-10-06: "i approve," (message text: "i approve, ").
Approval covers the presented synthetic-only exporter implementation and tests;
no private invocation, runtime capture, paid calls or service changes.
Approved by user 2026-10-06: "so can we advance that?" Scope authorizes advancing
readiness reconciliation and planning. Concrete private-retention/runtime contract
has not yet been presented or approved.

**Exceptions:**
—

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

Implementation authorized from6b377e59. Exact code targets are
evals/history_episode_export.py and tests/test_history_episode_export.py, both
blue evaluation/test surfaces. Existing High privacy-design judgment retained;
no runtime or protected behavior-contract file is modified. Lead owns docs/record;
bounded implementer owns those two code files; independent reviewer verifies
contract and CLI tests. Missing-context readiness remains incomplete by default.

Branch feat/history-evaluation-readiness starts from3093df26.
New managed worktree is separate from PR278's unfinished implementation and
private evidence. No search/runtime/installed edits. Current intended changes:
this record, the named report, owning product-gate roadmap item and the two approved
exporter/test files. No other code is changed.
Normal workflow applies: Work Record and report are outside the docs-only allowlist.

## Evidence

Implementation review caught a native-format mismatch (expansion has parent lookup
but no own lookup ID) and corrected fixtures to public page/revision shapes.
Independent result review by /root/eval_telemetry_audit found empty expansions
bypassed anchor validation and POSIX rename could replace a racing empty directory.
Both are being corrected in the same two approved files. Reviewer approved the
minimal publication refinement: exclusive destination creation, manifest published
last as the usable-output commit marker, incomplete outputs rejected, and cleanup
limited to files created by this attempt. Directory visibility itself is not atomic.
The prior reviewer could not be resumed due to an agent-thread limit; this reviewer
did not implement the change. No scope or runtime expansion.

Initial corrected focused suite: 44 passed and one unexplained filesystem publish
rejection; its stderr was truncated in the assertion output. The required failed-test
rerun passed, then the already-dispatched full-file run passed 45 tests. This is
recorded as an unresolved transient, not diagnosed away by a green retry. Publication
is subsequently changing for the independent no-clobber finding; final evidence
must exercise the replacement and retain the earlier limitation.

Read-only source audit /root/eval_telemetry_audit distinguishes IDs finalized by
the formatter from byte-exact output and actual caller consumption. Live status
reported1181 mixed events and funnel armed, not1181 usable cases. Current installed
revision and exact live source implementation remain unverified.

## Result review

Agent technical review: /root/eval_telemetry_audit (independent non-implementer).
Reviewed revision:6b377e59 plus the final exporter, CLI tests and documentation diff.
Verification adequacy: both reported defects resolved; actual public formatter
outputs and publication fault/race cases now covered. Reviewer approves the
synthetic-only implementation subject to required checks passing. Final focused
command `python -m pytest tests/test_history_episode_export.py -q -n 0` passed
52 tests with no skips. This measures exporter integrity, not candidate recovery,
injection precision or downstream task effect. Import-boundary and Redline checks
passed; diff check passed. Ruff was unavailable; no dependency was installed.

Required full lane `python -m pytest tests/ -x -q` stopped at 1 failed,
1136 passed, 2 skipped, 1 xfailed. Failure:
`tests/test_codex_retained_wake.py::test_session_start_lock_budget_claims_emits_and_acks_once[user_prompt_submit-released]`.
Observed timeout1.8213055001106113 exceeded asserted1.8. Required serial
`python -m pytest --lf --lfnf=none -q -n 0` also failed with1.8176471000770107.
Test and hook files are unchanged from3093df26; no unrelated fix, skip or assertion
weakening was made. Full-suite log: `build/history-episode-full-tests.log`;
failed-test log: `build/history-episode-last-failed.log`. Full collection started
before final exporter corrections; final focused52 covers those corrections.
The full suite is NOT passing or complete. Next action is triage of this separate
Relay timing failure, then finish required validation and human result review.

No private export, paid calls, runtime/service changes, push or PR creation.
Broader evaluation readiness remains open. Parent retains this worktree specifically
for validation-blocker resolution and result review. PR278 and its private evidence
remain separate and untouched.

### Relay blocker handoff — October 6

At user direction, stopped the bounded read-only Relay diagnosis before any edit.
Sent exact failure evidence and log paths through Relay to `@pallium-manager`:
`relay-msg-20056071314a4221b6830f27d63a0a83`. Admission resolved to session
`01a0d7ce-83c6-77e2-90f7-d413894059e1` in `git:github.com/rore/pallium`.
Send returned pending, not confirmed receipt or accepted ownership. No resend.
Do not repair, weaken or repeatedly rerun Relay tests in this task. Full validation
remains unresolved pending the owner's disposition; the exporter evidence is
unchanged. Real-case export still requires the separately agreed selection and
private export policy, not further infrastructure or speculative search changes.

### Approved real-case preparation — October 6

First implementation step: invoke Agent Workflow and classify risk before code
edits. Whole change remains non-exempt; High/Moderate retained. Synced isolated
branch with verified origin/main dbb699f4 (PR284 fixes the reported timing fixture);
no duplicate Relay correction. Full selector-required validation is running.

Bounded next slice: at most four real development episodes, chosen from at most
20 recent native transcript files using metadata/tool-call presence first. Exclude
this active evaluation thread and old incident/research threads; do not infer
held-out status from dates. Inspect only selected candidate request/call/answer
windows, not unrelated transcript content. Preserve raw evidence, not summaries.
Stop at the cap or at missing provenance; report attrition rather than pad cases.

Private pilot: user-selected storage outside Git; exact location retained privately.
Verify outside Git and symlink/junction-free, restrict access to the current user
before writing private data. No uploads, new sync, backup copies, ingestion,
model calls or live service mutation. Host-wide backup exclusion cannot be proven;
do not claim otherwise. Raw records are unredacted and remain local. Only anonymized
counts/readiness findings enter tracked docs.

Retention: local pilot artifacts are development evidence, not a permanent archive.
Stop using and delete the entire pilot directory on user revocation or known
source forgetting; before future reuse revalidate original source accessibility
and hashes. Review by 2026-10-13; expired artifacts must not be reused without a
fresh explicit decision. No automatic deletion scheduler is claimed or created.
Deletion includes selected records, selections, manifests and any local scratch
copies under this one directory. Never delete original transcripts or old evidence.

Plan for existing exporter only if candidates qualify: add an explicit mutually
exclusive private opt-in, allow explicit native input paths only in that mode,
retain existing safe destination, bounds, integrity and incomplete-readiness rules.
Do not relabel real input synthetic. No new framework or runner adaptation. Two
existing code/test paths remain blue; privacy judgment remains High. Independent
review precedes private opening/export. Lead owns selection and policy; bounded
worker may implement only that reviewed opt-in with synthetic tests.

Independent plan review /root/eval_telemetry_audit approved this bounded pilot.
Missing native identity/authorization rejects selection. Unknown old exclusion
membership or prior inspection is recorded unknown and development-only, not
reconstructed or asserted held-out. Before reuse, referenced History source IDs
also require accessibility/known-forgotten checks; unavailable lifecycle evidence
blocks corpus replay claims, even when transcript hashes match. Check selected
whole-record spillover; skip unrelated private multi-block content. No new framework.

Real-case preparation outcome: private pilot root created with current-user-only
ACL (inheritance disabled), policy saved before content handling. First20 headers
were all delegated/guardian sessions. Reviewer approved one targeted refinement
using four app-returned user-chat IDs; native IDs matched but all files exceeded
8MiB. Reviewer then approved qualification-only inspection of the same four1MiB
tails plus identity metadata, preserving original offsets/hashes and rejecting
unstable reads. No new files or larger byte cap. All windows stable and complete
after explicit leading-line omission; zero History search calls in those windows.
No task/source text was emitted and no episode was exported. Private ledger and
script are in the policy root. This is bounded attrition, not proof of absence of
usable history in the full sessions. Discovery stopped; no private-mode code was
added without a qualifying case. Future selection must start from known lookup
identities, not repeat recent-file/tail scans. Large-native-session byte-window
support is a diagnosed exporter limitation, not implemented or silently bypassed.

Post-sync full validation at d9d677a0 stopped with2failed1450passed2skipped1xfailed:
`test_busy_queue_recovery_stays_single_flight_and_competing_hook_blocks_overtaken_wake`
and `test_codex_setup_refuses_accidental_live_checkout_replacement` (WinError5
readiness os.replace). Log: build/history-episode-full-after-sync.log. Handed off
to @pallium-manager in relay-msg-82d5c5dfb0f84eedb7105a17a5bcf533; no changes or
repeated runs of these tests here, per user's direction. Full validation remains
unresolved. Source code unchanged from reviewed exporter; no push/merge/rollout.

Independent preparation result review: /root/eval_telemetry_audit inspected the
private policy/metadata ledger and public report, accepted bounded attrition and
privacy claims, and requested one stale-status correction now applied. This is
approval of preparation evidence only, not benchmark or full-validation completion.

### Lookup-led continuation

Independent reviewer /root/eval_telemetry_audit approved exact lookup-led selection:
require exact native request identity, call ID/arguments, matching finalized
lookup output and an actual task answer for complete recorded episodes. Missing
answers/outputs remain explicitly partial evidence; never coerce the mandatory
answer exporter. Preserve offsets/hashes and lifecycle/spillover checks. Continue
other request groups when one fails; no synthetic-mode bypass for private data.

The earlier stop was an execution mistake: the failed sampling method did not
exhaust authorized read-only alternatives. Metadata-only SQL against the verified
configured database, read-only/query-only, returned20 latest scoped lookup IDs
excluding this active thread. This is a new direct-identity method, not another
file/tail census. Deduplicate exact request IDs before choosing up to four cases.
Exclude known research/coordinator episodes. Use request metadata/native source
references to locate exact original records; inspect bounded windows only after
identity/lifecycle checks. Existing private root, no-upload/no-paid-call limits,
development-only labels and deletion policy continue unchanged.

Trigger2 feedback dropped: repeated stopping was this agent's execution error,
not an upstream workflow defect. Continue safe authorized alternatives without
requesting repeated approval for the same objective.

Lookup-led outcome: three exact request groups found in native outputs; one
excluded because3/10 referenced sources missing. One other group retained as a
reviewed partial observation:5 complete raw records9033bytes outside Git, exact
request hook ID/native turn linkage, call/result ID, lookup ID and final answer.
All10 returned sources plus request currently accessible/not forgotten in scope.
Raw request retains its trailing LF; source bytes rechecked before capture and
saved artifact reopened byte-exact afterward. No full-context/corpus/grade/replay
claim; other calls influenced answer. Private retention policy unchanged.
Independent /root/eval_telemetry_audit approved this one-off artifact before capture.
No synthetic-exporter bypass or runtime change. Actual wrapper compatibility gap
now established; investigate a minimal synthetic-format correction only.

Independent plan review approved the minimal native-format correction in the
already approved exporter/test files: pair Codex custom calls and preserve opaque
input and text blocks without executing JavaScript, flattening blocks or claiming
inner History lineage. Synthetic-only/private/live-directory gates stay unchanged.
Anonymous CLI boundary/pairing tests required. No byte-window/private-mode feature.
Reviewer verified5raw hashes and flagged extra sandbox ACL entries on pilot root;
lead restored current-user-only protected observation ACL and verified both raw-file
access rules. Root ACL correction failed with SeSecurityPrivilege; metadata/scripts
root still includes sandbox principals, so policy distinguishes it from the protected
raw observation directory. Recheck on reuse; do not assume tooling preserves ACLs.

Wrapper correction: focused CLI suite70passed. Parent and independent reviewer
caught unqualified wait-name bypass; fixed both name spellings and added four
string-output false-lineage rejection cases. Native custom input/output is opaque,
kind=other only, blocks preserved separately; no JS interpretation/private mode.
Fresh whole-change test selector still requires full lane. Earlier integration
failures remain with manager; no repeat or waiver. Fresh lightweight Redline BLUE
and workflow advisory-only (existing commit-order advisory), not full CI evidence.
Final independent result review /root/eval_telemetry_audit approved the bounded
wrapper correction and accepted focused70 evidence; no remaining actionable code
findings. Raw observation hashes and corrected raw-directory ACL independently
verified. Human result review/full validation and broader replay readiness remain.

Follow-up readiness decision: independent reviewer confirms the retained vague
recap is provenance evidence, not a benchmark task. Smallest meaningful quality
slice is up to four concrete development questions with independently chosen
required sources before outputs, fixed current corpus/config/budgets; measure
candidate recovery only, not downstream effects or precision of unlabeled hits.
Metadata-only current scoped private active corpus:6427rows,9299947contentbytes,
207threads; no content copied. Freezing corpus text (including distractors) is a
distinct privacy scope from four selected native episodes and awaits explicit
user approval. Do not add another exporter or infer historical replay fidelity.
Manager Relay update: two integration failures triaged read-only; separate owner
follow-up, not fixed. Wake no-reemit held; unavailable stderr possibly fixture clock
leakage; readiness os.replace cause unconfirmed. No local investigation or rerun.

## Approved corpus preparation

Invoke /agent-workflow and retain High/Moderate classification before corpus
capture. Private-only scripts/artifacts under the existing pilot; no production
changes. Read source rows in one SQLite read-only transaction for exact injected
container, private visibility, forgotten_at null. Export only source content and
retrieval metadata, not the whole database or configuration/credential tables.
Source text may still contain sensitive data; it is not certified credential-free. Bound content
to16MiB, publish exclusive corpus directory with current-user-only ACL checked
before/after. Store IDs/revisions, count/bytes/hash, scope/time and retention policy.
Freeze up to four concrete questions/required source IDs independently before
retrieval outputs. Reuse existing offline retrieval seams; no provider calls.
If available seam is lexical-only, label that limitation and do not equate it
with installed hybrid baseline. No current snapshot mislabeled historical replay.
Independent review required before capture; user approval now recorded above.
Independent /root/eval_telemetry_audit approved plan before capture. Snapshot
captured6429rows9300866contentbytes (two new ordinary rows since metadata census),
12886361serializedbytes within caps; exact saved aggregate/content hashes verified.
Protected destination/source file ACL current-user-only verified. No live DB copy.
Independent question selection precedes any retrieval outputs. Private one-off
driver reuses source-only service/SQLite lexical provider without semantic/vector
providers, preserves original IDs, topK10 and repeatability check. No production
edits, installed writes or provider calls. Actor metadata absent from snapshot:
actorNone/noactorfilter; default-config lexical candidate recovery only, not live
hybrid or historical replay. Public record contains no case text/source IDs.
Four source-grounded prospective development questions frozen by non-implementer,
four distinct threads, exact source/content hashes; case hash privately recorded
before execution. Same-content alternatives count as one evidence group, not
false duplicate-ID misses. Reviewer approved driver with two conditions completed:
protected current-user-only run parent before DB writes, explicit October13 cutoff.
Editing tools added sandbox access to corpus parent, so three frozen input files
are individually ACL-protected; raw outputs inherit only protected-runs access.
Baseline completed: four known-evidence groups recovered at top10, ranks1/4/1/1;
two repetitions per query identical. No provider calls/runtime mutation. Independent
/root/eval_telemetry_audit verified input/output hashes, recomputed scores, every
fixture source ID/content hash matching6429 captured rows (no gold/query ingestion),
lifecycle timestamps and raw-output ACL; accepted this limited candidate-recovery
result. No precision/hybrid/downstream/generalization claim or candidate change.
Approved corpus/four-case preparation is complete. Whole feature delivery remains
blocked by separate integration validation/human result review; broader product
gate and original actual-recovery failure remain open. Next substantive retrieval
proposal can use these frozen controls; no automatic tuning or repeated runs.

## Final investigation cycle

Reuse prior incident research without reruns. Establish local-only hybrid baseline
using already installed/cached ONNX model, never download or call network/provider
services. At most four additional difficult controls plus two absent-answer checks,
independently frozen before outputs; keep original four unchanged. Use current
snapshot in isolated protected files; preserve all old artifacts. Inspect actual
formatted output/context where necessary; do not equate candidate recall with
answer sufficiency. Test at most two genuinely evidence-justified generic options
if identified, otherwise recommend no ranking change. Independent review must
check costs, corpus/model/code fidelity, leakage and final conclusions. Stop this
research cycle with a final supported recommendation or explicit unresolved limits,
not another speculative implementation. Existing integration/release gates remain.

Independent review accepted four additional source-grounded development questions
and two exact-label absence controls, frozen before retrieval; original four
unchanged. Negative controls establish exact-label absence only, not universal
semantic absence or an empty-result requirement. Private required spans support
delivery-capacity checks, not full answer grading.

Before model loading, lifecycle validation stopped corpus-01 reuse: eleven rows
were missing, no observed forgotten/scope/visibility drift among remaining rows.
All required evidence remained. Missing rows had just crossed ordinary thirty-day
raw retention; routine cleanup is plausible, not proven. No inference ran on the
invalid set. Independent reviewer approved one explicit corpus-02 derivative:
6418 byte-equivalent original rows, no new content or revised questions/gold,
eleven missing exclusions with private lineage and hashes. Original corpus-01
is not reusable and its earlier score is not paired with revised-corpus results.
Any further lifecycle drift ends this cycle as inconclusive; no further amendment.
Protected current-user-only derivative ACL and membership independently verified.

Pinned cached E5-small ONNX/tokenizer probe on sixteen passages:1.850s model load,
1.110s inference;5953 eligible passages, screening projection415.840s, not a proven
upper bound. Local CPU only, download bootstrap bypassed, no network/paid calls.
Probe hashes/lifecycle independently verified. Full private lexical/hybrid driver
review approved after timeout-provenance and assertions guards;1200s cap, fixed
top10, same cases/corpus, two repetitions, production providers/fusion and direct
compact formatter pages. Complete rebuilt index is not installed-index fidelity.
Source/config/model/code identities and lifecycle checks remain required.
Oracle expansion capacity check approved only for genuinely returned required
handles:before0/after0/max_chars4000, unchanged spans, no query repair or neighbors.
It cannot establish blind navigation, transport receipt or downstream task effect.

Completed revised-corpus baseline: lexical and production-CLS hybrid each5/8
predefined positive evidence groups (original4/4, harder1/4), same three misses;
two exact-label controls returned related hits, no answer/abstention score.
Repeated ranks stable. Rebuild/persistence/query/format duration469.470s excludes
initial setup. All6418 sources and5953 vector entries remained isolated;
independent review verified exact6418 source/lexical rows, positions, vector
metadata and no query/gold ingestion. Formatting preserved all100 handles per
arm across32/40 pages; preview spans0/4 are not a bug (three exceed excerpt cap).
Only recovered hard-case handles expanded:1356chars and required span present
under4000 cap for each arm. Three misses not secretly expanded. Bounded saved
top-three review found partial alternative evidence in one case; do not equate
predefined-group misses with independently graded answer failures.

Independent reviewer approved exactly one final generic comparator: consistent
document/query attention-masked mean pooling plus L2 for the pinned E5 model,
instead of current CLS pooling. Justification is the preexisting encoding-contract
mismatch, not a prediction of improved scores. Same corpus/cases/K10/floor/fusion/
prefix/truncation, new isolated private index, no production edit, no download,
<=1200s cap. Reuse lexical evidence; no further variants regardless of outcome.
This is not an old incident rerun, runtime approval or deployment justification.

Final mean comparator completed within cap; consistent masked mean/L2 doc/query,
5953 newly rebuilt vectors, immutable lexical results reused. Before/after
lifecycle passed. Candidate recovery remains5/8 (original4/4, harder1/4, same
three misses); recovered ranks improved but no additional evidence group found.
Rebuild/persistence/query/final-check duration517.758s excludes initialization.
Only recovered hard-case handle expanded and contained its span; other three
not expanded. Independent reviewer verified hashes, frozen inputs, scores,
fixture/index provenance, unchanged baseline, lifecycle evidence and private ACLs.
No further option tested, no production search change justified. Research cycle
concluded; separate broader readiness, integration validation, human result review
and original actual-recovery gates remain open. See final report for the supported
recommendation and explicit limits.

Final documentation diff check passed. The runtime workflow check required the
explicit existing Python interpreter, then reported missing Redline verdict
input (including behavior-contract verdict detail); it is not a passing complete
workflow/CI check. No governance policy was changed or gate waived. Earlier
integration failures remain with their owner and were not rerun. This local
research checkpoint is not push/merge/release readiness.
Independent final public-claim review approved report/roadmap, with case-freeze
wording clarified: each case preceded its first outputs, not every case preceding
all earlier baseline outputs. Correction applied; no further experiments needed.

## Authorized delivery

Whole-change applicability remains normal/non-exempt: exporter/test code plus
Work Record/report are outside the documentation-only allowlist. Existing
High/Moderate privacy judgment retained; actual changed paths are Blue and no
behavior-contract file is changed. User accepted the presented result and requests
merge of this deliverable, not resolution of the separate original search incident.
Synced current origin/main d03c487f by clean merge; no unrelated local edits.
Next: fresh required full validation, current Redline/workflow evidence, reuse or
refresh independent result review for the final diff, public-only PR, inspect all
CI/comments/review threads, and merge only with required gates satisfied. No
installed rollout or private-artifact cleanup is part of this delivery.
Known integration failures remain with pallium-manager; sent status request
relay-msg-4a188fd6727f462395283e9d658d4513, pending is not acknowledgement. Required
validation is delegated; no Relay diagnosis or test weakening is authorized here.

Fresh required full validation at67a8574d4254285461b8177fa7f1b47b8e24eb0a passed
once:6084 passed,34 skipped,2 xfailed;370.53s pytest,373.16s command. Command:
`python -m pytest tests/ -x -q`. Ignored log:
`build/history-evaluation-readiness-full-2026-10-06.log`. Only documentation changed
during that run; tested application/test content is unchanged. No failed-test retry
was needed and no earlier Relay failure is claimed diagnosed or fixed here.
Current import-boundary check passed. Fresh complete changed-path/numstat/diff
Redline report has no boundary violations or required checkpoints; workflow is
advisory-only for the existing historical commit-order note. Missing-verdict
invocation limitation is resolved by supplying a freshly generated verdict.

Agent technical review: /root/eval_telemetry_audit independently accepted the final
five-file diff and reused its valid exporter70-test and public-claim reviews.
Reviewed revision:67a8574d plus documentation-only delivery/privacy corrections.
Verification adequacy: synthetic exporter caller boundaries plus current full
suite; no private data, runtime change or broader benchmark-readiness claim.
Two documentation findings corrected: private storage path removed, source-text
privacy caveat clarified. User merge instruction is separate human result acceptance.
Original unpublished development history will remain on a local evidence branch;
the public branch is prepared from current main with the same sanitized five-file
tree so removed private paths do not appear in newly published commit history.
PR CI and review-thread inspection remain required before merge. Broader product
and original search-recovery gates remain separate and open.
