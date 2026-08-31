# B2 candidate review — b06aa89 — 2026-08-31

Verdict: CHANGES REQUIRED. This is not complete B2; G2/G3 qualification and
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
