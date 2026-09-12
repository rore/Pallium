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

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

- Classified both reported 409 replies as valid expiry from exact claim/reclaim and call-start timestamps; no lease-duration or reclaim code changed.
- Added the missing original-message TTL check to `relay_reply_atomic`, matching ACK semantics: an undelivered claimed delivery becomes `expired`, its claim token is cleared, the transition commits, then the caller receives `409 message has expired`.
- Preserved delivered/idempotent reply behavior so a prompt ACK can safely precede long work and the same receipt can create the one allowed reply later, even after the original TTL and claim lease pass.
- Documented the 60-second MCP claim and ACK-before-long-work flow in MCP descriptions, Relay docs, and the three identical runtime skills. Restored the already-requested takeover exception and kept each skill within its measured budget.
- Added caller-surface E2E coverage for explicit TTL, exact expiry boundary, simultaneous message/lease expiry, persisted and public terminal state, no reply on expiry, and late reply after prompt ACK.
- `apply_patch` failed once with machine-local Windows error 1327; per local instructions, all edits used narrowly scoped deterministic PowerShell replacements instead.

## Evidence

- Incident evidence: first reply began about 140.329 seconds after its lease expired; the reclaim reply began about 6.557 seconds after its new lease expired. A third claim completed normally five seconds after claim. This distinguishes valid expiry from race, stale copy, or immediate-expiry implementation failure.
- Initial focused corrected expiry and guidance tests: `10 passed in 2.57s`; after review-guidance correction: `11 passed in 1.87s`.
- Full suite: `4868 passed, 33 skipped, 2 xfailed in 212.35s`.
- Last-failure command found no cached failures (`5118 deselected`); pytest returned its no-tests-selected status.
- `git diff --check`: clean apart from Git's line-ending notice.
- Import-linter report: zero violations.
- Redline report: `GRAY` advisory for watched storage/MCP and integration files; no red paths, boundary violations, API/schema/security/runtime-config changes, or required checkpoints.

## Result review

- Clean-context Astra review first identified the original-message TTL inconsistency and lease-guidance gap while confirming both incident failures were valid expiry and the transaction design was sound.
- Final Astra review caught and verified correction of a test-order masking risk: persisted expiry is asserted before the public status read can normalize state.
- CodeRabbit then identified that source TTL may precede the 60-second lease. MCP/docs/skills now require action before either deadline while preserving late reply after ACK; focused assertions pass.
- Astra re-reviewed that follow-up and returned `MERGEABLE_FOR_PR: yes` with no remaining correctness, boundary, privacy, transaction, or overengineering findings.