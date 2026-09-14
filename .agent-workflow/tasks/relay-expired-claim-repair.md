<!-- agent-workflow:start -->
**Outcome:** A reviewed obsolete Relay delivery whose claim lease expired can be safely suppressed by the existing offline endpoint-repair workflow instead of remaining permanently stranded.

**Target:** Pallium Relay.

**Scope:** Extend the offline repair manifest/apply path for expired claimed source deliveries; focused E2E tests; operator docs and RW-029 roadmap alignment.

**Constraints:** Service must be stopped; every delivery needs an explicit disposition and exact preimage; expired claims may only be suppressed, never adopted; active or missing-lease claims fail closed; no API, schema, automatic cleanup, endpoint merge, or live-service mutation.

**Completion criteria:** Dry-run and apply accept an unexpired message with a source claim whose finite lease is expired only when disposition is `suppress`; active/missing-lease claims and any expired-claim `adopt` refuse without mutation; manifest output exposes no raw claim token; identical apply remains idempotent; full tests and CI pass.

**Risk:** Elevated

**Complexity:** Moderate

**Reason:** Clean-context redline classification is GRAY because the app repair tool and Relay storage transaction are watch/otherwise unclassified paths. No red/API/schema/security/config surface or boundary violation is involved.

**Discovery:** Live installed evidence showed one four-day-expired claim stranded on an obsolete duplicate endpoint. The existing repair tool accepts only `pending` rows and refuses every `claimed` row, while Relay already treats finite expired claims as reclaimable. The tool prints complete manifests, so supporting claimed rows also requires a non-secret claim-token fingerprint. Existing stopped-service lock, exact database/endpoint/message/delivery preimages, complete inventory, wake evidence, digest acknowledgement, transaction, and repair ledger remain the governing safeguards.

**Material assumptions:** A finite `lease_expires_at <= now` makes a claim expired independently of message TTL; disproved by existing Relay lease semantics or tests, in which case return to planning. Explicit operator `suppress` means the work is reviewed as completed, duplicate, or deliberately abandoned; if adoption is required, keep refusing until authoritative Codex reservation/history evidence exists.

**Plan:** Reuse the existing offline repair transaction. Version new manifests so delivery preimages store a domain-separated SHA-256 claim-token fingerprint instead of the raw token or receipt-equivalent plain hash. Include live `pending` rows plus `claimed` rows with a finite expired lease in the complete source inventory. Reject expired-claim adoption in both dry-run construction and transactional apply; reject active/missing/malformed leases. On explicit suppression, preserve delivery history while clearing live claim token/lease fields. Keep version 1 ledger overlap detection and committed replay compatible. Update focused E2E/subprocess boundaries, operator docs, and RW-029. Target files: `app/tools/relay_endpoint_repair.py`, `storage/sqlite_relay.py`, `tests/test_relay_endpoint_repair_e2e.py`, `docs/context/operations.md`, `roadmap/features/add-wake-first-relay-delivery.md`. Stop and re-plan if this requires an API/schema change, automatic disposition, or active-claim handling.

**Verification plan:** Expired claimed suppress succeeds and is terminal across repair/read paths → focused E2E. Expired claimed adopt and active/missing-lease claims refuse with byte-for-byte state unchanged → focused E2E. Manifest contains fingerprint and no raw token → dry-run/subprocess assertion. Pending adopt/suppress and replay behavior remain compatible → existing endpoint-repair file. Whole repository contract remains clean → agent-workflow/redline checks, full `tests/ -x -q`, and PR CI.

**Plan review:** Approved by clean-context Astra review `/root/expired_claim_plan_review`; no blockers, with domain-separated token fingerprint and mixed-batch rollback/version-compatibility checks required.

**Approvals:** Not required at this risk level.

**Exceptions:** —

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

- Established the live failure: one obsolete split-identity delivery remains `claimed` with a lease expired by four days, while the guarded repair workflow rejects all claimed source work.
- Clean-context redline classification: GRAY / Elevated, no checkpoint or boundary finding.
- Reused the stopped-service manifest/transaction/ledger path. Version 2 adds finite expired claims to the complete inventory only for explicit suppression, fingerprints rather than exposes claim tokens, and clears token/lease state after preserving claim history.
- SQLite persists canonical UTC timestamps without an offset; the dry-run reader interprets those values as UTC while still rejecting missing or unparsable leases.
- A cheaper implementation delegate was stopped after machine-local deterministic-write corruption; the root agent discarded that output, reimplemented the bounded diff, and reviewed every changed line.

## Evidence

- Installed Relay summary after service restart: 53 pending, 32 claimable in duplicate-identity groups; exact stale claim had attempts=1 and an expired 60-second lease.
- Focused caller-surface E2E: `29 passed` in `tests/test_relay_endpoint_repair_e2e.py`, including lease equality, active/missing/malformed refusal, suppress-only enforcement in builder and apply, raw-token absence from stdout/manifest/ledger, terminal HTTP/ACK/reply/wake behavior, mixed-batch rollback, and version-1 replay/overlap compatibility.
- Affected Relay subsystem suite: 237 passed. Full repository suite: 4987 passed, 34 skipped, 2 xfailed in 216.75 seconds. An earlier unrelated xdist-only Claude session-pin failure passed immediately in isolation; the complete rerun was green.

## Plan review

Approved for implementation by clean-context Astra review /root/expired_claim_plan_review. The reviewer confirmed the lease_expires_at <= now boundary and separate message TTL contract, and required fail-closed active/missing/malformed leases; apply-time expiry/preimage recheck; equality and mixed-batch rollback; v1 ledger overlap/replay compatibility; a domain-separated fingerprint that cannot reproduce the existing receipt; token absence from stdout, manifest, and ledger; and terminal HTTP/ACK/reply/wake verification.

- Machine-local edit fallback: apply_patch failed with Windows CreateProcessWithLogonW error 1327; used an exact named-file deterministic replacement per AGENTS.md.

## Result review

Clean-context Astra review `/root/expired_claim_result_review` found no production defect. Its initial P2 test-evidence finding was addressed with six subprocess CLI refusal cases and a true expired-claim mixed-batch rollback; re-review returned no findings.
