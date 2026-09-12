<!-- agent-workflow:start -->
**Outcome:** Relay replies do not report an immediately expired claim lease after a valid claim/reclaim unless the lease truly expired, and any observed failure is explained by bounded evidence with a regression fix when reproducible.

**Target:** Pallium Relay.

**Scope:** Diagnose the reported reply failures; make atomic reply reject an expired original message consistently with MCP ACK; clarify the 60-second MCP receive lease and ACK-before-long-work flow in MCP descriptions, aligned runtime skills, and Relay documentation; add focused caller-facing E2E and guidance assertions.

**Constraints:** Preserve claim-token secrecy, receipt-based MCP semantics, hook-owned claim/ACK behavior, idempotent reply behavior, delivery provenance, activation approval blocks, and delivery-trace sequencing. Do not mix hook delivery with MCP receive, blindly reclaim, run paid native wake probes, or change wake submission as a workaround.

**Completion criteria:** The reported attempts are classified from exact evidence; atomic reply rejects an original message whose TTL elapsed after claim, marks its delivery expired, and creates no reply; valid live-claim and delivered-idempotent reply behavior stays unchanged; MCP callers are told to ACK within the returned 60-second lease before long work and can reply later with the same receipt; the reporting agent receives the bounded result.

**Risk:** High

**Complexity:** Moderate

**Reason:** Relay claim leases, receipt validation, atomic ACK/reply, and persisted delivery state are security- and durability-sensitive contracts spanning MCP, core lifecycle, and storage.

**Discovery:** Exact evidence identifies delivery `relay-delivery-3a15d973edcb4a05be478164a3a4a375` from message `relay-msg-1224ef38d5104b7e8181fc753a6020b6`, obtained through MCP receive rather than hook injection. Claim 1 ran at 11:56:20.023134Z and expired at 11:57:20.023134Z; reply began at 11:59:40.352Z with its receipt, about 140 seconds after expiry. Reclaim ran at 11:59:45.700894Z, returned a new receipt, and expired at 12:00:45.700894Z; reply began at 12:00:52.258Z, about 6.56 seconds after expiry. No intervening hook, receive, or user turn occurred in either claim window. Both 409 responses exactly reported `claim lease has expired`. A later third claim at 12:03:54.185344Z was delivered at 12:03:59.394422Z; attempts is 3. Current main fixes the claim lease at 60 seconds, rejects reply/ACK at or after the deadline, makes expired claims reclaimable, and has focused tests for valid atomic reply, expired redelivery, and stale-receipt rejection.

**Material assumptions:** Persisted claim/expiry/delivery timestamps and the caller's exact tool timing are sufficient to classify both failures without a new wake probe; contradictory server-clock or receipt-generation evidence would disprove this. The current 60-second lease contract is intentional correctness behavior; architecture or design evidence that supported MCP work must hold an exclusive claim throughout arbitrarily long agent execution would disprove this and require re-planning. Production code is required only for the independently found original-message TTL inconsistency and bounded lease guidance; no claim-lease implementation change is warranted by this incident.

**Plan:** 1. Invoke agent-workflow and record the task/risk before code edits (completed). 2. Collect and correlate exact caller and persisted evidence (completed). 3. Add an HTTP E2E that claims an explicit-TTL message while live, advances past the message TTL but not the claim lease, and asserts reply returns 409, expires the source delivery, and creates no reply. 4. In `storage/sqlite_relay.py`, mirror `relay_ack_by_receipt` by committing the expired source state before returning `message has expired`; preserve delivered/idempotent behavior. 5. Add concise lease-safe instructions to MCP receive/reply/ACK descriptions, all three identical runtime skills, and `docs/agent-relay.md`; assert tool wording, skill parity/budget, and the ACK-then-late-reply flow. 6. Run focused Relay/guidance tests, affected subsystem files, last-failure, full tests once, workflow/redline checks, and independent result review. Stop and re-plan if the fix requires schema, API shape, lease duration, wake submission, or activation/trace changes.

**Verification plan:** When the exact incident timeline is correlated, both reported calls shall be shown to start after their returned claim deadlines -> persisted delivery status plus caller tool timestamps. When original message TTL expires during a still-live claim, reply shall return `409 message has expired`, persist source delivery `expired`, and create no reply -> focused HTTP E2E. When a live claim replies or a promptly ACKed delivery replies later, atomic and delayed reply shall succeed once with existing idempotence -> focused MCP lifecycle E2E. Guidance shall state the 60-second lease/ACK-before-long-work rule identically and stay within measured budgets -> MCP description and guidance-budget tests. Before PR, run affected Relay files, `python -m pytest --lf --lfnf=none -q -n 0`, `python -m pytest tests/ -x -q`, agent-workflow check, and redline check.

**Plan review:** Clean-context Astra review `reply_lease_result_review` confirms both incident failures are valid expiry, finds P2 original-message TTL inconsistency in atomic reply and P2 lease-guidance gap, recommends the focused HTTP regression/minimal fix, and finds no basis for a lease implementation change.

**Approvals:** Approved by user 2026-09-12: "you have blanket approval for all tasks you get from the architect"

**Exceptions:** —

**State:** Ready to implement
<!-- agent-workflow:end -->

## Implementation

- Work Record created before code inspection or edits. Exact caller evidence and persisted delivery state classify both reported failures as valid lease expiry; no production code has changed.
- Focused current-main tests for valid atomic reply, expired redelivery, and stale-receipt rejection pass.
- Clean-context review confirmed the incident is valid expiry and found a separate atomic-reply message-TTL inconsistency plus a lease-guidance gap. Plan updated and approved before production edits.

## Evidence

- Caller evidence reply at 12:39:12Z supplies exact delivery, receipt generations, claim/expiry timestamps, tool-call timing, and absence of intervening claimers. Both reply calls began after their returned lease deadlines.
- Current persisted state shows the same delivery claimed a third time at 12:03:54.185344Z and delivered at 12:03:59.394422Z with `attempts=3`, proving ordinary recovery completed.
- `tests/test_relay_mcp_lifecycle.py::{test_lease_expiry_causes_redelivery,test_atomic_reply_from_claimed_state,test_mcp_ack_stale_receipt_returns_409}`: 3 passed in 1.85s.
- Independent review found `relay_reply_atomic` omits the original-message expiry check present in `relay_ack_by_receipt`; current reply tests cover claim expiry but not message TTL expiry.

## Result review

- Pending.
