# B1 bounded implementation review — 2026-08-31

Verdict: CHANGES REQUIRED. Review of the uncommitted B1 diff over ba843e3.
Scope: schema/codec/request transactions only; B2/C and runtime/config edits remain deferred.
Reviewed by the coordinating architect, independently of the plan reviewer.

## Evidence

The existing HTTP Relay E2E and MCP lifecycle suites pass: 53 tests, four existing
Pydantic warnings. No new B1 tests are present in this diff. Passing legacy tests
does not verify the new persistence, retry, migration or compatibility contract.
Independent probes used disposable databases, not the installed service.

## Required corrections (one consolidated pass)

1. **P1 — Reject public multipart acceptance until delivery support exists.**
   api/schemas.py accepts parts without request_id; core/relay.py persists them.
   storage/sqlite_relay.py excludes every parts_v1 row from turn eligibility.
   HTTP reproduction: register sender and receiver, POST /relay/messages with
   parts=["first","second"] and no request_id, then POST /relay/turn as receiver.
   Actual: send 200; zero deliveries, has_more=false, remaining_count=0 despite
   pending accepted work. This is not a compatibility gate.
   For B1 keep the codec/storage groundwork but reject unsupported public parts
   before persistence/ACK (send AND reply). Require the new form's request_id.
   Leave capability negotiation/full render/publication implementation to B2.
   Test rejection leaves no message/request/delivery and never ACKs a parent.

2. **P1 — Serialize reply sequence allocation and retry decisions.**
   relay_send uses _begin_immediate, but relay_reply_atomic uses _with_retry and
   reads/increments the counter without acquiring equivalent write ownership.
   Independent reproduction: two delivered parents; two concurrent keyed replies;
   barrier after SELECT relay_commit_counters forces both to read the same value.
   Actual: one succeeds; one raises IntegrityError: UNIQUE constraint failed:
   relay_messages.commit_seq. Distinct legitimate replies must both succeed.
   Use the established bounded write-transaction mechanism for the complete
   reply check/create/ACK transaction. Test parallel distinct replies, same-key
   retries, same-key mismatches, and send-vs-reply; no leaked IntegrityError,
   duplicate rows, lost counter updates or partial parent ACK.

3. **P1 — Preserve legacy reply IDs across upgrade.**
   core/relay.py now hashes scope + parent + empty request even for no-key replies,
   replacing the old sha256(delivery_id). A persisted old reply is not found.
   HTTP reproduction with an old-format persisted reply: retry the same no-key
   reply against its delivered parent. Actual: 200 with a different ID; two reply
   messages now reference the parent. Keep the exact old derivation when no key
   is supplied, scoped new derivation for keyed replies. Test actual old-format
   upgrade/reopen, identical retry, changed-content conflict and two keyed replies.

4. **P1 — Make migration DDL/backfill/counter transaction real on SQLite.**
   engine.begin() alone does not BEGIN before DDL with this driver's transaction
   mode. Probe: legacy relay_messages table; fail immediately before INSERT into
   relay_commit_counters. After rollback payload_format/commit_seq columns and
   both new tables remain, while the legacy sequence is still 0.
   Establish an explicit SQLite transaction before migration DDL (using the
   existing locking conventions). Cover rollback at DDL/backfill/seed/index
   boundaries, reopen/recovery, fresh DB, legacy order, concurrent initialization,
   and cleanup followed by new allocation. Do not rely solely on a happy reopen.

5. **P2 — Complete the promised request tombstone contract.**
   RelayRequestRecord stores another full payload but no retention deadline or
   compact immutable recipient/result snapshot. Retry requires the message row
   and raises "request retry result has expired" if that row was cleaned up.
   The approved contract retains replayable result/snapshot through seven days
   after batch expiry, including payload cleanup. Implement bounded retention and
   result recovery, or keep this unfinished path unexposed until completed; do
   not claim the current rows satisfy tombstone/cleanup acceptance.
   Verify alias movement, cleanup inside/outside the retry window, unchanged
   expiry and canonical-field mismatch. No second indefinite payload copy.

6. **P1 verification gate — Add new-contract tests before re-review.**
   Cover the cases above plus input boundaries (including Unicode, invalid types,
   missing key and both/neither forms), codec roundtrip/malformed storage,
   split-secret redaction, cross-scope message-ID collision (must remain a scoped
   rejection, not an INSERT IntegrityError), and rejected reply with no ACK.
   Use HTTP/read-path E2E for public contracts; disposable SQLite fault/concurrency
   tests for persistence seams. Persist the reproducers as regressions.
   Record exact commands/results and update the Work Record before requesting
   one consolidated re-review. Do not submit legacy-only test evidence again.

## Scope discipline

No new architecture review cycle is needed for these corrections: they enforce
the approved B1 plan. Do not implement B2/C to solve item 1; fail closed at the
public surface now. Preserve unrelated uv.lock. Avoid broad formatting rewrites.
The HTTP reproduction completed successfully but its temporary-directory cleanup
hit a Windows open-handle error; neither the live database nor service was touched.
The migration and concurrent-reply probes exited successfully.


## Withdrawal and live mixed-version incident

The developer withdrew the uncommitted B1 code after a Windows replacement
corrupted four source files. Independent git status confirms those files match
branch base. The review remains a regression checklist, not implemented B1 code.

The live reply failed at 13:43:33 UTC with UNIQUE constraint failed:
relay_messages.commit_seq. The old API INSERT omitted the new column, whose
persisted default was 0. Read-only inspection found 205 text_v1 messages, zero
request records and the B1 unique index in the live DB. The failed reply was
not committed. This is a mixed-version compatibility incident, not a lost ACK.

A supervised processor restarted at 13:26:30 UTC while B1 source was present.
That is the likely migration entry point, not a proven process-level trace.
No intentional B1 deployment/service restart occurred. Source rollback alone
cannot undo a schema change performed by another process.

Recovery: completed a SQLite backup (quick_check=ok). Under a bounded write
transaction, revalidated legacy-only data and zero requests, then removed ONLY
uq_relay_messages_commit_seq. Preserved all 205 messages, added columns and
counter records. A new live Relay send succeeded; health/ingestion were ok and
no ingestion work was pending. No service restart or payload deletion was used.
The developer reported a successful single confirmation reply afterward.

Additional gate: test an old writer against upgraded schema, a new worker
starting alongside an old API, and rollback before/after new-format use.
Unmerged source initialization must not silently break the installed service.
The next B1 attempt needs a safe mixed-version migration/activation approach
before guarded edits, disposable test DBs and bounded source edits. No batch
support is approved. This addendum used the documented exact-file fallback
after apply_patch failed with Windows sandbox error 1327.

## Consolidated rebuilt B1 review — 2026-08-31

Verdict: CHANGES REQUIRED; not complete B1. Independently reran the six reported
suites: 213 passed, four existing warnings. Migration foundation remains approved
and uncalled. The following are contract issues, not requests for a new design cycle.

1. **Retry retention must preserve reply dependencies.** The new global cleanup
   deletes a parent message/delivery based solely on its own expiry. Reply retry
   first loads that parent, even if the reply is still retained.
   HTTP reproduction: deliver a parent with 60-second expiry; create a keyed reply
   with seven-day expiry. Advance to parent expiry + seven days + one second;
   an unrelated successful send commits cleanup. Reply status is still 200,
   but retrying the identical keyed reply returns 404. This was reproduced on
   disposable SQLite. Preserve the minimal parent/receipt/routing evidence through
   every dependent retry window, or make retry resolution independent of deleted
   parents while still validating caller scope/receipt. Cover a chain deeper than
   two, differing expiries, cleanup races and eventual release of retained ancestors.

2. **Do not recycle message identity after request retention.** The new retention
   test explicitly expects the same message_id with a fresh delivery after cleanup.
   A previously accepted message ID must not come to identify a different payload
   or recipient snapshot: retained replies, status links and agent context still
   refer to it. Request-key reuse after the window must either be safely rejected
   under a documented contract or create a fresh message ID through a persisted
   scoped request mapping. The approved request-record design already separates
   these identities; a deterministic message ID alone is not an equivalent
   replacement. Test a retained reply pointing at the old send, then key reuse
   with changed content/alias; the old reference must never retarget.

3. **New MCP versus old API must fail closed for keyed operations.** The prior
   HTTP models silently ignore unknown request_id fields. The new client forwards
   that field without checking support; an older API can accept repeated sends
   as separate messages while the caller believes retries are protected.
   Keep the new client surface unexposed until coordinated activation, or add a
   bounded capability check that rejects unsupported keyed operations before POST.
   Test an old-server contract, not just request forwarding mocks. Source checkout
   sharing means a fresh MCP process can load new code before the API upgrades.
   Do not blindly replay a keyed write after an ambiguous network response.

4. **Finish or explicitly defer the remaining B1 deliverables.** No canonical
   parts codec/persisted format exists in the rebuilt source. Multipart public
   rejection is correct until B2, but is not implementation of B1's codec.
   The approved scoped request-record/snapshot design has also been replaced
   without demonstrating equivalent lifecycle semantics (items 1–2).
   Finish the internal codec with bounds, malformed-storage and cross-part
   redaction tests, keeping its public acceptance disabled. Maintain the original
   B1/B2 boundary; no whole-batch delivery or wake work is requested here.

5. **Align exposed tool guidance with keyed behavior.** The MCP reply docstring
   still says "Reply once" and neither tool explains request_id retry versus a
   new logical message, actual limits or retry window. If keyed tools remain
   exposed, update descriptions and the source skill/examples together; otherwise
   defer their exposure. This is the user-requested agent UX contract.

The old-writer sequence fix and immediate reply transaction are accepted.
Do not roll them back or seek another broad architecture approval. Apply one
bounded correction pass with regressions, retain the startup/deployment block,
and report incomplete gates honestly. Preserve unrelated uv.lock.

## B1 foundation acceptance — 2026-08-31

APPROVED as an internal, unactivated foundation. The scoped request mapping,
fresh post-retention message identities, retained reply ancestry, MCP keyed-call
fail-closed boundary, migration shape validation and redacted ordered preparation
resolve the consolidated review findings. Startup has no migration caller.

The manager directly corrected two small codec issues to avoid another review
round: preserve the existing multiline/tab/CR payload contract and map malformed
stored surrogates to RelayCodecError. Three regression cases cover those changes.
apply_patch failed with Windows sandbox error 1327; exact-file deterministic
replacement was used only for the codec/tests and this acceptance note.

Independent focused verification after the manager correction: 229 passed, four
existing Pydantic warnings, across codec, migration, HTTP Relay E2E, MCP lifecycle,
MCP client/server/tools. git diff --check passed. No service restart, installation
or live migration occurred. No lint result is claimed.

This approval is not batch delivery, Codex wake, G2/G3, or release acceptance.
Public multipart and keyed MCP remain disabled. The recovered local request-table
shape will intentionally fail migration validation; coordinated deployment must
address that explicitly on a backup first, never delete it implicitly at startup.
Full attributed-envelope budgets and publication/admission semantics remain B2.

Next: commit reviewed B1 source/tests/Work Record, preserve unrelated uv.lock,
and prepare one bounded B2 execution checkpoint against the approved design.
Keep startup/installation/live DB changes blocked. Claude wake remains deferred
until stable shared delivery and actual Codex no-ping/fallback E2E evidence.
