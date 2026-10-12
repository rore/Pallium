# Exact Claude credential-loss revocation (REL-14)

<!-- agent-workflow:start -->
**Outcome:**
For admissions created by a successful current registration, credential loss can publish exact deferred revocation after bounded intent publication refusal. Recover it through the existing reconciler without revoking sibling, newer valid, or unresolved inflight authority. The initial REL-14 objective remains broader: legacy publication-refusal recovery is explicitly not closed by this slice.

**Target:**
Claude hook publisher and persistent native wake registry; canonical roadmap roadmap/features/add-wake-first-relay-delivery.md REL-14 (root owns roadmap reconciliation).

**Scope:**
core/claude_wake.py; integrations/claude-code/hooks/common.py; tests/test_claude_wake_registration.py; tests/test_claude_wake_durability.py; tests/test_claude_wake_instance_isolation.py; this Work Record.

**Constraints:**
No installed environment changes, live sends, new worker/TTL/global queue, identity relaxation, timeout widening, database schema/config changes, or changes to the root-owned PR312 checkout. Preserve existing exact intent authority and unresolved wake_inflight reservations. Keep completed recovery commits immutable.

**Completion criteria:**
Real native publisher-lock refusal reproduces surviving old admission; after release and successful durable writes the existing reconciler revokes exactly that modern admission. Real HTTP status and native-attempt witnesses prove sibling/new-valid/inflight safety, restart replay/ABA safety, and failure handling. Unknown capture refuses rather than downgrading to an unqualified close. Legacy load stays read-only; normal verified-legacy close is qualified against modern replacement but has no invented deferred ID. Persistent disk failure retains the notice and reports failure without promising immediate revocation. Independent source/result review and required isolated validation pass before root publication/deployment; global REL-14 remains open for the legacy limit.

**Requirement baseline:**
{"source":"root-delegated REL14 continuation, direct human all-tracked-fixes authorization relayed by root","outcome":"Credential loss cannot leave a previously admitted idle Claude endpoint indefinitely eligible after bounded publication refusal","scope":"core/claude_wake.py; integrations/claude-code/hooks/common.py; existing Claude registration/durability/instance-isolation tests; this record","constraints":"No installed changes, new worker/TTL/global queue, authority relaxation, or deadline widening; preserve sibling/new-valid/inflight admissions","completion_criteria":"Causal real-lock RED/GREEN, exact reconciler recovery and safety E2E, independent review, isolated validation"}

**Risk:** High

**Complexity:** Moderate

**Reason:**
Persistent capability and authenticated revocation boundaries require architecture/persistence review. Stable admission identity, competing intent precedence, and restart compatibility span publisher and registry.

**Discovery:**
The publisher returns False before HTTP when its 100ms native intent lock cannot be acquired. Invalid-credential registration ignores close success and returns False. Persistent registrations have no TTL; old idle remains ready without a successfully communicated close. These semantics are byte-identical between cf558114 and PR312; the historical CI failure stage remains unknown. Current complete run passed all nine credential variants with close HTTP204.

**Material assumptions:**
A registration intent UUID can serve as immutable admission identity across native transitions. Current generation cannot: transitions change it and an empty canonical resets its high-water. No exclusive legacy canonical writer is proven: legacy loading MUST remain read-only. Legacy publication-refusal recovery remains unresolved until safe adoption under reviewed ownership; do not close REL-14 globally. Deferred notices must not overwrite/delete a competing valid scoped intent. If any assumption fails, stop source edits and revise the protocol with the reviewer.

**Plan:**
First invoke Agent Workflow and classify/create this record before source/test edits (done). Obtain exact technical plan review (done). Real-lock causal RED before production edits (done). Stable admission_id comes from accepted registration intent_id and survives transitions; old rows load without mutation and acquire identity only through a normal successful registration. Invalid-credential revocation captures this identity BEFORE ordinary publication; normal and fallback consumption both compare it under the existing scope lock. On ordinary close-intent publication refusal, publish a credential-free, exact-scope/admission notice in existing intent storage. The existing reconciler consumes it under the scoped lock; newer valid intents take precedence, changed/absent admissions make it obsolete, and inflight reservations keep current close semantics. No identity means no invented fallback authority; explicit and legacy close paths retain current behavior. Run focused GREEN and safety races, affected existing files, static/workflow checks, and result review; root owns integration/full/release. Legacy global closure is a separate unresolved acceptance condition.

**Verification plan:**
Real publisher lock held through invalid credentials: False, no close HTTP, old ready on baseline; release and existing reconciler produce exact revocation on candidate. Cover sibling scope, newer accepted/pending valid intent, busy/native state transitions, inflight reservation, malformed/unbound publication, I/O failures, replay, legacy load, and restart ABA. Preserve all real locks/deadlines and public HTTP/native witnesses; use private database/state and inert transport only. Coordinate the shared execution slot before runs. Text/forced mechanisms do not attribute historical CI.

**Plan review:**
Agent technical plan review: /root/architecture_check approves stable admission identity, pre-capture before the normal write wait, per-admission deterministic notice, newer-intent precedence and retained inflight semantics. Root resolves credential-loss revocation fencing for BOTH normal and deferred paths where a stable identity exists; explicit SessionEnd/legacy close linearization stays unchanged. Reviewer rejected eager legacy upgrade without exclusive writer proof; root accepted read-only legacy load and adoption through normal registration, with legacy refusal remaining open. Root authorizes source implementation after real-lock causal RED. No live format upgrade is authorized.

**Approvals:**
Approved by user 2026-10-12 (direct messages relayed by root; no message ID supplied): "these are all bugs we should make sure we fix" and "so we should track this list - this all should be fixed. also, see if there are things here we can parallalize with a second developer". Root explicitly assigns isolated REL14 continuation. No live approval inferred.

**Exceptions:** —

**State:** Ready for review
<!-- agent-workflow:end -->

## Recovery state

Isolated managed checkout codex-enrollment-recovery/Pallium; branch fix/claude-credential-revocation from clean e2a0034c4270b253154a12e99a5cd4209d4a47b2. Prior completed commits/evidence retained. Source/tests frozen and accepted for root integration after causal RED, focused GREEN, affected evidence and fixture-only correction. No active test process or installed action. Root owns combined selector/full/CI/release; no separate full or PR is authorized. Captured admission comparison also qualifies the normal invalid-credential close intent, while explicit close callers retain compatibility. Unknown/malformed canonical capture refuses without inventing authority.

## Compatibility requiring review

Adding a canonical admission field must explicitly accept legacy records. Older binaries reject unknown canonical fields; any eventual live rollback must restore the backed-up compatible wake state or use a reviewed forward fix. Root owns backup/rollout approval. No database migration or new integration setting is proposed.

## Causal evidence

Baseline e2a0034c real registration helper + loopback HTTP (not the full Stop hook): private run 5c1448a7bd76419ab0bdc929a74a1c4e, one failure in 2.24s at final ready rather than unknown after real publisher lock refusal, release, and existing recovery call. Setup/admissions, False return, no close HTTP and no ordinary intent passed. stdout SHA256 B8D97F5E02BFF93816E588C83A7FE586454963EECF52F2D885BDFDEBF7503FD4; guards/stderr empty; all three tracked owned processes drained. This proves a mechanism, not the historical CI stage.

Reviewed candidate: 22 passed in 4.85s, private a62f508da0934c83bae8706d722433cf; stdout SHA256 36AC3CB5D9FE78B4D25A1D86929217FC4D9855EC5252B4449207F75EEA7B5B12, guards/stderr empty and three tracked identities drained. Actual HTTP replacement during normal publication stays ready; pending/newer/inflight/restart, unknown-capture, legacy read-only parsing and I/O replay cases pass. Source hashes: core/claude_wake.py C48BBE5ABEFF857A3759F569A7FD0C0CF57467F9EF05343F2E436FBCC665156C; common.py 85197D62AA09F94E0B2C61921169C49294B7AC68C83B40269E95D53F3DDDD473. Evidence preserved in shared build/service-performance-20261012/claude-credential-revocation/red and green. No global legacy or disk-failure closure inferred.

## Scope and acceptance transition

Root and reviewer narrowed initial global closure before source acceptance: eager legacy rewrite is rejected because same-directory exclusive canonical ownership is not established. Preserve the immutable baseline above; current slice addresses modern stable admissions and retains the legacy refusal ledger item. Capture failures are distinct from validated legacy, normal publication preserves any pending scoped intent, and qualified normal closes compare expected identity under the native lock. Reviewer explicitly retains existing persistent-write-failure semantics: notice remains durable, next successful recovery applies it, but permanently failing disk cannot guarantee revocation. No new per-scope in-memory fencing or notice-on-load machinery is authorized.

## Affected evidence and final component review

Five affected files: 216 passed / 1 failed in 53.04s, private 9dd412beefe4495692163813ca4197c4, stdout SHA256 A71472554631C5219D5ABD50C108A89A340B9909ADADF6BAD1B5062170B0D14D; guards/stderr empty, all five tracked identities drained. Failure was the encoded-body-limit fixture expecting close HTTP without any prior canonical admission. Root and reviewer approved real prior HTTP204 registration setup, preserving the original close-only/restart assertions and adding expected-admission comparison. Exact corrected node: 1 passed / 0.47s, private 339c65dff7db42b1bef673afc5fdf821, stdout SHA256 AC06E9859EC73E81C7B04CCEC0F3DDF6CB2BD309A00A256F206F9AB5068A4DCA, guards/stderr empty, three owned identities drained. Reuse the 216 passes because production source did not change.

Seven malformed-notice cases: 7 passed / 0.56s, private baf56134f49147d3b25f6d2ae55a26fc, stdout SHA256 3486C22BB030D9C11B9A4ACBF80D6B0A102C44DA25BDEFEFDF98171A9352872F; guards/stderr empty, three identities drained. Wrong runtime/scope/admission/closed marker/keys/filename cannot trigger the legacy unscoped cleanup path. Source unchanged from focused GREEN. Static import-linter exit0 / zero violations; fresh Redline GRAY advisory with passed boundaries, no API change; diff check clean.

Agent technical review: /root/architecture_check final actual source/test acceptance, 2026-10-12; root approved integration checkpoint. Reviewed revision: frozen dirty delta on e2a0034c4270b253154a12e99a5cd4209d4a47b2; source SHA256 C48BBE5ABEFF857A3759F569A7FD0C0CF57467F9EF05343F2E436FBCC665156C and 85197D62AA09F94E0B2C61921169C49294B7AC68C83B40269E95D53F3DDDD473. Verification adequacy: causal helper+HTTP mechanism, normal replacement race, native/restart/failure boundaries and affected evidence qualify this modern-admission slice; they do not attribute historical CI, prove the full Stop hook, or close legacy/persistent-disk failure. Root requires one coherent combined full before release. Selector against origin/main selected full: python -m pytest tests/ -x -q. No separate full was run to avoid duplicate qualification before root's latest baseline integration.
