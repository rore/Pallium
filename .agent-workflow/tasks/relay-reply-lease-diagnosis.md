<!-- agent-workflow:start -->
**Outcome:** Relay replies do not report an immediately expired claim lease after a valid claim/reclaim unless the lease truly expired, and any observed failure is explained by bounded evidence with a regression fix when reproducible.

**Target:** Pallium Relay.

**Scope:** Diagnose the reported reply failures using existing delivery records, logs, and caller evidence; inspect MCP receive/reply, hook delivery, receipt, claim-lease, and stale-copy handling; if reproducible, apply the smallest shared-boundary fix with focused caller-facing E2E coverage and relevant operator documentation.

**Constraints:** Preserve claim-token secrecy, receipt-based MCP semantics, hook-owned claim/ACK behavior, idempotent reply behavior, delivery provenance, activation approval blocks, and delivery-trace sequencing. Do not mix hook delivery with MCP receive, blindly reclaim, run paid native wake probes, or change wake submission as a workaround.

**Completion criteria:** Each failed attempt is classified as valid expiry, mixed hook/receive race, stale delivery copy, caller misuse, or a reproducible Pallium defect from exact evidence; if defective, a focused regression proves a valid current receipt can reply atomically without immediate false expiry while expired/stale receipts still fail safely; the reporting agent receives the bounded result or a precise list of missing evidence.

**Risk:** High

**Complexity:** Moderate

**Reason:** Relay claim leases, receipt validation, atomic ACK/reply, and persisted delivery state are security- and durability-sensitive contracts spanning MCP, core lifecycle, and storage.

**Discovery:** Initial report says two reply calls returned immediate claim-lease-expired, including after reclaim; the caller then sent a new message. Parent hook replies succeeded shortly beforehand. Exact delivery IDs, timestamps, error bodies, receipt use, and hook-vs-MCP path are requested from `@minimap-dev`; no defect is confirmed yet.

**Material assumptions:** The two failures belong to a claim/receipt path rather than hook-injected reply; exact caller evidence disproves this and changes the diagnosis path. Existing persisted timestamps and logs are sufficient to distinguish expiry from race without executing a new wake; missing correlation evidence disproves this and limits the result to a specific evidence gap. Production code is needed only if the supported receive/reply lifecycle reproduces the failure under current main.

**Plan:** 1. Invoke agent-workflow and record the task/risk before code edits. 2. Collect the exact caller evidence and inspect existing delivery/message state plus service logs without claiming or mutating it. 3. Trace all callers through MCP reply, receipt verification, lease expiry, hook admission, reclaim, and atomic reply/ACK; compare current behavior with tests and recent changes. 4. Classify the incident; stop with a bounded explanation if behavior is correct or evidence is insufficient. 5. Only for a reproducible product defect, update this record, obtain clean-context plan review, then patch the shared lifecycle boundary with the fewest files and add end-to-end coverage through the same MCP/HTTP surface. Target files are conditional: existing Relay MCP server/client, core/storage delivery lifecycle, focused Relay E2E tests, and relevant Relay/operator documentation.

**Verification plan:** When exact incident evidence is available, each attempt shall map to persisted claim, lease, receipt, and transition timestamps -> read-only delivery/status/log correlation. When a valid receipt is used before lease expiry, atomic reply shall succeed once and ACK the source -> focused MCP E2E. When the receipt is expired, stale, duplicated, mixed with hook delivery, or replaced by reclaim, reply shall fail with the documented conflict and preserve state -> focused MCP/hook E2E. Before PR, run affected Relay files, `python -m pytest --lf --lfnf=none -q -n 0`, `python -m pytest tests/ -x -q`, agent-workflow check, and redline check.

**Plan review:** Pending clean-context review if production changes become necessary.

**Approvals:** Approved by user 2026-09-12: "you have blanket approval for all tasks you get from the architect"

**Exceptions:** —

**State:** Blocked
<!-- agent-workflow:end -->

## Implementation

- Work Record created before code inspection or edits. Evidence request sent to `@minimap-dev`; production work is blocked until the incident path is classified.

## Evidence

- Assignment delivery `relay-delivery-2c7c7e1454734b6fa7b20e40ae79d779` reports two immediate lease-expired replies and identifies source message `relay-msg-25555aa3551a4aa983d3b3b03e087d66`; exact failed delivery evidence is pending.

## Result review

- Pending.
