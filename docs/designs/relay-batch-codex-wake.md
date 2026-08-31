# Relay batches and Codex-first wake

Status: design review closed; agreed revisions applied (2026-08-31). Runtime evidence gates G1-G3 remain open before production implementation/enabling wake.
Roadmap: [wake-first Relay](../../roadmap/features/add-wake-first-relay-delivery.md).
Work Record: [design review](../../.agent-workflow/tasks/codex-relay-batch-wake-design.md).

This is the authoritative proposed milestone-1 contract. It supersedes conflicting
state/timeout/PR sequencing rules in the earlier implementation plan and Phase 0
fixtures; those remain historical evidence, not implementation-ready specifications.
No runtime capability or exactly-once guarantee is established by this document.

## 1. Outcome and scope

The existing Codex architect and developer exchange task, result, review and
remediation through Relay without additional human/agent pings. Sending is explicit;
wake is automatic. If wake is unavailable or definitively fails, the recipient's
next regular turn receives the same whole batch. Claude follows, then OpenCode.

Implement atomic multipart submission, bounded whole-batch delivery, safe backlog
progress, retry identities, operational status and MCP/skill guidance together.
Do not add staged open/append/commit batches, file-attachment infrastructure,
new managed runtimes, task assignment, inferred recipients or LLM polling.
A sender need not create an external artifact. Independent sends are independent
batches; a timing debounce or textual "1/6" cannot establish group completeness.

## 2. Public batch and reply contract

Extend the existing send/reply operations; do not create a parallel messaging API.

- New form: parts: non-empty ordered list of strings, plus request_id.
  Existing message/payload text is the legacy one-part form. Exactly one form is
  accepted. One call submits the complete communication, including multipart replies.
- Each batch has one sender, scope, expiry, immutable resolved recipient snapshot,
  and optional parent relationship. No per-part recipient, expiry or ACK.
- Reuse message_id as batch identity and one delivery_id per batch/recipient.
  Existing deliveries become one-part batches; no part-level lifecycle is added.
- Validate ALL parts, total rendering, recipient compatibility, capacity and scope
  before committing anything. Send commits the batch and every recipient delivery
  in one transaction, without adapter calls. No partial success on fan-out admission.
- The commit sequence, not sender timestamps, establishes FIFO for each recipient.
  Store RelayMessageRecord.commit_seq as a unique non-null integer allocated by a
  durable SQLite counter updated inside the send transaction. Never use wall time
  or MAX(remaining rows), which can reuse values after cleanup.
  Claim selection orders by commit_seq, not created_at or random delivery ID.
  Migration assigns old rows a deterministic created_at/message_id order once
  (historical commit order cannot be recovered), then seeds the counter above it.
  E10/E11 assert concurrent commits, equal/backward timestamps, restart and cleanup.
- After commit, payload, ordering, expiry and recipient snapshot cannot change.
  Alias transfers, retries and newly opened sessions never retarget old work.

Idempotency: request_id identifies a logical send or reply, not each attempt.
Scope the key to current sender identity/container and operation kind; a reply also
binds its parent delivery. Persist a unique mapping to the batch in the same
transaction. A same-key retry with the same canonical redacted content, selector,
parent and expiry duration returns the original result, even after alias movement.
A mismatch returns a structured conflict. Retry never extends expiry.
On a request-key uniqueness conflict, compare all canonical redacted request fields: equal returns the original result; any mismatch returns 409 with no new batch or ACK. Payload content/hash is comparison data, never part of the unique request key.
No unredacted payload is stored for fingerprinting. Validate current caller scope
before returning a previous result; do not re-resolve recipients on a valid retry.

Persist RelayRequestRecord with a database UNIQUE constraint over container_ref,
actor_ref, sender_runtime, sender_session_ref, operation_kind, parent_delivery_key
and request_id; parent_delivery_key is non-null (empty for sends), avoiding SQLite
NULL uniqueness gaps. Store message_id plus canonical redacted comparison fields.
The message and its delivery rows are the resolved recipient snapshot, not a fresh
alias lookup. Retain that snapshot and compact result through the retry window,
including after payload cleanup; cleanup must preserve the request tombstone.
The unique insert, batch and recipient snapshot commit together. Concurrent retry
tests assert one result, including alias transfer and cleanup boundaries.

The MCP caller supplies and reuses request_id across a lost tool response; the
client must retain it across its own HTTP retries. Existing legacy sends without
a key remain compatible but do not gain a false retry guarantee. Tool guidance
must warn against retrying those as a new logical send after an unknown outcome.

Replies derive both endpoints from parent delivery_id AND validate the actual
runtime-owned caller is that recipient. Do not trust model-supplied sender IDs as
authentication. Distinct reply request_ids allow multiple legitimate responses;
retrying one returns one response. Legacy replies without request_id retain their
one-reply-per-delivery behavior. Wake/ACK never generates a reply automatically.
Reply creation and receipt-based ACK remain atomic; a rejected reply must not ACK.
Check expiry and claim generation in reply just as in ACK, including sweep races.

## 3. Bounds, rendering and compatibility

Proposed initial policy bounds (not measured runtime guarantees):

Rate and queue bounds limit bursts; reply depth limits linked chains. They do not
prove termination or cap lifetime cost when agents create fresh-send conversations.
Automatic conversation policy is outside this milestone; do not claim otherwise.

| Bound | Proposal |
|---|---|
| Parts per batch | 1–8 |
| Part text | 1–1500 Unicode code points; whitespace-only rejected |
| Fully rendered batch | <=16,384 code points AND <=65,536 UTF-8 bytes |
| One turn | <=8 complete batches AND the same aggregate rendered bounds |
| Fan-out | existing <=25 recipient snapshot |
| Expiry | existing 60 seconds–7 days; default 24 hours |
| Pending admission | <=64 nonterminal deliveries per recipient; reject new submission atomically at capacity |
| Wake starts | <=6 per recipient per minute; one outstanding activation per recipient |
| Reply depth | <=4 edges; siblings do not increase depth, admission/rate limits still apply |

These are explicit bounded starting policies for review. Qualify them with actual
Codex hook/output/model-context headroom before enabling; include all envelopes,
part labels and backlog metadata in accounting. Character/byte budgets are NOT
token measurements. If the runtime cannot guarantee the whole bounded payload
fits, do not advertise batch support at that size. Never lower the contract under
already accepted work without a visible compatibility block/recovery route.

Render one batch envelope containing ID, origin, part count, ordered parts and end
marker. Part content is escaped/encoded as data, cannot forge envelope structure,
and stays lower-authority peer input. Use shared conformance fixtures for Python
and JavaScript code-point/UTF-8 accounting; reject lone surrogates/control characters.
Redact the logical text across part boundaries as well as within parts, mapping
redacted spans back to parts; joining synthetic secret fragments must not bypass
existing redaction policy. Bounds apply before and after redaction/rendering.

Storage proposal: extend RelayMessageRecord with payload_format. Existing rows
default to text_v1; parts_v1 stores canonical redacted parts JSON in the existing
payload column. One codec owns decoding and whole-message projection.
Dispatch validation by payload_format: text_v1 retains core/relay.py's singleton
validator; parts_v1 validates each decoded part against the 1500-code-point limit,
never the serialized array as one singleton. Reject stored JSON over 131072 UTF-8
bytes before decoding; canonical serialization must also fit that ceiling.
Decoded shape, per-part and whole-render limits remain mandatory on every read.
The existing redacted boolean means any part was redacted. Cross-part span mapping
is transient redaction work; store only the redacted parts, not original spans/text. No second
authoritative copy and no database row per part. API v2 responses expose parts,
part_count and a complete text projection; status never truncates into apparent
completeness. Use compact status without payload unless explicitly retrieved.

Registration/receive advertises batch protocol version and safe render budget.
Reject new multipart sends to incompatible recipients before acceptance (including
mixed fan-out); never send an old client raw parts JSON or a partial projection.
Old singleton traffic retains its supported path. If an accepted recipient
downgrades, retain the batch with an explicit compatibility-block reason until
upgrade/expiry; no payload destruction. Installer rollout precedes batch use.
Rollback after batch acceptance cannot mean running an unaware old binary against
new-format rows; disable wake while keeping a batch-aware passive service, or
finish/expire new-format work before software rollback. Additive schema alone does
not make such rollback safe.

## 4. Wake is a notification; delivery uses the regular-turn inbox

Primary proposal: codex queue --thread carries only a bounded, attributed
notification and opaque activation ID, NOT the batch content or a claim secret.
At the next pre-model boundary, the normal integration drains complete batches.
Thus regular user turns and wake turns share the SAME select/claim/render/admit
path. No second payload injection channel competes with hook fallback.

Important feasibility gate: prove that the exact installed Codex sessions execute
that hook for queued turns, including busy-boundary delivery, before implementing
the production adapter. If false, leave wake passive and return the alternative
admission design to review; do not silently resume the old dual-path plan.

After send commits, the durable queue scan notices pending work. A per-recipient
activation reservation coalesces sends; adapter calls occur OUTSIDE SQL transactions.
A regular turn may claim a pending batch whether or not a notification is queued.
The activation reservation never reserves payload ownership. Notification failure
or uncertainty therefore does not prevent regular-turn delivery.
Admission on either path clears the covered work reservation and rechecks remaining
pending work in the same transaction; completion cannot clear a newer reservation.
Before adapter dispatch, compare-and-set validates the reservation generation.
Cancel an obsolete not-yet-dispatched notification. A dispatched/unknown notification
remains separately tracked until consumed or definitively reconciled; admission must
not erase that evidence or authorize another ambiguous queue submission.
New work may use an already queued turn. If its trigger remains uncertain, retain
visible passive fallback rather than silently wedging or duplicating wake attempts.
E09/E10 must cover reserve -> regular admission -> new send, with the old trigger
not dispatched, queued, consumed and unknown, including a late old completion.

Before triggering, recheck pending eligible work and recipient capability.
A user turn may drain it immediately afterward: one harmless empty wake is possible;
never manufacture a reply, ACK unseen content or loop on an empty inbox.
Do not retry an ambiguous non-idempotent queue call. Record the uncertain activation,
reconcile runtime evidence and bound further notifications. A duplicate notification
must not duplicate already-admitted batches; it may still cost a turn, which is
observable and not described as exactly-once activation.

## 5. Batch ownership, admission and failure semantics

Reuse the existing pending/claimed/delivered/expired lifecycle; add an explicit
uncertain delivery outcome plus claim-publication phase/generation where required.
Wake activation state is separate and never appears in the delivery-state enum.

A claim transaction selects complete FIFO batches fitting the turn budget.
It claims the whole per-recipient delivery, records a fresh generation/lease and
the final rendered digest/length. Hook and explicit MCP recovery share this owner.
Before publishing any output, the integration atomically validates ownership and
records publication-start. An expired/replaced owner cannot start publication.
No SQL transaction spans stdout, runtime I/O or model work.

| Delivery condition/event | Required outcome |
|---|---|
| Pending; regular or wake turn claims | One whole-batch claim wins |
| Reserved but publication not started; lease expires | Reclaim safely, invalidate old generation |
| Publication started; ACK/admission missing | uncertain, NOT automatically pending |
| Whole batch admission witnessed for current attempt | delivered; idempotent admission/ACK |
| Wrong recipient/scope/generation/digest | Reject, reveal no batch data |
| Runtime proves non-admission AND old publication cannot arrive later | Release same batch to pending; regular-turn fallback |
| Uncertain outcome without such proof | Keep visible/reconcilable, no blind replay |
| Pending or proven unexposed claim expires | expired; no future submission |
| Expiry during uncertain publication | Keep expired intent plus uncertain exposure; do not claim execution was prevented |
| Late positive evidence of pre-expiry admission | Record admission time and late observation; never resubmit |
| Confirmed post-expiry admission | Record late-admission violation; retain evidence, no replay |
| Delivered then deadline/expiry sweep | Preserve delivered result |

The new batch admission operation binds scope, runtime-owned recipient identity,
delivery ID, claim generation and rendered digest to private capability evidence.
Do not turn existing receipt comparison alone into that proof. MCP recovery uses
receipt-based whole-batch ACK or atomic reply, never raw HTTP/claim-token handling.

An ACK means the agreed integration admission boundary, not that the model read,
understood or acted on the message. Existing hook stdout flush + per-message ACK
is NOT proof of durable model-context admission. Qualification must identify
runtime evidence for the full envelope, or an equivalent guaranteed context-commit
event, and a way to fence/reconcile interrupted publication. A sender marker alone,
a queue response, a model saying "got it", or history absence alone is insufficient
for the failure cases. Positive full-envelope history evidence can prove admission;
negative history evidence cannot rule out delayed publication.

This evidence is an unresolved release gate, not an invented runtime capability.

Evidence gates for slice A:

- G1: capture a queue-origin turn running the installed pre-model claim/render hook
  and admitting the pending batch, including a busy boundary. E14 tests unsupported
  hooks separately from disabled capability, stale transport and permission refusal.
  Failure keeps wake passive; it does not authorize a second injection channel.
- G2 / E08: read back the entire envelope and ordered parts keyed to batch,
  attempt and digest, and demonstrate stale-publication rejection. Partial readback
  is insufficient. No proof means visible uncertainty and no automatic replay,
  not an exactly-once claim. Pallium owns the expiry deadline; runtime timestamps
  alone cannot establish pre/post-expiry admission under clock skew. If time bounds
  straddle expiry, record unknown timing, not a fabricated late-admission violation.
- G3 / E02/E15: measure maximum fully rendered input and cumulative context headroom
  while draining a 64-delivery backlog. Sixty-four is storage capacity, not one
  turn's payload. Enforce both per-turn bounds and safe later-turn headroom; pause
  visibly if safe drain is unavailable. Lower provisional caps before acceptance
  if measurements fail; never truncate accepted batches.
- E17 checks declared part count plus the terminal marker before replying.
  E18 captures both transcripts and asserts zero intervening user prompts or
  surrogate agent/app pings during the automatic exchange.

Until resolved, retain honest at-least-once legacy delivery semantics and never
claim strict no-loss/no-duplicate behavior for new wake/batch release. User-requested
regular-turn fallback remains available after DEFINITIVE non-admission; uncertainty
is not relabeled failure merely to unblock it.

## 6. Backlog, ordering, lifecycle and observability

- Select oldest eligible committed whole batches; stop when the next does not fit
  the REMAINING budget. Do not skip it repeatedly to fit smaller newer work.
- If it cannot fit an EMPTY advertised budget, report compatibility/size block,
  never silently omit it. Deterministically invalid work is quarantined visibly;
  release later work only with a gap/error indication. Uncertain earlier exposure
  blocks dependent ordering until reconciliation; no invented causal guarantees.
- Response metadata: selected batch/delivery IDs, part counts, has_more,
  remaining_count, blocked_count/reasons and current activation outcome.
  Counts are a snapshot, not a promise that no concurrent sender can add work.
- New sends, ACK/admission completion, safe-boundary events and restart scans
  recheck durable pending work. Test enqueue during the last-item/idle transition
  so a lost notification cannot strand mail.
- Remaining backlog starts a subsequent safe wake turn when capability/rate budget
  permits. If wake fails/is passive, it waits for subsequent regular turns. No
  guarantee of autonomous drain when wake is unavailable; no LLM polling.
- Finite rate limits defer rather than discard accepted batches. Rejections at
  admission return capacity/retry-after information. Persistent failures are
  visible; a full queue cannot prevent ACK/status/reconciliation operations.
- Close/project change does not move payloads; aliases resolve only on send.
  Delivered fan-out recipients stay delivered when another fails. Reopen gets a
  new integration generation; old public notifications may run but cannot revive
  stale payload claims or private capabilities.
- Wall-clock expiry is checked on every claim/admit/ACK/reply path, not dependent
  on a status read. Restart/backward/forward-clock cases must not enable stale
  publication. Lease duration alone is never evidence of non-admission.
- Cleanup preserves active/uncertain claims and retry tombstones long enough for
  the documented retry window. Proposed request-id retry window: 7 days after
  batch expiry; cleanup and retries within it must not recreate work.
- Dashboard/status distinguish pending, claimed, delivered, expired, blocked,
  uncertain and notification outcomes; show remaining batches/parts and oldest
  backlog, not just raw part counts. No payloads or private capabilities in logs.
  Status is scoped read-only; uncertain/stalled work is actionable, passive waiting
  alone is not an alert.

## 7. Agent UX is a release contract

Updated MCP descriptions, installed Relay skill and examples must agree:
1. Submit related parts together in ONE send/reply; one text is a singleton batch.
2. State actual limits, units, aggregate-envelope counting and actionable errors.
   Never suggest arbitrary chunking into independent sends as equivalent batching.
3. Reuse request_id and identical arguments for retry; use a new ID for a genuinely
   new communication. An unknown outcome is not permission to recreate a batch.
4. Wake is automatic, regular-turn delivery is fallback. No manual ping command,
   polling loop or sender-selected wake mode is needed.
5. Read the entire attributed batch before responding. For hook-delivered input,
   do not call receive or ACK again. For explicit recovery, receive returns whole
   batches plus opaque receipts; ACK each batch or reply atomically.
6. Address-book lookup is not inbox retrieval. Runtime-owned identity is not
   inferred from visible session names. Reply endpoints come from the parent.
7. Pending/uncertain is not delivered; delivered is not understood. Limits and
   blocked/expired outcomes explain what the agent can safely do next.
8. Wrong arguments return structured field/limit/state errors, never an invitation
   to guess HTTP endpoints. Normal agents need no curl or raw claim token.

One bounded real-agent usability run gets only installed MCP schemas/descriptions
and the skill plus a normal user task. No corrective prompts or hidden recipe.
It must submit a six-part review, retry the same submission, send a separate
follow-up, receive/reply and interpret fallback/status correctly. Record behavior
and cost separately from deterministic transport tests.

## 8. Implementation boundaries and acceptance matrix

First implementation step: invoke agent-workflow with a new risk-classified Work
Record, obtain the required API/persistence/security reviews and human approvals
before guarded edits. Use the existing Codex Relay developer; manager reviews code.
This design-review task authorizes no implementation or live probes.

| Slice | Scope / gate |
|---|---|
| A — evidence | Actual two-session queued-turn hook, full-envelope admission/fencing and transport-size qualification. Bounded evidence, no managed replacement runtime. If infeasible, revise once before code. |
| B — batch + passive path | Schema/codec migration, send/reply request IDs, whole-batch claims, expiry, recovery, compatibility and MCP/skill contracts. Pass regular-turn E2E before wake. |
| C — notification coordinator | Persist-first notification reservation, Codex queue adapter, safe-boundary backlog/restart handling and operational outcomes; reuse B's payload path. |
| D — release | Regression matrix, reviewed code, installed local integrations and actual no-ping two-Codex exchange. Full multi-runtime feature remains active. |

Expected guarded targets: core/relay.py; storage/sqlite_relay.py,
storage/sqlite_schema.py and existing migration mechanism; api/schemas.py,
api/routes.py; app/mcp/server.py and client/context; Codex hook/common/installer;
service lifecycle and dashboard summary. Preserve core/storage dependency boundaries:
runtime adapter composition belongs in the runtime layer, not SDK imports in core.
Claude/OpenCode only need compatibility/passive handling, not wake adapters.

Every applicable row below runs through real HTTP/MCP/hook surfaces and observes
status plus captured actual integration output. Parameterize wake-triggered and
regular-turn paths; fake only the runtime transport, not SQL claims or ACKs.

| ID | Cases and observable assertion |
|---|---|
| E01 | Empty/one/max/over-max parts; whitespace; malformed types; both/neither input forms; no partial rows or wakes on rejection |
| E02 | Exact/over aggregate envelope bytes/code points; maximum identifiers; Unicode/emoji/RTL/surrogates; post-redaction expansion; all parts render completely or reject |
| E03 | Known secret split across parts; forged envelope markers; attribution and lower-authority behavior preserved |
| E04 | Commit crash/disk-full/SQLite contention; lost send response; concurrent same-ID retries; mismatch; alias movement; one batch/snapshot, no duplicate or extended expiry |
| E05 | Cross-scope/actor/recipient; guessed/replayed/stale receipt; close/reopen/project change; no data disclosure or retarget |
| E06 | New reply vs retry, atomic ACK+reply rejection, expired parent claim, sibling replies and depth>2 up to/over bound; no ACK on failure, no wake-generated reply |
| E07 | Six parts together; concurrent claims; regular-vs-wake and recovery races both orderings; one whole-batch owner |
| E08 | Interrupt before/after claim, publication-start, full output, runtime admission and ACK; no automatic uncertain replay; stale publisher fencing |
| E09 | Lost queue response, duplicate notification, empty notification, regular turn wins first; no duplicate admitted batch or manual ping dependency |
| E10 | More than one turn's backlog; large oldest batch; concurrent new send at final ACK/idle transition; FIFO/progress without starvation |
| E11 | Runtime/Pallium restart in each outstanding/admitted window; durable reconciliation, no blind retrigger; backward/forward clock changes |
| E12 | Expiry before claim, during publication/uncertainty, before ACK/reply; late evidence; sweeps and callbacks agree without false non-execution claims |
| E13 | Mixed fan-out eligibility/protocol versions, capacity reached, one recipient fails; atomic acceptance, independent per-recipient completion |
| E14 | Absent/stale/busy/disabled capability, permission refusal, unsupported queued hook; regular-turn fallback gets same complete batch |
| E15 | Burst/rate/depth bounds, compatibility shrink, invalid stored batch, cleanup/retry-window boundaries; visible errors, no silent drops/infinite turns |
| E16 | Installer upgrade/downgrade, legacy singleton/reply compatibility; old integration never sees partial batch/raw encoded payload |
| E17 | Agent-only MCP/skill usability run; six-part review without external artifact, correct retries/status/replies without coaching |
| E18 | Actual architect/developer no-ping exchange plus wake-disabled regular-turn control; per-batch admission evidence and runtime non-steering; no surrogate app pings |

Tests with polling/live harnesses use the repo's slow marking and are run explicitly;
ordinary deterministic tests stay fast. No claim that every conceivable failure is
proven: record tested runtime/version/OS, rejected/blocked cases and residual limits.

## 9. Previous architect findings and review questions

| Finding | Disposition in this revision |
|---|---|
| B1 transaction boundary | Accepted: durable commit, then separate notification dispatcher; assert no adapter call under send transaction. |
| B2 claim/wake race | Accepted root concern; revised solution: notification reservation owns no payload. Both wake and regular turns use one batch claim. Unreserved pending work MUST remain regular-turn eligible. Do not exclude queued notifications from payload selection. |
| B3 one reply per delivery | Replaced restriction with per-logical-reply request_id; preserve legacy behavior, never auto-reply on wake. Test distinct replies versus retries. |
| B4 admission binding | Accepted: new whole-batch admission operation, recipient/generation/digest/capability binding; existing token comparison alone is insufficient. |
| B5 expiry | Accepted expiry/callback consistency; keep wake states separate from delivery enum. Uncertain exposure and late admission need truthful outcomes, not unconditional timeout expiry/fallback. |
| N1–N4 | Reuse existing dedupe style, bound reply traversal, test complete envelopes, treat numeric limits as proposed and qualify them. Current 2400/3 constants are not current receive defaults. |

Independent reviewer: validate minimality and safety of notification-only wake,
whole-batch ownership, uncertainty reconciliation, retry semantics, compatibility,
MCP/skill UX and E01–E18. Distinguish design blockers from bounded evidence gates.
Do not grant implementation readiness while hook/admission/fencing gates lack proof.
Return one consolidated artifact with exact revision, verdict, required corrections
and tests; send its path and short verdict through Relay. No code or live probes.
