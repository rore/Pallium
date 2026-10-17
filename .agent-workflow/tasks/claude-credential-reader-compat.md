# Claude credential revocation: reader-first compatibility

<!-- agent-workflow:start -->
**Outcome:**
Provide a rollback-compatible reader baseline before modern admission-fenced deferred revocation is enabled.

**Target:**
Claude hook publisher and persistent wake registry; roadmap/features/add-wake-first-relay-delivery.md REL-14, owned by root.

**Scope:**
core/claude_wake.py; integrations/claude-code/hooks/common.py; tests/test_claude_wake_durability.py; tests/test_claude_wake_registration.py; this Work Record.

**Constraints:**
No installed changes, live operations, eager canonical migration, new worker/config/TTL/queue, deadline widening or authority relaxation. Preserve current durable state and inflight reservations; never restore stale canonical backups.

**Completion criteria:**
Reviewed reader-first source, causal isolated RED/GREEN and actual stage1-stage2-stage1 lifecycle evidence, affected validation and root integration.

**Requirement baseline:**
{"source":"root-delegated reader-first staging, direct human all-fixes authorization relayed by root","outcome":"Provide a rollback-compatible reader baseline before modern admission-fenced deferred revocation is enabled.","scope":"core/claude_wake.py; integrations/claude-code/hooks/common.py; tests/test_claude_wake_durability.py; this Work Record.","constraints":"No installed changes, live operations, eager canonical migration, new worker/config/TTL/queue, deadline widening or authority relaxation. Preserve current durable state and inflight reservations; never restore stale canonical backups.","completion_criteria":"Reviewed reader-first source, causal isolated RED/GREEN and actual stage1-stage2-stage1 lifecycle evidence, affected validation and root integration."}

**Behavior changes:**
[{"target":"task-context.scope","classification":"equivalent","before":"core/claude_wake.py; integrations/claude-code/hooks/common.py; tests/test_claude_wake_durability.py; this Work Record.","after":"core/claude_wake.py; integrations/claude-code/hooks/common.py; tests/test_claude_wake_durability.py; tests/test_claude_wake_registration.py; this Work Record.","reason":"Root approved reuse of the previously reviewed real prior-admission fixture correction in the encoded-body-limit node; qualified close requires actual canonical authority. No production expansion or assertion weakening."}]

**Risk:** High

**Complexity:** Moderate

**Reason:**
Persistent authenticated admission and rollback authority cross publisher and registry. Architecture and persistence review required.

**Discovery:**
The old reader rejects modern admission_id rows and may treat revoke notices as unscoped intents. Merely accepting JSON is insufficient: native transitions must preserve modern fences, notice consumption must retain newer pending and inflight authority, and normal credential-loss closes must remain qualified.

**Material assumptions:**
Stage2 rollback targets this Stage1 baseline only. A genuinely new Stage1 registration writes legacy identity None, making prior modern notices obsolete; native-only transitions retain the existing ID. No deferred None notice exists. Legacy publication refusal remains unresolved.

**Plan:**
First invoke Agent Workflow and create/classify this record before code edits (done). Reuse independently reviewed modern reader, exact notice consumer and qualified normal credential-loss close. Disable modern ID minting and deferred publication. Add focused persisted-modern/legacy-write/replacement/inflight regressions. Preserve immutable modern checkpoint 46ebfbf357d97379d61ed2ef7039b71875e32ad0 for a private actual-code Stage1-to-Stage2-to-Stage1 experiment without requiring hosted tests to access Git history. Coordinate the guarded execution slot, run focused RED/GREEN then affected validation, and obtain final independent review. Root owns full/CI/publication/live rollout.

**Verification plan:**
Compatibility -> actual persisted state across reader versions, exact notices and no canonical rewind.
Authority -> newer legacy replacement, pending intent and inflight preservation using real native locks and IO.
Boundaries -> existing affected Claude files, static/workflow checks and independent result review.

**Plan review:**
Agent technical review: /root/architecture_check accepted reader-first staging with qualified normal-close fencing, exact modern notice consumption and no None deferred notices. Root authorizes the isolated implementation, keeping first PR312 deployment independent.

**Approvals:**
Approved by user 2026-10-12: "these are all bugs we should make sure we fix" (direct human message relayed by root, no message ID supplied). Root explicitly approved this isolated reader-first stage; no live approval inferred.

**Exceptions:** —

**State:** Ready for review
<!-- agent-workflow:end -->

## Recovery state

Existing managed codex-enrollment-recovery checkout, branch fix/claude-credential-reader-compat from e2a0034c4270b253154a12e99a5cd4209d4a47b2. Modern reviewed checkpoint remains immutable on fix/claude-credential-revocation. No owned test process or installed change.

## Implementation and focused evidence

Reader and notice consumer reuse the reviewed modern implementation. Accepted new registrations deliberately clear admission identity to None and serialize legacy rows; native transitions preserve loaded IDs. Qualified normal credential-loss capture and competing-intent preservation stay enabled. Deferred publisher and its invocation are absent. The existing encoded-body-limit test establishes real prior HTTP authority and asserts qualified expected identity None for Stage1.

Baseline RED: eight failures and one pass in 1.84s, private e9dd4b8f1b4547d18adf0794e3b3b789, stdout SHA256 42C1EEECF5D433E5C22C4A265104FE5022D1DF9C23B9ECBF0B2E533DA5C809EF. Old reader refuses modern state and cannot transition/replace it; old publisher lacks qualified capture. Candidate core/common bytes restored in finally with exact hashes. All three tracked owned processes drained; guards/stderr empty.

First candidate: eight tracked passes and one private-probe failure in 1.56s, private c70bbe325ced4c5bbfe82a7d31b27e6a, stdout SHA256 A49E857E7E3B9D1E68238D1971C6AA25F88047DB61EA2C9B9F6DCA92643C2B58. The probe called legacy probe() without a delivery, spending authority before the next reload. This was an unintended test setup operation; no production caller uses that method. Root approved non-admitting state_for plus canonical readback instead, preserving the separate actual inflight attempt.

Corrected actual-code Stage1-to-46eb-Stage1 roundtrip: one pass in 0.56s, private 2dd6fae05489423dbf87766a6496db39, stdout SHA256 49A2111F8AEC1FCAE2C70CC8EF16CE196AEC6259AC5EEC52F5926F4E41AC8AEA. Reuse the unchanged eight tracked passes. Each candidate run had empty guards/stderr and three tracked owned identities drained. No installed change or canonical rewind. Stage1 does not fix legacy publication refusal; Stage2 deployment and rollback to this qualified floor remain separate acceptance.

Five affected files: 202 passed in 51.63s, private a9cce959e4dd4251b43e624698bbbd9c, stdout SHA256 4035A62FDA9C546ACBC44C5093B58665B25AE8AB9BB9E6C2E30F35660EFBC469. Guards/stderr empty, all five tracked owned processes drained. Import-linter exited 0; fresh Redline advisory with passed boundaries and actual architecture/persistence reviews. Root accepted the reviewed checkpoint for integration before its one combined full; no duplicate lane full. Evidence preserved in shared build/service-performance-20261012/claude-reader-compat.

## Rollout contract

Stage1 writes legacy canonical records for genuinely new valid registration and publishes no revoke notices. Qualified expected_admission_id=None closes remain readable by the cf558 close path with legacy semantics. Once Stage2 writes modern state, rollback must target qualified Stage1, which understands and consumes that CURRENT state without restoring backups. Native transitions preserve modern IDs; new Stage1 registration deliberately resets identity to None, making old modern notices obsolete while retaining spent inflight authority. No eager rewrite, stale canonical restore or migration framework is used. First PR312 deployment and installed verification remain root-owned; Stage2 is a separate later code activation after the Stage1 floor is actually installed.

## Result review

Agent technical review: /root/architecture_check accepted actual Stage1 source, tracked regression cases, private real-code roundtrip and source-restore runner; root accepted integration conditioned on affected GREEN, now passed.
Reviewed revision: bb393e52a54330ba232eaf62a5dbc6dca8ff3f2a.
Verification adequacy: old-reader causal RED, eight tracked successes, corrected actual version roundtrip and 202 affected passes qualify reader compatibility and unchanged authority fences. This is not global REL14 closure or installed compatibility verification. Root owns coherent combined full/CI and any live rollout.
