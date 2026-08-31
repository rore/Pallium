# B2 candidate review — 2026-08-31

Current verdict: deterministic candidate accepted after final manager fixes and
independent Relay Dev review; 296 tests pass. G2/G3, PR merge and activation are
not complete. See the final result below. Earlier findings are historical.

Original b06aa89 verdict: CHANGES REQUIRED. G2/G3 qualification and
activation remain blocked. Independent targeted rerun: 103 passed, four existing
warnings. Those tests do not establish the promised whole-batch/lifecycle contract.

## Reproduced through actual surfaces

Disposable HTTP fixture, real storage and actual Codex common.format_relay:

| Probe | Actual result | Required result |
|---|---|---|
| Pass a real candidate turn envelope to the hook formatter | Empty string, zero rendered deliveries | Entire attributed envelope accepted |
| Publish candidate, expire lease, call legacy router turn for same recipient | Same message reclaimed as text_v1 | No legacy bypass of publication ownership |
| Claim; expire message while lease is active; start publication | 200 | Reject pre-output expiry |
| Claim candidate; reply with valid receipt before publication-start | 200 and parent ACK | Reject bypass of candidate publication/admission contract |
| Publish older message; expire its lease; queue newer; candidate turn | Newer delivered while older becomes uncertain | Preserve the declared ordering barrier |

These are independent successful reproductions, not hypothetical review comments.
The live service/database was not used.

## Consolidated corrections

### 1. Finish actual whole-batch data flow

_batch_envelope inserts message.payload verbatim; there is no payload_format
dispatch, decode_parts/prepare_parts usage, ordered part labels/count or safe
content escaping. Tests send only single text payloads. A parts_v1 row would be
raw JSON, not the agreed whole-batch envelope, and payload text can forge headers
or the terminal marker. Fixture-only must mean the real candidate protocol
activated in disposable fixtures, not a different singleton approximation.

Implement the same typed send/reply/claim/render/read path for actual six/eight-part
messages in candidate fixtures while default public acceptance stays disabled.
Enforce recipient protocol compatibility before acceptance (including mixed fan-out)
and retain explicit downgrade blocks afterward. Existing legacy clients must never
receive raw parts JSON or incompatible state. Include safe lower-authority encoding,
part count, attribution, parent reference and terminal marker.

### 2. Test the real hook and MCP outputs

format_relay's candidate branch rejects every Cc character, including newlines
inserted by _batch_envelope itself. Correct using the existing supported newline,
CR/tab policy plus surrogate rejection. Exercise API claim -> actual formatter ->
publication -> captured hook output, and the corresponding real MCP receive path.
Hand-written one-line mock envelopes do not prove this contract.

Count the final combined output: inter-envelope separators, scope, backlog metadata
and MCP serialization/projection overhead, not only the sum of isolated envelopes.
Clamp caller-provided budgets to service ceilings; keep the oldest non-fitting
batch pending/visibly blocked without discarding its future eligibility.

### 3. Centralize candidate lifecycle checks across ALL entry points

The candidate path is not isolated from legacy turn, status expiry, raw ACK,
receipt ACK and reply. Legacy turn can replace a published generation; reply can
ACK an unpublished one. start_publication checks lease but not message expiry.
Status/ACK expiry paths can erase publication uncertainty by marking expired.

Route eligibility, expiry and ownership transitions through shared checks once a
delivery is candidate-owned, regardless of which router/runtime reaches it.
Cover all permutations of ordinary/candidate/MCP calls, fresh/expired generations,
before/after publication, invalid proof, scope and expiry. Legacy default operation
must still work on truly legacy deliveries.

### 4. Preserve uncertainty and block visibility across turns

Candidate selection filters only pending/claimed. Once a delivery becomes uncertain
or blocked, later queries forget it; the transition loop also continues past an
uncertain predecessor immediately. This breaks FIFO and can report no problem on
later turns. Maintain persistent barriers and truthful counts/reasons for uncertain,
invalid and incompatible predecessors, including later turns and status reads.
A budget-incompatible recipient that upgrades must be able to resume the SAME
delivery rather than permanently strand it in an excluded state.

### 5. Complete admission/reconciliation seams, not just publication

Skipping hook auto-ACK is correct but is not a complete delivery lifecycle.
Specify and implement the candidate operation that accepts verified full-envelope
admission evidence or keeps uncertainty, binding recipient/scope/generation/digest.
Receipt ACK alone must not be rebranded proof of durable hook admission.
A fixture witness can exercise the contract; actual runtime qualification remains G2.
Test positive evidence, ambiguous evidence, stale callbacks, expiry timing and
safe non-admission recovery. No automatic uncertain replay or invented evidence.

## Acceptance for the correction pass

Keep resolved B1 work closed. Add regressions for every reproduction above and a
real six-part send/reply lifecycle through HTTP/hook/MCP with migration, restart,
capacity and backlog cases. Reuse approved design E01–E18 as a checklist: mark
implemented/tested, qualification-only, or genuinely incomplete, rather than
substituting an aggregate passing-test count.

Return one complete corrected candidate checkpoint. No additional architecture
proposal is requested unless the approved contract proves infeasible.
No live migration, installation, public activation, wake coordinator or other
runtime adapter work is authorized by this review.


## Correction review — b3c592d / 80d815d

Verdict: useful corrections, but B2 remains incomplete. Independent rerun: 108
passed, four existing warnings. Actual six-part envelopes now render; the earlier
published-candidate legacy reclaim, pre-publication expiry and unwitnessed ACK/reply
paths have regression coverage. Do not redo those fixes.

Further disposable HTTP probes against old/new routers sharing a temporary DB:

| Probe | Observed | Required |
|---|---|---|
| Multipart send; legacy turn BEFORE any candidate claim | text_v1 delivery containing raw parts JSON | Reject incompatible acceptance; block downgraded reads before exposing payload |
| Same valid admission callback twice | 200 then 409 | Idempotent result for the same verified attempt |
| Publish, expire lease, become uncertain, submit matching positive witness | 409 | Reconcile verified late evidence without replay; retain admission/observation timing |
| Eight 1499-character newline-heavy parts | Send 200, then permanent envelope_exceeds_turn_budget | Validate fully escaped envelope before acceptance |
| Same request key: singleton '["one","two"]', then parts ['one','two'] | Both 200, same message ID | Conflict: payload format belongs to canonical request identity |
| Eight 1500-character parts in current MCP JSON projection | 25,889 characters for a 12,580-character envelope | Bound final MCP output; avoid redundant payload plus envelope |

Reproduction: tests.conftest.client.__wrapped__ and
 tests.test_relay_b2_candidate_e2e.batch_client.__wrapped__ on temporary SQLite,
using their turn/send_parts/publication/admit helpers. For the size case, parts
were ['a\n' * 749 + 'a'] * 8. For late evidence, move lease_expires_at to the past
in the disposable DB, turn again, then repeat admission with the original proof.
No live data changed.

### Consolidated remaining work (existing approved B2 scope)

1. Know recipient capability/budget before send/reply acceptance; check payload
   format on every read, not just claim-row existence. Add explicit disposable
   capability fixtures, mixed-fan-out rejection and downgrade blocks. Legacy
   callers must never receive unclaimed parts_v1 JSON; backlog/status stay truthful.
2. Validate fully rendered size before atomic acceptance, including quoting,
   attribution and recipient scope. Share final-output accounting with hook/MCP.
   MCP currently returns payload AND envelope; hook output omits candidate backlog
   metadata. Test actual output boundaries. Smaller temporary receive budgets may
   block pending work, but globally impossible work must not be accepted.
3. Include payload_format in canonical comparisons for send/reply request retries
   and legacy message-ID retries. Test identical serialized text with different
   formats; do not change the logical request key. Any schema adjustment needs
   explicit migration/compatibility tests as already required.
4. Complete fixture admission/reconciliation: same-proof retry, stale/wrong proof,
   late positive evidence before/after expiry, and safe negative evidence only
   when publication cannot arrive later. Uncertain must be resolvable without
   blind replay. Fixture evidence is not G2 runtime proof; tokens stay private.
5. Exercise REAL MCP receive -> output -> fixture witness -> ACK/reply, and actual
   hook publication/output for multipart. MCP currently only starts publication;
   its advertised receipt ACK/reply rejects until a separate witness. Do not call
   this a completed MCP lifecycle or turn receipt ACK into durable admission proof.
6. Complete remaining deterministic E01-E18 cases in the Work Record, including
   restart, contention/crash, capacity, depth and cleanup. Separate actual-runtime
   G2/G3 and wake-only qualification. The honest partial labels are useful, but
   E02/E07/E08 must not imply the full contract is verified.

Continue under existing approval, without another plan review or per-fix approval
requests. Return one consolidated checkpoint when deterministic implementation and
regressions are complete; stop only for a concrete design contradiction or new
permission requirement. Preserve unrelated working-tree changes. No activation,
install, live migration or wake implementation is authorized by this review.

## Second correction review — 1b52222

112 focused tests independently pass (four existing warnings). The narrow fixes
for legacy turn raw-parts injection, format-aware retry identity, admission retry
and late lease evidence are improvements. This is not B2 acceptance: the preceding
review required shared acceptance/read/output paths and complete deterministic
work, not only fixes for the exact probe inputs.

Remaining reproduced sibling paths, same disposable HTTP fixtures:

- After sending parts ['one','two'], GET status still returns raw JSON in
  deliveries[0].payload although top-level payload is decoded. Before candidate
  claim, legacy turn returns has_more=false, remaining_count=0 despite blocking
  that delivery. Project every status/read path and report the barrier truthfully.
- Publish/admit a parent; reply with ['a\n' * 749 + 'a'] * 8. Reply returns 200;
  recipient turn reports envelope_exceeds_turn_budget. The new preflight exists
  only in send. Use ONE shared acceptance validator for send AND reply, including
  capability/capacity/depth and final rendered bounds; no duplicate policy.
- Real PalliumMcpClient.relay_receive with only HTTP transport bridged to the
  disposable TestClient: max_chars=1000, one 'hello' part, 1740-character final
  JSON after server claim-token removal. Removing duplicate payload helps but
  does not enforce final serialization/metadata bounds. Plan claim/publication
  around actual supported output; do not publish then drop excess output.
- That real MCP receive followed by receipt ACK returns 409 requiring admission
  evidence. This is expected safety before witnessing, NOT a completed usable
  lifecycle. Test actual output -> separate verified fixture witness -> ACK/reply.
  Never fabricate runtime proof or weaken admission checks.

Previously requested capability/mixed-fan-out, safe negative reconciliation,
expiry evidence timestamps, restart/crash/contention, capacity/depth/cleanup and
hook/MCP output/backlog regressions remain deterministic B2, not G2/G3.
Actual runtime proof, wake scheduling and live rollout remain separate gates.

Continue immediately under existing approval. Finish all six numbered items in
the preceding review and the deterministic matrix before another final review
request. Commit internal milestones as useful; they do not need manager approval.
Report a blocker only for a concrete contract contradiction, missing authority or
unavailable dependency. Update WR state to implementation in progress, not a
complete candidate awaiting acceptance. Do not reopen B1 or touch live config,
database or installations.

## In-progress lifecycle evidence — b730e5f / e3ae685

Not another approval gate. Developer continues existing B2 implementation.
Manager reran combined B1/B2/MCP/hook suites at b730e5f: 266 passed, four existing
warnings. Further disposable HTTP/MCP probes:

- Fill 64 pending deliveries, expire their message timestamps, submit fresh work
  without a status/recipient turn: admission rejects at capacity. Reconcile expired
  unexposed work before counting; retain genuinely uncertain exposure.
- Two candidate messages; refuse publication for the first only: real MCP client
  returns the second. Hook publication loop has the same continue behavior. Preserve
  FIFO across publication failures and expose the unpublished suffix as backlog.
- Publish a candidate, move expiry eight days into the past, confirm uncertain,
  then send another message: cleanup makes original status 404. Preserve unresolved
  exposure and reconciliation evidence through cleanup.

These were sent through Relay with exact reproductions. The e3ae685 fresh-router
test reuses the same storage engine, not a database/process restart. Injecting a
busy exception proves error mapping, not real lock contention or rollback. Add
file-backed dispose/reopen and independent-connection contention/fault tests.
Admission records observation time as delivered_at; complete the agreed pre-/post-
expiry admission timing and safe negative reconciliation contract.

Review default max_chars=0/above-ceiling final MCP budgets, legacy compatibility
of unconditional depth limits, and the remaining previously listed matrix items.
No public activation or live-data mutation was performed by this review.

## Consolidated review — cae7016

Independent combined B1/B2/MCP/hook run: 276 passed, four existing warnings.
Accept the corrections for expired capacity, published/uncertain retention,
publication-failure FIFO, file-backed reopen, real independent-provider contention
and legacy depth compatibility. No live activation is approved.

Three bounded contract gaps remain before B2 closure:

1. Actual admission and observation are distinct. Current admission_timing compares
   now with expiry, falsely classifying a late observation as late admission. Keep
   observed_at separate from verified admitted_at; use unknown timing without proof.
   Late observation of pre-expiry admission must not be a violation. Validate
   evidence against the attempt/publication and make retries immutable.
2. Candidate MCP output needs the declared final char/byte ceiling with default zero
   or oversized caller budgets. Reproduction: eight sends, each one 1300-character
   part; default real MCP receive returns 17,119 JSON characters after publication.
   Preserve legacy zero semantics but do not let candidate traffic bypass bounds.
   Plan final projection before publication; preserve FIFO/progress and never drop
   already-published work because a later serialization guard rejects it.
3. Finish the fixture-only safe negative reconciliation contract: verified
   non-admission AND impossible late publication are both required to release the
   same delivery with generation fencing. Ambiguous outcomes remain uncertain.
   Wrong/stale/repeated evidence, expiry and restart must have surface regressions.

Developer received these through Relay; continuation is approved, not a fresh plan
approval gate. Return one closure checkpoint with actual hook/MCP output assertions
and an accurate E-matrix separating implemented, qualification-only and incomplete.
G2/G3 and real runtime proof remain release gates; no migration/install/live changes.

Coordination observation: native queue notifications during a long busy developer
turn remained queued while its progress reports reached the manager. Confirmed
Relay status was pending; after a notification-only app message, the next turn provided a
receipt opportunity. All substantive instructions stayed in Relay; MCP recovery
was used only without hook injection. This is not evidence of automatic wake.

## Executable closure criteria — df894c7

Manager-owned tests/test_relay_b2_architect_acceptance.py now reproduces remaining
contract failures through HTTP and real ASGI-backed MCP. Initial run: three fail,
one ordinary six-part control passes; an eight-part control was then added.

- A 16,375-character accepted hook envelope yields no MCP delivery at default max.
  Acceptance must budget actual supported transport projection; reject impossible
  work atomically, but support ordinary complete six/eight-part batches.
- Identical negative-reconciliation retry returns 409 after first success.
- Deadline after proven non-admission restores uncertain instead of expired because
  old publication metadata still controls lifecycle. Preserve historic evidence,
  but distinguish a closed/reconciled attempt from outstanding exposure.

These tests are intentionally red until the fixes land. Do not weaken assertions
or solve them by lowering the approved public bounds. Private fixture attestations
are not production proof; expired lease alone never fences a late publisher.
The full G2 proof requirement still gates activation. Continue existing approved
implementation, then run these controls plus the combined regressions.

## Final manager patch — 7621ab4

The executable closure criteria above are now green, including repeated terminal
reads and wrong-credential negative retries. Acceptance and MCP emission share the
same JSON projection accounting; accepted complete batches are not stranded by a
transport wrapper. Cleanup retains unresolved publication and its reply ancestors,
while proven non-admission can expire and be removed. Independent combined run:
294 passed, four existing Pydantic warnings; import-boundary check has no violations.
The existing Relay developer is reviewing this final delta read-only. Earlier
findings above are historical evidence, not a claim they remain open after this
patch. Final candidate verdict follows that review.

### Next qualification and rollout sequence (not executed)

1. Close independent candidate review and record exact immutable commit/test evidence.
2. Define a disposable Codex qualification plan before runtime edits/probes: use
   the existing-session queue transport, one shared turn hook, and bounded generic
   payloads. No managed App Server, second payload path, or production DB migration.
3. G1/G2: qualify idle and busy queue turns; read back the FULL attributed envelope,
   ordered parts, terminal marker, session and attempt identity. A transport ACK,
   model paraphrase, receipt ACK or partial transcript does not prove admission.
   Demonstrate stale pre-publication rejection. Already-started publication remains
   uncertain unless a trusted witness proves admission or proves BOTH non-admission
   and impossible late publication; timeout alone never releases it.
4. G3: measure per-turn rendered char/byte bounds and cumulative headroom while
   draining 64 durable deliveries over multiple turns. Cover late arrivals,
   restart, disabled/unavailable wake, regular-turn fallback and no silent gaps.
   Stop visibly if headroom/admission cannot be established; never truncate.
5. Only after those gates: review the live schema inventory and backup/restore
   rehearsal, including any withdrawn prototype tables. Deploy compatible readers
   and explicit migrations before enabling new writers/capabilities. Old/new
   runtime/API/schema combinations must fail closed without breaking legacy mail.
6. Implement/qualify the bounded notification coordinator and actual Codex-to-Codex
   no-ping task/result/review round trip. Update installations only via the approved
   rollout; keep Claude development deferred until the shared contract is stable
   and milestone 1 is genuinely demonstrated. No new permission is inferred here.

### Final result

Relay Dev returned one count-range sizing concern (review message
relay-msg-6a2fcaec5efe4f26853aa56771c2e03b); all other final-delta areas passed.
The manager removed the small-count assumption in favor of SQLite's signed row
count range and verified a real pre-capability 128-item backlog plus a projection
bound assertion. Existing reserved reason-string space meant the reported
overshoot was not independently reproduced; this is a justified conservative
tightening, not an invented production incident. Final combined result: 296
passed, four existing warnings. Candidate review is accepted. No live rollout,
runtime admission/headroom qualification, or automatic wake is claimed.

Coverage boundary: this accepts the reviewed candidate fixes, not every E01-E18
release scenario. The Work Record's partial matrix remains a release obligation,
including dedicated malformed multipart/secret-split, disk-full/keyed-send/alias,
recipient lifecycle, sibling-reply and independent fan-out E2E combinations.
Some shared legacy/B1 behavior is already covered, but that is not a substitute
for candidate-surface assertions. Consolidate the remaining deterministic cases
before release alongside G1-G3 qualification; do not mark the full B2/passive or
wake feature Done merely from the 296-test count.
