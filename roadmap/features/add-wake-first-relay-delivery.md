---
id: add-wake-first-relay-delivery
title: Add wake-first Relay delivery
status: active
priority: high
commitment: committed
milestone: pallium-relay
lane: capability
---

## Current release checkpoint (2026-10-20)

PR306 subsequently merged as `2ac9e2b66b9cd72ff7af9e7aeda9ecf061360b1f` from qualified `37fc691380f86db307b2de8932b09948a736db12` into PR297's actual merged main. Full local qualification passed 7,531 tests; package, real-HTTP and isolated native OpenCode 2.0.24 checks passed. The single reviewed Linux 3.12 retry passed 7,474 tests, with 92 skips and two expected failures; all other passing PR jobs were reused. Independent review verified actual logs and final merge conditions. PR314, PR297 and PR306 are now merged. Evidence: `C:/Users/I347041/.codex/worktrees/opencode-capture-idempotence/Pallium/build/pr306-current-main-20261020/verified-merge.json`. The baseline main Windows 3.13 retained-recovery failure remains unresolved and was not a full-Windows PR requirement. Installed deployment and broader reliability remain open; the item stays active.

PR297 merged as `178fea16e36946ffed68fb4bdd93da76056d5f73` from exact qualified head `07697ac2b8f74e8503534a6586fb13dbb30bdeb4`. The explicitly authorized final retry of ordinary run `39273147321` passed Linux 3.13 (7,440 passed, 92 skipped, two expected failures) and Windows 3.12 (79 serial passed, two skipped; 7,427 remaining passed, 33 skipped, two expected failures). Passing lanes were reused. Independent review accepted actual logs and compatibility with main `a28eb90dc1f962f4dbdf8afe67af52912016a2e9`; all four review threads were resolved. The actual merge tree matched the reviewed merge tree. Evidence: `C:/Users/I347041/.codex/worktrees/opencode-297-resume/Pallium/build/pr297-final-two-job-retry-20261020/verified-merge.json`.

PR314 previously merged as `cf4e8eceff28d601554ade615f2a9ecbed8ba500`. These receipts supersede historical pending-merge claims below. Earlier failures remain preserved; the closed diagnostic runs did not establish the physical cause of acquisition delays and were not used as release qualification. Broader runtime reliability remains unfinished, so this item stays active. No installed environment change or deployment accompanied these merges.

Roadmap completion receipt (2026-10-18 04:23 UTC): PR299 merged at `701608cd0f666fe5106bf7c91e2e98bf0fe21d0c` after exact-head documentation CI, governance and CodeRabbit passed with no unresolved findings. Its eight-finding OpenCode ledger records OC-2/OC-5 merged in PR302, separate open PR306/PR297 dependencies and remaining reliability/qualification work. This supersedes older PR299-pending statements below without closing runtime reliability. PRIMARY fast-forwarded to that documentation commit with the existing incident history reapplied exactly and its tracked-path stash retained; all untracked files remain. Installed `65a4e5ad` and the service are unchanged.

Diagnostic disposition (2026-10-18 03:26 UTC): the single isolated hosted diagnostic `39091113511` at `62e30f399229ced374a07ebc78e8c2e1cbe36ad3` completed successfully: Windows 3.13 serial coverage passed 79 with two skips; remaining coverage passed 7,296 with 32 skips and two expected failures. The target exact claim passed, with one observed request and complete, non-overflowed observation status. The failure-only recorder therefore contains no timing spans. This is nonreproduction only, not historical-cause closure or release qualification; no repeat capture is scheduled. Exact source parity and saved artifacts are under independent verification. Separately, Minimap PR52's bounded lock correction passed 21 focused tests with existing protected stale-lock recovery and concurrent-restart assertions retained; full upstream validation is next. Neither result closes Pallium's real-session reliability requirement.

Upstream completion receipt (2026-10-18 02:33 UTC): Agent Workflow PR55 merged as `25f35a0814e7d0d8a4d4eb7a25caaffc4f1b3a1d`, from exact head `acefed029d3317fa77a4d49490e87d6415d58a04`. Required test, Redline, workflow and CodeRabbit checks passed; the actionable review thread is resolved. Its Work Record now distinguishes blank package exit files from verified parity evidence. Minimap PR52 remains blocked: one hosted attempt left two live servers after two successful concurrent restarts, with only one registered; the other failed at the detached-child readiness result. The latter error covers timer, child exit and child error, and the test took 1.85 seconds, so a literal ten-second timeout is not established. Both raw attempts are retained under `build/consumer-upstream-validation-20261018/minimap-hosted-failures/`. Bounded lock/registry source review continues; no speculative fix or new run is authorized. PR320 can consume the Workflow merge once its remaining upstream dependency and combined qualification are resolved.

Terminal qualification checkpoint (2026-10-18 02:26 UTC; supersedes pending states below): PR314 at `65a4e5ad` passed ordinary CI, governance, all Linux lanes, both native Windows serial selections and Windows 3.12 remaining coverage. Full `39085577901` failed only the Windows 3.13 real exact claim: HTTP 503 `setup_deadline`, service time 1,504 ms, with 7,295 other remaining tests passing. PR297 at `45c30cd8` also has terminal failed full qualification: three Linux failures, while ordinary CI, governance and both Windows lanes passed. Neither PR is merge-ready; collectors are drained and settled jobs will not be rerun or polled. The shared acquisition path is being examined without assuming a shared physical cause: the deadline includes work before explicit BEGIN, and does not establish SQLite contention. A separate, temporary diagnostic branch prepares one narrowly instrumented hosted workload; artifact and safety-control review must finish before any dispatch. Release tests, deadlines and installed behavior remain unchanged.

The installed `65a4e5ad` rollout remains healthy by its recorded checks, but all 30 observed MCP clients predate that rollout. Candidate client loading and the new foreground recovery branch are therefore still unproven; no Desktop restart, client kill or private refresh API is authorized while the user is away. Upstream Workflow PR55's reviewed legacy-path validation correction is published at `abca6532` with 174 focused passes; exact-head hosted status and package exit-status evidence are being recovered. Minimap PR52 retains two separate hosted lifecycle failures and is not merge-ready. Consumer PR320's pins wait for upstream qualification and merge. PR278 substantive History acceptance, PR299's conflicting ledger and PR306 after PR297 remain outstanding.

Local-first rollout checkpoint (2026-10-18 01:35 UTC): installed clean `main` is now exact `65a4e5ad2ae6a886ca4c4e6be4141079907ba5a4`. The two runtime changes are explicit Windows object ownership and checked foreground client retirement for a later genuine caller, with no replay or relaxed trust checks. The baseline failure, 144 affected tests and full local 7,355-pass result received independent review. Backups and branch `backup/foreground-retirement-f49-20261018T013023Z` are retained under `build/team-wake-20261016/rollout-foreground-retirement/20261018T013023Z`. Installed-wrapper stop/start succeeded; old service identities drained, exact runtime hashes matched, health/readiness/vector/embedding/ingestion checks passed and queue health returned HTTP 200. Dependency inventory and protected configuration/launcher/wrapper fingerprints are unchanged. No Desktop or MCP-client refresh occurred: existing cached clients and execution of the new foreground recovery branch remain unverified. Hosted full `39085577901`, ordinary `39085580729` and governance `39085580687` remain under the sole collector; local installation is not a hosted qualification or merge claim. Prior 684 hosted failures and historical disconnect uncertainty are retained.

Publication receipt (23:45 UTC, received 23:51 UTC): PR297 normal-fast-forward published `45c30cd800e60b03fdcd3c0aab0fc1e66860a459` after independent full/result review and resolution of all three review threads. Full `39080166253`, ordinary `39080149955` and governance `39080149956` have one owner collector (`13762`); governance passed and application jobs are running. Local new-source full passed 7,159 / 45 skipped / 2 expected failures in 510.11 seconds, with captured processes drained. The guard ledger contains 116 flat DNS attempts, 115 detailed ONNX records and one caller-unknown record; that limitation is retained without replay. PR314's independently reviewed local `684cda350f7b4e01c603e6cb3f189e03e4f2e72e` passed its single lifecycle check and remains unpublished pending current matrix disposition. Consumer source regressions now own the local slot. Installed state remains unchanged. Recent root-bound payloads took approximately 6–14 minutes, with native-unavailable deferrals and incomplete activation histories; existing-log correlation is underway, not a reliability acceptance.

Latest coordination checkpoint (23:36 UTC; supersedes pending-state claims below): PR314 is published at `b7aebb4c2f599deae0e64e32da864d7a0ec7f0a9`, with full `39078580307`, ordinary `39078582663` and governance `39078582646` under the existing sole collector. Windows full jobs remain pending. Ordinary Linux 3.12 rejected one trailing read-only eligibility probe after the expected read/send pair; the minimal assertion correction has independent technical and simplicity approval, retains every ownership/ACK/reservation/settlement assertion, and awaits its single positive check. The earlier second-send SQLite refusal remains unexplained; its unchanged journey passed one passive observation, which is nonreproduction only. No ordering workaround or repeat capture is authorized.

PR297's new-source full suite actually started in managed session `5921`, frozen record `75ae0cd2` with reviewed source `bf30120d` unchanged. Seven focused controls and independent review are accepted. Pal-dev1 exclusively owns the local application-test slot until terminal evidence and process drain; an app-message fallback resumed this step after an older Relay instruction left the owner idle. No focused tests are repeated. Exact-source full qualification, publication and hosted qualification remain required before merge; PR306 follows actual merged main.

Separate consumer PR320 is published at `c48318945efcb47ab552baa96919735ed22f927e`. The isolated short-path full suite passed 7,169 cases, but hosted Python 3.12 failed two unrelated setup cases, so the PR is not merge-ready. Three verified upstream review findings now have independently accepted minimal plans in isolated source worktrees: decode legacy Git C-quoted paths while preserving strict path-set validation, apply the existing cached request budget to aliased workspace reads, and preserve fresh first-page data plus deduplicated later pages on same-generation refresh. Source fixes and regressions remain pending; original dirty upstream roots and installed Pallium are protected. PR278 substantive History acceptance and PR299's ledger remain unresolved as recorded below. Individual recent Relay ACKs do not establish all-session reliability.

Latest coordination checkpoint (22:45 UTC; supersedes pending-state claims below): PR314 is published at `c24b70fe9b68a221bf88dfbad4c953fdd8d0a498`, with full `39074509617`, ordinary `39074512384` and governance `39074512399` under one collector. Two Linux failures have independently reviewed test-only corrections in clean local `c36a2b297ea40795c2c2df258bb71dcc99f3503d`: callback-entry synchronization (original completion deadlines retained; deterministic RED plus nine GREEN cases) and the first restricted-resume registration prerequisite (three cases). Root read the committed three-file patch; no runtime or installed changes. Current Windows jobs must finish and all failures receive disposition before normal publication and one replacement qualification. The previous ownership correction passed the actual native serial selections on both Windows lanes; this does not establish general delivery reliability.

PR297 `9a18fb3982b552b23a316ed88e1a795ceae91073` qualification is terminal: ordinary and governance passed, manual full failed. Windows 3.12 failed first enrollment before behavior; Windows 3.13 sent successfully but did not witness transport entry within one second. No common cause is established. Pal-dev1 owns preparation of two passive observations under an independently reviewed plan and now has the released local application-test slot, conditional on actual artifact review; no published source change or blind CI retry. PR306 waits for PR297's actual green merge and then composes against actual main.

Consumer refresh remains separate: pinned Workflow/Minimap source review and the distinct custody correction `c9c5cc29c82e570701214a94f693764e83396f6d` are accepted. Full qualification stopped after 3,726 passes at a 248-character directory creation and a 263-character intent temporary file. The first is proven Windows path-length failure; the second is strongly consistent but not conclusively attributed. A reviewed shorter private runner keeps TEMP and pytest basetemp separate; its one full run is queued after PR297's observations. PR278's local composition checkpoint `4abbba0910d4b32e24eca0a16a756a81ff575115` passed 139 affected tests, but substantive History acceptance remains 0/4 within 29,581/32,000. PR299's conflicting ledger is preserved.

Installed `f49f6b0cf26c081501cf175dad49aaaf28db4e51` is unchanged. Recent real payloads arrived after 8–11 minutes with incomplete traces containing native-unavailable deferrals; two later complete traces show busy-session deferral, transport acceptance, then payload ACK in approximately 65 and 36 seconds. These are individual delivery observations, not all-session reliability acceptance. No receive, manual ACK, resend, forced turn or Desktop restart was used. Required releases and real-team reliability remain open.

PR297 publication (19:48 UTC): reviewed five-file candidate `fa016aa33bf5026499ca4bf684305e96986a23d8` was normal-fast-forward published to the existing PR. It fixes cross-session initial-ownership invalidation and assertion-failure subscription cleanup, plus the bounded Claude registration prerequisite. The old plugin reproduced the loss; eight corrected HTTP/History cases, 106 package cases, the native caller journey, cleanup controls and the required local full suite (7,158 passed / 45 skipped / 2 expected failures) passed independent review. Both inline findings were answered and resolved. Exactly one hosted full run `39063896646`, automatic CI `39063863078` and governance `39063863082` target that head; governance passed. Pal-dev1 remains sole collector. Historical Codex timing failure remains unexplained, and local success is not hosted qualification. PR306 composition and installed state remain separate; no merge has occurred.

PR314 `78efcbf` qualification is terminal: ordinary/full CI failed and governance passed; its sole collector exited successfully. Windows 3.13 remaining tests passed 7,282; Windows 3.12 remaining tests passed 7,281 with one `ImmediateTransactionBusyError` in `test_http_activation_reads_authority_once_and_fails_closed[claude-code-failed]`, under bounded review. Both native-enabled serial selections failed during secure fixture ancestry validation before native behavior: `unsafe-owner` on 3.13 and `unsafe-acl` on 3.12. The proposed test-local secured pytest-temp fixture preserves all authority checks and requires actual review and native validation. Independently reviewed local `c0a216edff5a67dc6974b327dcb72286eadddf38` contains the worker-count and two-registration prerequisite corrections, with one and 23 focused passes respectively. No further publication, dispatch, installed change or merge has occurred; old runs must not be polled again.

Original delivery-cohort reconciliation (19:02 UTC): fresh read-only snapshots show ten of the eleven originally failed deliveries eventually ACKed on October 17 between 09:00 and 10:06 UTC. The remaining `relay-delivery-f387e66416a54cfdb13fe04d9cd42862` expired without an ACK after three claims. Its recipient's saved final observation explicitly reports no original hook payload, only an app-message fallback; that is failed delivery evidence, not autonomous success. First-page activation histories are truncated and were not exhausted, so no historical cause is inferred. These events predate the later installed claim-expiry correction and cannot validate the current runtime. Saved snapshots: `build/team-wake-20261016/cohort-current-20261017.json`. No send, resend, manual receive/ACK or forced turn was used for this reconciliation. Existing recipient confirmation evidence covers only part of the ten ACKed cases; prompt wake and all-session payload reliability remain open.

Qualification follow-up (18:54 UTC): PR314's new lifecycle test overconstrained internal worker count; the observed three settled workers still produced exactly two native owners. Independently reviewed local `24aa8d084063c9e23ebfea11b1d9c73706200f00` removes only that internal equality, with the full positive journey passing once and native-action, generation, payload, ACK and cleanup assertions retained. A separate Linux callback test failed during its two-session setup before callbacks were armed; its prerequisite boundary is under review, with no production-delay cause established. The original full matrix continues; no new publication or dispatch has occurred. PR297 also has two newly unresolved review findings: possible cross-session completion suppression by a global retirement fence, and subscription cleanup missing after assertion failure. Its owner is independently verifying both and retains implementation ownership of the earlier first-hook admission finding. Neither PR is merge-ready.

Latest verified checkpoint (18:39 UTC; supersedes active-state claims below): PR314 is normal-fast-forward published at `78efcbf98aeae742cb8520cb081598220a083666`. One full qualification `39058892350`, ordinary CI `39058895015` and governance `39058894958` target that exact head; encoded_setup_fix is the sole collector. The prior `54f78b4f` runs are terminal failed. Independently accepted follow-ups include 40 Linux prerequisite checks and 24 initial gate checks plus two corrected production-lifespan controls; failed fixture-development attempts remain recorded. The existing Windows-full serial lane now includes the six real native reconnect cases. The autonomous retained-expiry journey uses actual production lifespan scheduling with a fake Desktop boundary; it does not prove real-host reliability. No runtime or installed change accompanies these test/CI corrections; installed `f49f6b0c` remains protected.

PR297-only `b4fd6beb1249b13b06bafef62f704ae60819f2c1` is published. Ordinary `39058158248` and governance `39058158296` passed; manual full `39058178148` remains under pal-dev1's sole collection. Its Linux 3.12 failure is a first-hook admission refusal before the intended response-loss injection, independently confirmed not covered by PR314. The owner has the bounded finding; no shared physical cause is established. Its separate combined continuation passed 7,158 local non-slow cases under the private locked environment. PR306 follows actual PR297 merge; PR299, draft PR278's substantive History acceptance and persisted Workflow/Minimap refresh remain outstanding.

Current continuation: the user renewed standing authority to finish qualification, publish reviewed fixes and merge when green without routine handoff approval. All `c26b3cb5` runs are now terminal: ordinary/full CI failed and governance passed. Reviewed local `ba6924b188db94db3e5ad7e60e0b478843e92016` contains three test corrections with 35 independently accepted focused checks. Two additional Windows registration prerequisites failed before their intended behavior; their narrowly scoped fixtures and controls are being completed before publication. No current full CI remains active, and installed `f49f6b0c` is unchanged. Physical setup delays and general wake latency remain unproven resolved.

Other agreed work remains active: PR297's current-main integration and PR297/306 composition passed independent review, 134 package checks and two native end-to-end cases. Its isolated full run hit two Windows temporary-path setup failures; both unchanged nodes passed under shorter paths, and one corrected full run is authorized after PR314's short local test slot drains. Historical native logs were not recovered by the bounded search; preserve that limitation. Publish the PR297-only component first, then reconcile PR306 with the actual merged main. PR299 canonical ledger reconciliation, draft PR278's substantive History recovery acceptance, and the separate persisted Workflow/Minimap consumer refresh remain outstanding; none is silently closed or superseded.

Latest qualification: PR314 is now pushed at `c26b3cb59246d687c5a294f16802cbc4c5f32792`. Exactly one full `ci.yml` run `39044587073`, ordinary CI `39044590717`, and governance `39044590627` are active on that head; encoded_setup_fix is the sole collector. The test-only continuation preserves production behavior, fixes native owned-worker settlement ordering and updates the strict request expectation for the already-reviewed optional expiry field. Deterministic baseline RED and seven GREEN cases, including delayed settlement and stuck-worker rejection, passed independent review. Five prior Windows failure causes remain unproven; no further preemptive edits or blind reruns. Merge requires exact-head qualification and review-thread disposition. Installed service remains clean at `f49f6b0c`; no restart or installed update was done for these test/ledger commits.

Recovered follow-up detail: PR278's local continuation `db74865a6f4e9a34e8bd4a4f163ec9d59350c942` must be preserved; it contains work beyond its remote draft. Its Work Record confirms the old Windows setup failures were resolved, but the actual blind History incident-recovery check still failed 0/4 content groups (single-case downstream-task-effect), with 440 characters over the frozen ceiling. This is a separate acceptance blocker, not a reason to hold PR314 or silently close the draft. Consumer-refresh inventory also confirms only the agreed existing skill/checker surfaces need updates; source owners and backups are identified, and the installed clone remains clean. Prepare those as a separate persisted change after the active release qualification checkpoint.

PR314 publication resumed: reviewed local fixes plus the truthful release ledger are now normal-fast-forward pushed as `1c53b815435d2a0f4350e6a771041631124a6bc2`. Automatic CI `39043494615` and governance `39043494617` started on that exact head; no manual full run has been dispatched. The existing six Windows failures remain explicitly unproven fixed. A bounded review supports correcting only the native-error test's owned-worker settlement order before its unchanged sender-join assertions; the suggested health helper change was withdrawn because that helper is already present. Installed `f49f6b0c` is unchanged. Pal-dev1 accepted recovery of #297/#306; Workflow and Minimap owners confirmed exact pending consumer scopes, now undergoing read-only conflict/persistence preparation separately from the release.

At pickup, the user explicitly resumed publication and closure of the reviewed local fixes, plus recovery of the previously agreed follow-ups. PR314 was open at `cfb8bb1148cf88f0319fdfb0ea8806a7a0a195f2`; the local reviewed chain through installed `f49f6b0c` is eleven commits ahead. Publication preparation and independent integration review are active in `pr312-fixture-final`, using the existing Work Record; exact-head full qualification and final review precede merge. Unresolved activation delay and the historical queue error remain disclosed, but are not a blanket hold on unrelated work. No fresh CI has yet been dispatched for this continuation.

Follow-up sequence recovered and live-checked: #297 needs current-main conflict/API reconciliation, then #306 capture idempotence qualification; #299 needs roadmap conflict/status reconciliation; draft #278 needs current-base History qualification. All four remain open and none is silently superseded. Workflow and Minimap owners have each been asked once over Relay for their exact previously authorized pending consumer-update scope; serialize approved file updates without modifying active runtime, configuration, data or installed cleanliness. Receipt of those coordination messages is not yet confirmed. The prior read-only simplification review found no supported production redesign; preserve that conclusion rather than expand the release.

Bounded queue-error structure diagnostic `f49f6b0cf26c081501cf175dad49aaaf28db4e51` is installed clean after independent review, verified one-file backup, normal fast-forward fromd92b and successful supported wrapper StopOnly/restart. At14:44:48 UTC, health/status/queue returned200, initialized/ready/embeddingtrue, runtimeBA92C7E4 matched review, newAPI43552 was active, old59708 absent and all57 normalized dependency pairs unchanged. No Desktop/dependency/configuration/data change occurred. The existing failure log now exposes only fixed structural observations and exact source-supported outer markers, with no raw error text;38 focused privacy/outcome/fence/cleanup controls passed. The unknown first pal queue exit is not diagnosed by this change. Backups and full rollout receipts are `build/team-wake-20261016/rollout-queue-stderr-structure`; root owns next genuine observation. Governance shadow advisories and incomplete broader qualification remain disclosed.

Root's real-team review afterd92b confirms all four fresh14:27 deliveries reached normal-hook payload with their exact wake, attempt1/no redelivery and no root resend/forced turn. Astra arrived in about13 seconds; pal and Minimap around14:30:29; Workflow around14:32:29 after target-not-idle/native-unavailable deferrals. Pal's initial queue exit1/categoryother remains unexplained; the saved exact host window has no matching queue record and raw stderr was discarded. These receipts establish delivery for that batch, not acceptable activation latency or general reliability. Root retains exact receipt ledger in rollout-claim-expiry/team-root-review.md.

Expired-hook admission correction `d92b1a59a195bcccefb6a0cee73a10a13403765b` is installed clean after independently reviewed normal fast-forward fromd91f and successful supported wrapper StopOnly/restart, with verified five-file backups. At14:26:16 UTC, health/status/queue returned200, initialized/ready/embeddingtrue, all five runtime hashes matched review, newAPI59708 was active, old43972 absent and all57 normalized dependency pairs unchanged. No Desktop restart or dependency/configuration/data change occurred. The exact hook carries its existing remaining two-second budget as optional UTC-ms expiry; existing transaction guards reject expired requests before claim and roll back session/generation/lease changes when expiry occurs before final guarded return. Baseline RED proves a real timed-out hook could otherwise leave an abandoned claim;27 focused cases pass, including delayed HTTP409/pendingattempt0 then fresh Unicode emission/ACK1 and actual-flush rollback. Missing-field legacy behavior remains compatible. Local shared UTC and native commit/response races limit the claim: this is not guaranteed response delivery or general wake reliability. Backups, wrapper/process/dependency/health receipts: `build/team-wake-20261016/rollout-claim-expiry`. Root owns postactivation real-team verification, pending at this checkpoint. All blocking governance predicates pass; API/persistence/architecture and size shadow advisories remain disclosed. No new CI/publication occurred.

Queue-failure diagnostic `d91f484f6fa9ec76a927b5fdaf425157f6b4cb0a` is installed clean after normal fast-forward from04974423 and supported wrapper restart. At13:43:31 UTC, health/status/queue returned200, initialized/ready/embedding checks were true, runtime hashC28E26ED matched independent review, new API listener43972 was active and the old listener was absent. All57 distinct normalized dependency pairs remained identical. First StopOnly hit a stale-PID55812 race before FF; actual process absence was verified, failed evidence retained and one bounded wrapper retry succeeded. No direct kill, Desktop restart, dependency/configuration/data change or publication occurred. Existing classifier now recognizes verified queue error-chain stages and conservatively bounded RPC codes without raw error/message/data/path/token logging; all44 focused controls and independent committed review passed. Arbitrary errors may still be other/unknown and historical pal queue cause is unproved. Backup and full rollout receipts are `build/team-wake-20261016/rollout-queue-error-chain`; root owns postactivation genuine-team verification.

Standing human authorization now covers reviewed Pallium wake fixes/diagnostics and supported service-wrapper restarts with backup/rollback and installed health/dependency verification: "you don't need approval for every service restart, you have my ongoing approval to sort this out". Do not repeat approval handoffs for that scope. Desktop/client restart, dependency installation/version changes, persistent configuration and data changes remain outside it.

Message-loss correction `04974423df810f1079f49d42aff7ec1acf53072f` is installed clean after exact user approval, normal fast-forward from `8966a9f3`, and successful installed-wrapper stop/restart. At 13:19:42 UTC, the installed runtime hash matched review, health/status/queue returned 200, initialized/ready/embedding checks were true, the old listener was gone and new listener PID23524 was active. Dependency inventories were identical (57 distinct normalized name/version pairs; the historical raw inventory includes duplicate Pallium metadata). One service runtime file preserves a message that completed during deadline cancellation for exactly one later fresh read, while retaining the original deadline, bounds, stop/uncertainty guards and peer reset boundary. Baseline RED proves the prior frame loss; 22 focused controls plus a real Windows cancellation-race/source-registration journey passed after one secure-fixture setup correction. The historical live race remains unproved. Backup, wrapper logs, process/dependency and health receipts: `build/team-wake-20261016/rollout-message-read-carryover`. No Desktop restart, dependency/configuration/data change or publication occurred. The service restart activates server polling correction; existing MCP children retain their cached helper code.

Post-rollout real-team verification delivered both exact fresh messages without resend, app fallback or another restart. Astra `relay-msg-bbf0848567ba412ba62be3e4fe6f5ec2`, delivery `relay-delivery-b012e1779f4e4d8a85dd907a4a97d088`, ACKed13:20:38.106 UTC in4.205 seconds; root independently read its matching wake prompt and normal-hook payload confirmation. Pal-dev1 `relay-msg-918752a273294a9ba07b5f43ae63cd92`, delivery `relay-delivery-9b7a968003d9463f80ee0a240588fe86`, ACKed13:23:18.056740 UTC in163.747 seconds, with the exact wake and hook payload confirmed. Token values are deliberately redacted; this is not evidence of payload loss. Pal's initial queue subprocess exited1/categoryother at13:20:37.582179; retry dispatch13:22:36.909 failed registration-missing/reopen, then native queue acceptance13:23:09.397340 preceded hook claim13:23:17.527549. Eventual delivery does not close these latency/failure causes or establish general reliability. Bounded service/client/CLI evidence is retained in the rollout directory; no new post-rollout client close marker was found in that captured window.

Previous client diagnostic `8966a9f3bc5817f93605e8c30e74a080cb7bfdb3` was installed clean without a service restart. A new MCP child loaded it under the existing host without another Desktop restart: at 12:51:04.603789 UTC, its fixed marker recorded `idle-ready-deadline` for ownPID55952/native creation12:50:20.609000 UTC, unresolvedFalse. The service recorded the exact same peer alive closing1.838 milliseconds later. This establishes that client's registered idle-readiness retirement branch, not process exit; it does not prove the physical cancellation race. Fixed close-reason files remain bounded to8KiB per PID and omit caller/thread/payload metadata. All23 diagnostic controls passed; receipts are `build/team-wake-20261016/rollout-client-close-branch` and `build/team-wake-20261016/idle-ready-deadline-20261017`.

Local diagnostic `29357e19437bf75020a516511e68b947517bd98e` is installed clean after exact user approval and successful wrapper stop/restart. One runtime file adds authenticated channel-peer identity and a zero-time held-process state observation to the existing close log; authority, deadlines and cleanup are unchanged. All 16 focused controls and independent review passed. At 12:29:09 UTC, health/status/queue checks passed, embedding was ready and dependency inventory was unchanged. Backup and receipts: `build/team-wake-20261016/rollout-source-close-identity`. At 12:29:33 UTC, a resolved channel failure recorded authenticated PID 57052 alive; the subsequent native creation-time query matched exactly. Process exit is ruled out for that closure. An adjacent server registration succeeded, but lacks peer identity and does not prove client receipt. Client retirement, caller failure/cancellation and lifespan closure remain unproven alternatives. This is diagnostic evidence collection, not a wake reliability claim.

Previous availability-fix checkpoint: clean installed `a0a4cecef256aaccc1a61e8fa21c1983d51c77b9`, after explicit user approval and successful installed-wrapper stop/restart. One runtime file changes from `29587ad9`: conclusively completed accept error 232 drops stale authority, resets the pipe and resumes listening; unresolved/unknown failures remain terminal. Independent review accepted 37 controls plus a real Windows closed-before-accept to fresh authenticated registration journey. Two failed test-harness attempts remain recorded. The live service subsequently encountered accept 232 without restarting; health remained ready with increasing uptime. All 58 dependency versions are unchanged. Backups, wrapper logs and health receipts are in `build/team-wake-20261016/rollout-closed-accept`.

Earlier real-team checkpoint: fresh `relay-msg-a363d91a86fd43869ed220dda0989840` reached Astra through the normal payload hook with its matching wake prompt and a successful reply. Fresh pal-dev1 `relay-msg-e9d63c2857614f5ea8f07e416bc0c560` remained pending/unclaimed with complete trace pages reporting `native_unavailable`; the explicitly labeled app fallback also contained no payload, but that `functionCallOutput` surface does not prove a normal user-prompt hook ran. No resend, manual receive or ACK was used. Native registration can succeed then be released on source EOF; the new fixed client marker establishes readiness retirement for one exact authenticated peer but does not map every failed delivery or prove the historical cancellation race. Do not infer universal wake reliability or weaken authority revocation. Next work is bounded attribution of the initial queue exit and subsequent registration loss from existing evidence; the two post-rollout deliveries above succeeded but pal's latency remains unacceptable. Published PR314 remains separately unqualified; these local commits are not a merged release.

The user explicitly approved installing `7eb171644b61d84e243aed27ae24cf532592ed2f`, the installed-wrapper restart, and one user-controlled Codex Desktop restart. The local fast-forward and wrapper stop/restart completed successfully; installed checkout is clean and both runtime hashes match review. All three required health endpoints returned 200, initialized/ready/vector/embedding checks were true, ingestion pending was zero and recent queue failures empty. All 58 dependency versions, including AnyIO4.14.2, are unchanged. Evidence is `build/team-wake-20261016/rollout-retired-owner/post-restart-health.json`, with stop/restart logs and exact preimage backups beside it. Native enrollment was still `never_registered` before client refresh. User was told the service is ready for the approved Desktop restart, then to return with “restarted”. Next: verify fresh client loading and native enrollment, then actual team wake/payload/ACK; no manual receive/ACK, stale notice resend, safety-latch reset or guessed scope. Health alone is not reliability acceptance.

The retired-owner recovery correction is independently accepted in clean local `7eb171644b61d84e243aed27ae24cf532592ed2f`, parent `2c6c1fe0`. It retains the authenticated process handle through resolved retirement and permits changed-service acquisition only after kernel-confirmed old-owner exit, including exit during retirement. All 112 affected worker/native application cases passed; two corrected private baseline controls independently proved that the old code misses fresh registration in both sequences. The initial two private harness failures remain recorded and application passes were not repeated. Fresh import/workflow checks pass; existing nonblocking governance advisories and required full qualification remain disclosed. From installed `8ee1c702`, exactly two runtime files change, including the accepted bounded diagnostic. Hash-matched installed backups are ready at `build/team-wake-20261016/rollout-retired-owner`. Exact local update/service restart and user-controlled Desktop restart approval has been requested because running MCP children cache the old code. Nothing after `8ee1c702` is installed yet. Full published-candidate Windows 3.12 qualification failed three cases (7148 passed); Windows 3.13 remains under the sole collector. Real-team reliability is not established.

Local reliability now takes priority under the user's explicit direction. Both approved local rollouts completed: `cfb8bb1148cf88f0319fdfb0ea8806a7a0a195f2`, then `8ee1c7021dcfd438d818f0d0df1099092605c773`. Installed checkout is clean at `8ee1c702`; the installed restart wrapper completed and health, status, queue and embedding checks passed. Dependencies, configuration, data and Desktop were unchanged. The latter fixes returned Win32 `ERROR_PIPE_CONNECTED` (535) being treated as failure; thirteen new controls, including a real Windows pipe, passed. Three unrelated existing file tests remain disclosed. Service health does not establish wake reliability: native enrollment remains absent. Evidence is `build/team-wake-20261016/rollout-native-preconnect`.

Ten of the eleven original notices now have delivery ACKs, with several actual recipient payload confirmations. The remaining `relay-delivery-f387e66416a54cfdb13fe04d9cd42862` had no payload even in the authorized app-fallback turn; it remained claimed at attempt three with no delivered timestamp. No manual receive, ACK or resend was performed. A bounded source review found a further lifecycle defect: retiring a resolved source connection discards its authenticated old-service process handle, so a later service exit cannot authorize replacement. Implementation and independent review are active for retaining that exit witness and preserving all untrusted-replacement fences. This mechanism is not yet proven to explain the live missing enrollment. Existing MCP clients require supported connection recreation to load a client-side correction; no such live action is approved or performed. The generic bounded native-error diagnostic in repository-only `2c6c1fe0` is not installed. Published `cfb8bb11` ordinary CI and governance passed; its full Windows lanes remain under the sole existing collector.

After explicit human approval, reviewed `cfb8bb1148cf88f0319fdfb0ea8806a7a0a195f2` was fast-forward pushed and exactly one full qualification [39021665057](https://github.com/rore/Pallium/actions/runs/39021665057) started at 09:34:44 UTC; ordinary CI `39021660454` and governance `39021660369` run on the same head. The prior `bfa4b8b6` full matrix finished successfully, including both Windows lanes (70 serial and 7151 remaining tests each); its ordinary CI failed only at the now-corrected endpoint-projection setup. The new candidate retains the independently accepted eleven-case result below. Root owns the sole once-only result collector; no installed changes have occurred. Exact-candidate qualification, final review, approved rollout and real-team payload/ACK verification remain pending.

Published `bfa4b8b6` qualification is not green: ordinary Linux 3.12 failed during `_send` registration setup before the endpoint-projection assertions (2980 passed, 1 failed; typed late-BEGIN refusal). The other three Linux lanes passed 7164 cases each, both smoke lanes and governance passed, and both full Windows lanes remain running. Independently reviewed local `cfb8bb1148cf88f0319fdfb0ea8806a7a0a195f2` removes unnecessary message delivery from that projection test's setup, inserting its canonical session row in the existing native SQLite setup transaction. All ten original parameters plus a control forbidding registration/message sends passed once (11 cases, 1.814 seconds); original projection assertions are unchanged. Only the test and Work Record changed. The historical physical delay remains unexplained. This correction is not pushed; no additional run or installed change has occurred. Complete qualification and the original eleven real-delivery receipts/ACKs remain outstanding.

Reviewed `bfa4b8b68dedb3d55afe9c7f064ea9713dcf896f` is published after exact human authorization, with exactly one full qualification [39018432294](https://github.com/rore/Pallium/actions/runs/39018432294), ordinary CI `39018415989` and governance `39018415929` on that head. Only the encoded-body-limit test's valid initial registration uses the existing scoped registry clock pattern, plus the Work Record. Native clocks are restored before all original rejection, close-intent, restart and Unicode assertions. The original test and full journey with a real 150 ms lock-open delay passed (2 cases, 0.775 seconds); native locking/restoration and owned-process cleanup were verified. Fresh selector requires full26; imports/workflow/boundary checks pass, existing advisories remain disclosed. Prior `f572b508` is terminal: ordinary/governance and seven of eight application lanes passed, including both full Windows lanes (each70 serial +7151 remaining). Linux 3.12 alone completed7163 passed/1 failed at initial registration (409 instead of204), before the body-limit behavior. Its physical cause is unknown. Root collected the complete previous run once and owns the new result collector. Runtime hashes remain frozen. Complete qualification, approved rollout and original eleven real-delivery receipts/ACKs remain outstanding; the installed service is unchanged.

Reviewed `87ccfd0a386850440a0c7990058fdd1b4939f336` is published with four test-only corrections and the Work Record since `e986988d`. Nine focused cases passed across the recovery, short-prompt and full D1/D2/D3 lifecycle checks, including real delay controls; all original delivery, ACK, generation and no-replay assertions remain. Prior `e986988d` is terminal: governance, full Linux 3.12, smoke and full Windows 3.13 passed; the four failed nodes are the corrected cases. One full qualification [39010301454](https://github.com/rore/Pallium/actions/runs/39010301454), ordinary CI `39010303892` and governance `39010303880` run on the exact new head. Production files and installed environment remain unchanged. Complete qualification, approved rollout and the original eleven real-delivery receipts/ACKs remain outstanding.

Local `dc5ab7ac4c8d3c101ec8e7ea43ede089fe09cd55` contains three independently reviewed test corrections atop published `e986988d`. Ordinary Linux failed a second release admission and retry-target admission before the intended claim/ACK race; manual Linux 3.13 failed session-lock setup before the short-prompt protocol check. Five operation-local recovery cases and two short-prompt cases passed, including real admission delays, native timing restoration and unchanged semantic assertions. The manual Linux 3.12 lane, smoke lanes and governance passed; both full Windows suites are still running. Publication waits for their combined disposition. No production or installed change, shared physical cause, or original-delivery success is claimed.

Reviewed `e986988d24b1b284615c721a3a1d26d7fdfbc69f` is published. Prior `25b564af` qualification finished with seven of eight application lanes and governance passing; Windows 3.12 failed only the Claude coalescing test's two-second transport-entry wait. Its synchronous reservation already establishes coalescing. The correction removes that readiness dependency and always releases and drains owned workers, retaining exact coalescing, completion and trace assertions. The full affected file plus delayed-transport and duplicate-worker controls passed 56 cases and independent review. One full qualification [39007406523](https://github.com/rore/Pallium/actions/runs/39007406523), ordinary CI `39007409970` and governance `39007409945` target the exact new head. Production files and the installed service remain unchanged; original eleven-delivery acceptance is still outstanding.

Reviewed `25b564af86b4aebb635804834795dd0217d26f80` is published. The latest three test corrections preserve payload validation and model one ordinary periodic recovery opportunity omitted by bare fixtures; seven payload cases and eight distinct recovery cases are accepted, retaining two initial private-control failures and their corrected follow-up. The targeted negative proves committed uncertainty remains fenced. Prior `cc401f1f` qualification is terminal: ordinary/governance and full Windows 3.12 passed; full Linux 3.13 failed initial payload-test registration, and Windows 3.13 failed two substantive recovery assertions. One full qualification [39004176902](https://github.com/rore/Pallium/actions/runs/39004176902), ordinary CI `39004170007` and governance `39004170004` are active on the new exact head. No production safeguard or installed environment changed; original eleven-delivery acceptance remains outstanding.

Reviewed `cc401f1fca649cf027ee0e4b786f5f3042ae2684` is published. Its three bounded test corrections passed 15 focused cases, including real connection-delay and initial-recovery-readiness controls; native production timing and refusal contracts remain unchanged. Prior `57548090` qualification is terminal: ordinary/governance and both full Windows suites passed (each 70 serial plus 7,151 remaining); the three full-Linux failures are the corrected cases. One full qualification [39000210524](https://github.com/rore/Pallium/actions/runs/39000210524), ordinary CI `39000206980` and governance `39000206935` are active on the new exact head. Full qualification, approved live rollout and original eleven-delivery acceptance remain outstanding.

Reviewed `5754809083dbd9507f54b21c452781394b401741` is published with only the two supported test corrections and Work Record added since `cb1f1b20`. Five focused cases passed: original restart journey with a real 460 ms connection-delay control, both observer states and real worker-tail writer-transaction settlement. Production files and safeguards remain unchanged. One full qualification [38997042482](https://github.com/rore/Pallium/actions/runs/38997042482), ordinary CI `38997039316` and governance `38997039317` are active on the exact head. Installed rollout and original eleven-delivery receipt/ACK remain unverified.

Qualification of `cb1f1b20` is terminal: ordinary CI and governance passed; manual Linux 3.12 failed initial restart-test registration (`late_begin`, 739 ms), and Windows 3.12 failed the observed hook comparison after its baseline passed (`local_gate`, 468 ms). Full Windows 3.13 passed 70 serial plus 7,151 remaining cases. The prerequisite-only Linux correction is independently accepted in local `21bf442c`, with the original journey and real 460 ms connection-delay control passing. The observer's competing-work boundary is under bounded review; no shared physical cause, release qualification or live delivery acceptance is claimed.

Reviewed `cb1f1b20f71772645b42fa0b9bcf7a99597baf2d` is published. The three bounded fixture corrections passed 45 distinct focused cases, preserving production timing and refusal safeguards. Exactly one full qualification [38993342180](https://github.com/rore/Pallium/actions/runs/38993342180), ordinary CI `38993339411` and governance `38993339394` are running on this head. Full qualification, approved installed rollout and actual receipt/ACK for the original eleven failed deliveries remain outstanding.

Qualification of `1913e2fa` finished with ordinary CI, governance and seven of eight application lanes passing. Windows 3.12 passed 70 serial and 7,151 remaining cases; Windows 3.13 passed 70 serial and 7,148 remaining cases but failed credential-loss revocation, malformed-response observation and post-cooldown worker settlement. The corrected pre-CAS registration passed. Bounded review is separating the actual revocation persistence/refusal contract, observer fixture admission and functional worker settlement; no shared cause or release qualification is claimed. The installed service and original delivery cohort remain unchanged.

Reviewed `1913e2fa7f0345e4a8288fb578f3cbfe66c98b2b` is published. Its prerequisite-only registration correction passed the original recovery test and a real 460 ms registration-delay control, with native timing restored before worker fault injection. One full qualification [38986741623](https://github.com/rore/Pallium/actions/runs/38986741623), ordinary CI `38986735888` and governance `38986735875` are running on this exact head. Production files remain unchanged by this follow-up. Full qualification, exact installed-rollout approval and original eleven-recipient receipt/ACK remain outstanding.

Qualification of `62548515` is terminal: ordinary CI, governance and seven of eight application lanes passed. Windows 3.12 failed only the initial sender registration in `test_http_pre_cas_worker_exception_clears_marker_for_same_process_resume` (`503`, `setup_deadline`, 827 ms), before the intended worker failure/recovery behavior; 7,150 other cases passed. The next bounded correction reuses the same file's existing prerequisite-only clock pattern and restores native timing before the worker behavior. No production deadline change, installed action or delivery acceptance is claimed.

Reviewed `62548515cec8c1deaa0b8ec89cbbe0b2cdcc33db` is published to PR314. The native cleanup correction and POSIX capacity sibling correction passed six focused cases in total; all three PR findings have reviewed dispositions. Exactly one full qualification [38982283250](https://github.com/rore/Pallium/actions/runs/38982283250), ordinary CI `38982256663` and governance `38982256708` target this head. Production bytes are unchanged by these follow-ups. Complete qualification, exact installed-rollout approval and actual receipt/ACK across the original eleven failures remain outstanding.

Qualification of `ca324570` is terminal: ordinary CI and governance passed, and seven of eight application lanes passed. Full Windows 3.13 finished with 7,150 passes and one failure in the POSIX capacity-policy test's second registration. Its Windows sibling already isolates that functional assertion from incidental lock-admission timing; the bounded review now checks the omitted sibling treatment, preserving native admission safeguards and exact survivor assertions. The separate native-test cleanup correction is committed locally as `b34621f268b629266a425a4a0b2085571cdc9ee7`; two direct failure controls and the real replacement/re-enrollment journey passed. No installed change or original-recipient acceptance is claimed.

PR314 now publishes independently reviewed `ca324570b3faf6dcfe35b3c974f0692bd39791ef` by normal fast-forward. Exactly one full qualification [38977484351](https://github.com/rore/Pallium/actions/runs/38977484351), ordinary CI `38977489005` and governance `38977489103` run on this exact head. Fresh checks cover 23 whole-change paths; required import, boundary, workflow and protected-contract checks pass, with recorded advisory findings retained. The candidate remains unqualified until complete results and review. Atomic-reply and readiness origins remain unknown; no installed change, repeat dispatch or original-recipient acceptance is claimed.

The coherent follow-up is now frozen for final checks: 14 Claude contract cases, one late-ACK journey and 238 retained/retry/direct-consumer cases passed, with root and independent evidence review. Shared fixture settlement uses the existing five-second watchdog convention, and the two functional journeys invoke one ordinary recovery sweep after initial worker settlement; native budgets, explicit timing tests and uncertain-state no-replay assertions remain unchanged. The six-path diff contains five test files and the work record, with no further runtime change. Atomic-reply refusal and empty-hook readiness remain unresolved and disclosed. Fresh whole-change checks and committed review precede the next publication decision; nothing has been installed and the original eleven deliveries remain unverified.

The two Claude contract corrections passed fourteen focused cases (including real lock-open delays), and the late-ACK observer correction passed its existing real-HTTP journey. Root and independent review accepted both results. The ACK witness now checks that the response exceeded the actual 500 ms ACK budget; the real 650 ms delay and all payload, durable-state and negative-ACK assertions are unchanged. Four qualification outcomes remain unresolved. A bounded source review identified that the two retained-wake fixtures omit production's periodic recovery; any correction must settle the initial worker before invoking the existing recovery sweep and must preserve uncertain fences. Atomic-reply refusal and readiness-marker failure remain separate unknowns. No new full matrix, publication or installed change has occurred.

The proposed quiet baseline/candidate experiment was cancelled before creating an environment or running tests: source tracing showed that the failing Claude registration paths do not execute the changed Codex lifecycle code, and a small quiet run would not reproduce full-suite conditions. The current bounded correction separates only two Claude functional contracts from incidental lock-admission timing: valid registration before revocation, and capacity reclamation policy. Native lock operations, refusal coverage and policy assertions remain intact. Actual diff review accepted the scope; one focused control batch is pending. No other failure-specific changes or new CI run are underway. The two wake runtime fixes remain frozen, and the original eleven real deliveries remain the acceptance requirement.

`36a38179` qualification is terminal and not green. Six of eight latest application lanes passed; full Windows 3.12 failed seven cases, and ordinary Linux 3.13 failed a PowerShell self-check timeout then a different valid-preregistration prerequisite on its single authorized retry. Original attempts and raw logs are retained; no further reruns are authorized by that retry decision. The failures span distinct admission, readiness, hook-settlement and timing-observation boundaries, without a proven shared production cause. Further per-case fixture changes are frozen. The next bounded investigation is an unchanged compatible-test baseline/candidate comparison, with exact runtime/source compatibility checked before one isolated pair; no broad rewrite, compatibility shim or repeat-until-green loop. A read-only status check at 2026-10-16 22:00 UTC found all eleven original deliveries still unacknowledged (four claimed, seven pending), expiring 2026-10-17 around 10:41 UTC; evidence is `build/team-wake-20261016/cohort-pre-rollout-status-36a38179.json`. Installed PR312 remains unchanged, and no rollout or live acceptance is claimed.

PR314 now publishes reviewed `36a381790f7d9925f131cd672914134363877bf2`. Exactly one full qualification [38963524506](https://github.com/rore/Pallium/actions/runs/38963524506), ordinary CI `38963533075` and governance `38963533206` target this head. Prior `91238010` passed seven of eight application lanes; its sole failure occurred at first native-attempt admission in a bare-router fixture that omitted production's periodic recovery. The correction is one ordinary recovery sweep plus a comment, preserving every transport, payload, ACK and idempotence assertion. Two selected cases and two refusal/uncertainty controls passed in 2.77 seconds; root and independent review verified the committed change. No clock, retry policy, authority reset or production change was added. Full qualification and approved rollout followed by actual original-recipient acceptance remain open.

PR314 now publishes reviewed `912380100884afd1d437a4728a968e8fe7ca252a` by normal fast-forward. Exactly one full qualification [38956748228](https://github.com/rore/Pallium/actions/runs/38956748228) and ordinary CI `38956671436` target this head; governance `38956671458` passed. The prior full Windows failures were endpoint seeding before migration and waiting for a synchronous natural-hook callback before race assertions. Two narrow existing-pattern corrections and two direct controls passed four cases in 5.29 seconds; no complete-file repeat was added. Root and independent review accepted the exact committed scope and fresh full-21-path checks with disclosed advisories. The five production hashes are unchanged. Scope remains the two demonstrated wake defects; complete qualification, separately approved live rollout and original eleven-recipient payload/ACK acceptance remain open.

Qualification of `1fedc912` remains incomplete: ordinary Linux failed, while both full Linux lanes, both Windows smoke lanes and governance passed; full Windows results remain pending. One ordinary failure emitted its payload and reached durable delivered state but lacked ACK-response confirmation evidence, with the physical cause absent from the raw log. The other encountered a typed reserve refusal during deferred recovery. Bounded follow-up preserves the original ACK success assertion and budget, adds diagnostics plus a real post-commit delayed-response negative case, and allows one later recovery only after proving pre-yield refusal and unchanged authority/native state. Root and independent review accepted 336 affected-file/control passes plus one corrected private-control pass (2.27 seconds); the initial private control failure is retained and not presented as a clean batch. Existing same-call reconciliation of a committed prepared fence explained that control's incorrect expectation. Production hashes are unchanged; final checks/commit, complete qualification and live acceptance remain outstanding.

PR314 now publishes independently reviewed `1fedc912b4c20e30ac4af4fa8fe25b522dee7afb` by normal fast-forward. Exactly one full qualification [38947720515](https://github.com/rore/Pallium/actions/runs/38947720515), ordinary CI `38947719555` and governance `38947719763` target this head. Fresh whole-change checks select all 20 paths; imports, boundary checks, workflow and protected-contract predicates pass, with disclosed size and historical shadow-checkpoint advisories. The five production hashes are unchanged from the reviewed lifecycle fix. Complete exact-head qualification, approved installed rollout and actual payload/ACK evidence across the original eleven failed recipients remain open.

The selected second-reply fixture correction passed two direct real-delay controls and all 64 affected Relay E2E cases: 66 passed in 30.97 seconds, with zero failures/errors/skips and no remaining private Python process. Root and independent review read the actual evidence under `build/qualification-boundaries/alias-reply-admission-eedbbce950834a72b9fe74115ab28958`. Only the functional second-reply acquisition uses the local logical clock; it restores before the third reply, and the native-clock companion still refuses without adding a reply or changing alias, claim or parent state. Production hashes remain unchanged. Fresh checks and final committed review precede one new exact-head qualification; installed rollout and original eleven-recipient acceptance remain outstanding.

Terminal evidence supersedes the pending/cancelled-lane expectation below: Windows 3.13 completed its full pytest output before the cancellation request, with 19 failures, 7,131 passes, 32 skips and two xfails in 3,976.88 seconds; its job conclusion is failure, while the overall manual run is cancelled. Raw SHA256 `2E1D9AF24E79A7EA69D6F3DF0533AEEA185DE00A9E43E9504A0CD2064D3FF4A5` is retained. Eighteen failures map to accepted corrections; the additional alias-transfer lifecycle case hit a typed send admission refusal at the second substantive reply, then raised `KeyError` when using the absent message ID. This is not setup failure. Exact contract/source review is active before publishing `9380a30`; no physical delay cause or new production fix is inferred. All CI is terminal; no repeat run or installed action has occurred.

Reviewed local fixture follow-up `9380a30a4d3d3113de3d36d2fdf1816ea39a1427` is ready with unchanged production hashes. After the published `761ea764` failed all four Linux lanes and full Windows 3.12, root directed standard cancellation of the sole remaining Windows 3.13 lane after more than an hour without exposed test progress. Cancellation of manual run `38936093292` was submitted after exact-head/status verification; its terminal logs must be collected and assessed before publication of the corrected revision. The cancelled lane is incomplete, never a pass. New exact-head full qualification remains mandatory; no installed change has occurred.

The selected concurrent-expiry correction passed both direct real-stall controls and the complete 28-case retry-edge file: 30 passed in 17.92 seconds. Root and independent review verified the saved log/JUnit and process result under `build/qualification-boundaries/owned-concurrent-claim-0cce8064377f415189d25581aea2e747`. Native clocks are restored before the two recovery sweeps; initial owner/fence prerequisites and original race assertions remain enforced. The native companion still produces the expected bounded admission refusal without consuming delivery authority. The accepted 14-case caller-fidelity evidence is reused, production hashes are unchanged, and fresh combined checks/committed review are in progress. Current full Windows qualification results remain pending; no new run or installed action has occurred.

The bounded caller-fidelity correction passed 14 cases in 9.27 seconds, including both protected journeys, seven SQLite cases, trace coalescing, all three real-Uvicorn shutdown stages and the direct missing-thread-method poisoning control. Root and independent review read the actual evidence at `build/qualification-boundaries/owned-caller-fidelity-ff0d651c52b14ff19317da99505f640c`; no test Python process remained, and the exact CI watcher was verified and reported separately. This proves the controlled mechanism and corrected callers, not the cause of every historical zero-owner result. Production hashes remain unchanged. The selected concurrent-expiry test's initial claim, strict initial-owner prerequisite and failure cleanup are being corrected separately; native clocks and assertions during the actual race remain required.

Qualification of `761ea764` is not green: both ordinary and both full Linux lanes failed; both Windows smoke lanes and governance passed, while the full Windows lanes remain under the sole watch. Bounded review found two missed capture-only thread doubles, including a protected behavior-contract fixture, that can leave an invalid worker in global ownership tracking. Fixture-only corrections must preserve all behavioral assertions and prove the contamination sequence. A new shutdown test bypassed the actual server's request-drain-before-lifespan ordering; its same three held-stage assertions are moving to the real owned Uvicorn driver. The concurrent-expiry test separately hit a typed initial-claim refusal before its race on Linux 3.12; Linux 3.13's zero-owner result has no captured cause yet. No shared cause, successful qualification or live recovery is claimed. No new full run or installed change has occurred.

PR314 now publishes independently reviewed `761ea7642cefa31134ff2abc378ee9b6114b2915`, including owned API shutdown after terminal retained-listener failure and Codex worker admission/draining. Exactly one full qualification [38936093292](https://github.com/rore/Pallium/actions/runs/38936093292), ordinary CI `38936094658` and governance `38936094690` target that commit. The implementer owns monitoring and once-only failure collection. Fresh whole-change selection requires full CI; import and boundary checks pass, while disclosed Gray/watch and historical shadow advisories remain. Installed service changes and original eleven-delivery acceptance remain outstanding.

Subsystem follow-up passed all 76 selected cases in 45.03 seconds after correcting nine capture-only thread doubles to implement the thread lifecycle interface and adding registry-owned fixture cleanup. Root and independent review verified the actual log, JUnit, unchanged production hashes, exit zero and zero remaining private Python processes. The affected evidence ledger contains 404 reused historical body/assertion passes plus 76 current passes; it is not a clean current 480-case run, and full CI must exercise the new finalizer across the reused cases. The initial 406-pass/74-failure batch remains recorded. Fresh whole-change checks and committed review are next; exact-head hosted qualification, live approval and all eleven original delivery receipts/ACKs remain required.

The isolated linked recovery test now passes: actual API PID54304 enrolled, encountered the controlled terminal listener failure and exited naturally; the unchanged supervisor qualified replacement PID46532 with a fresh nonce and epoch, and the same source process authenticated again. The original uncertain fence was preserved with no owner-tool replay. Both exit receipts show listener settlement and token removal, with terminal notifications `[1, 0]`. Root read the receipts and passing log under `build/qualification-boundaries/owned-terminal-native-evidence-e1e21631f7d64171810f27903bc1c0cb` in the isolated checkout. Combined focused coverage is 117 distinct passing cases using 111 unchanged cases, five corrected fixture cases and this linked case; initial collection and fixture failures remain recorded. A captured fixture lock collision was corrected to the production retained-directory namespace; it is not attributed to the original live incident. Remaining subsystem/full qualification, exact live approval and original eleven-delivery acceptance remain outstanding.

Production investigation now confirms a persistent recovery gap beyond PR314's diagnostics: the retained listener marks itself stopped after a terminal source-loop failure, while the API remains alive and its supervisor probes only TCP. Fresh `/status` at 15:11 UTC still reports released native enrollment and `reopen/stopped`; all eleven original failed deliveries remain pending, including four with no wake turn. Fully paged activation traces have explicit gaps and show repeated native-unavailable deferrals, so they do not establish the original terminal exception. Bounded architecture review is preparing graceful API process replacement through the owned ASGI server and existing supervisor, with Codex wake-worker admission/drain ownership before storage closes. No stop reset, same-process identity replacement, uncertainty clearing or live environment change is authorized by this preparation. Further publication/full CI is held until that production fix is reviewed; the independently accepted local fixture corrections remain preserved.

All `fc17d564` qualification is terminal. Full Windows 3.12 passed 70 serial and 7,124 remaining cases; Windows 3.13 passed 70 serial and 7,123 remaining cases but failed `test_queue_wait_allows_fresh_registration_and_disconnect`: native-attempt admission exhausted retries before its queue callback ran. The raw log identifies the refusal stage, not its physical cause. The earlier intent-arrival correction is committed and independently accepted as `e1846f7f`; publication is held for bounded contract review of this new failure. No new tests, rerun or installed change is claimed. Both original no-payload and no-wake recipients remain in the eleven-delivery live acceptance requirement.

Qualification on `fc17d564` found an ordinary Linux 3.12 intent-race fixture failure: publication completed just after its one-second arrival wait. Contract review found no one-second publication SLA and a real teardown defect: blocked workers were joined before their gates were released. The test-only correction preserves actual native contention and all old/new intent checks, uses a five-second arrival watchdog, releases gates before executor join, and ties the recovery gate to owner stop including failed startup. The initial batch recorded 58 passes, two existing platform skips and one private observer failure; only that observer was corrected and rerun (one pass in 2.25 seconds). Root and independent review accepted the combined evidence, including actual 1.101-second delayed publication, startup failure and exact owned-worker drainage before storage close. The initial observer failure remains recorded; its unsaved inner assertion is not claimed as proven. Evidence lives under isolated `build/qualification-boundaries/intent-arrival-*`. Both full Windows lanes remain pending, with no installed change or live acceptance yet.

PR314 publishes reviewed `fc17d5643eb4acf171170238e385b8719a7baa03` by normal fast-forward. Exactly one full qualification [38912597132](https://github.com/rore/Pallium/actions/runs/38912597132), ordinary CI `38912568698`, and governance `38912568313` now target this head. Root and independent committed review accepted the two narrow test-contract corrections, their actual 198-case and 36-case results, unchanged runtime hashes, and fresh checks. Full qualification is pending. No installed action has occurred; approval for the exact qualified rollout and actual receipt/ACK of all eleven original failed deliveries remain outstanding.

The `b40f0428` matrix is terminal: full Windows 3.13 passed 70 serial and 7,124 remaining cases; the only failures were the permitted idle-ready observation and a Windows 3.12 pre-claim admission refusal. The latter happened on the substantive first receive, not setup. History and dedicated deadline tests support making only that functional claim deterministic: a module-local SQLite clock is restored before ACK and readback, with real SQL, locks, sleeps and production budgets unchanged. Root and independent review accepted two real-delay controls and all 34 MCP lifecycle cases (36 passes in 13.85 seconds); the native-clock companion still refused without creating any claim authority. Evidence is `build/qualification-boundaries/first-claim-functional-0dd373e214a04b1c8622704a4e21a186` in the isolated checkout. The combined test corrections require new-head qualification. Installed PR312 and all original pending deliveries remain untouched.

On `b40f0428`, ordinary CI and governance passed, as did full Linux 3.13 and Windows smoke. Full Linux 3.12 had one assertion failure after successful replacement enrollment: the test rejected a permitted metadata-free idle `ready` observation after its exact initial ready/register pair. Source/history review confirmed that observation does not admit another client or change custody. The minimal assertion correction preserves the initial pair and permits only `ready(None)` afterward; two direct controls (real idle poll and actual extra-registration rejection) plus all 196 affected-file cases passed, 198 in 49.43 seconds. Full Windows lanes remain pending. A read-only recheck also confirmed all four original no-turn recipients still have pending notices and latest recorded turns predating those notices; evidence is in `build/team-wake-20261016/no-turn-recheck-before-b40-qualification.json` and `no-turn-native-recheck-before-b40-qualification.json`. No live delivery success or installed change is claimed.

PR314 now publishes reviewed `b40f04282d8d3d21f53c469dd66df137ce443b78` by normal fast-forward. Exactly one full qualification [38904845612](https://github.com/rore/Pallium/actions/runs/38904845612), ordinary CI `38904799692` and governance `38904799609` target that head. The previous Windows 3.13 lane passed all 70 serial and 7,123 remaining cases; the terminal prior matrix failed only the two cases corrected in this head. Root and independent review accepted the corrections and reused unchanged production evidence. Complete new-head qualification and exact live-rollout approval remain required; the original eleven failed deliveries still require actual payload receipt and ACK.

Full Windows 3.12 on PR314's `ada3adb8` finished with 7,122 remaining-case passes and one setup-registration HTTP timeout before the ACK/callback/shutdown assertions. The narrow correction gives only the two initial registrations the existing five-second setup budget; the client default and tested half-second ACK deadline remain unchanged. Root and independent review accepted a direct real 2.1-second registration-delay control and all 56 capacity cases (57 passes in 27.45 seconds), with results under `build/qualification-boundaries/capacity-registration-bfc0e6d06b494489a0e7e24eeaf2d89d` in the isolated checkout. The remaining Windows 3.13 result precedes publication and new-head qualification. No installed change or team-wide acceptance is claimed.

PR314 ordinary CI and governance passed. Full Linux 3.13 completed with 7,135 passes and one backlog-send refusal (`relay_busy`, pre-yield `late_begin`, 1,251 ms); full Linux 3.12 and both Windows smoke runs passed, with full Windows lanes still running. The supported test-only correction permits one identical backlog retry only after typed pre-yield refusal, unchanged claim/session/wake authority and the real bounded `Retry-After` wait. Root and independent review accepted four direct controls plus all 28 affected-file cases (32 passes in 20.42 seconds), including rejection of post-yield refusal, persistent refusal and changed authority. Broader private control harness drafts were rejected before writing; the narrower direct controls were approved and passed. Production admission budgets and all 12 recovery journeys remain unchanged. Evidence is in the isolated checkout's `build/qualification-boundaries/backlog-four-8f617291a820434a8d36bad6794292e2`; full qualification remains held and installed/live acceptance is incomplete.

Follow-up [PR314](https://github.com/rore/Pallium/pull/314) publishes reviewed commit `ada3adb8569f894f603986dc492735daf953c35a`. Exactly one full qualification [38895605457](https://github.com/rore/Pallium/actions/runs/38895605457), ordinary CI `38895589609` and governance `38895589578` target that head. Local controls and independent committed review passed; full qualification and live team acceptance remain outstanding. The change omits optional enrichment only for exact wakes and adds bounded terminal-source category/source-line diagnostics. It does not reconstruct listeners, weaken identity or uncertainty guards, or establish the historical no-turn cause. Installed PR312 remains unchanged pending qualified-candidate rollout approval.

The isolated exact-wake correction removes optional work-reference enrichment from the payload claim path while preserving existing associations. A real HTTP regression reproduced a committed claim followed by a 2.2-second optional refresh and no emission/ACK; the corrected path emitted and ACKed. Root and independent review accepted 150 passes and two existing platform skips in `build/qualification-boundaries/exact-wake-optional-db43af7187454935b8c07077230aca28` in the isolated integration checkout. This establishes an avoidable delay mechanism, not the historical cause of every failure. The four no-turn sessions are not archived. Their native source remains a separate unresolved boundary; terminal-source diagnostics and qualification are in progress, with no installed change or replay of their original deliveries.

Team dogfooding reopened wake reliability after the successful single-recipient rollout check. The 15-session notice cohort has four delivered/ACKed notices, four empty-wake sessions with a claim that expired without ACK, three empty-wake sessions with no claim, and four sessions with no new turn in the captured app history or local rollout. These are observed boundaries, not established shared causes. Exact traces and recipient evidence are retained in `build/team-wake-20261016/cohort-initial.json` and `recipient-inputs.json`. Investigation must correlate native submission, hook input, HTTP response, payload injection and ACK, including the no-turn sessions. PR312 remains merged and installed; its qualification and single-recipient acceptance do not establish team-wide wake reliability. No resend, manual ACK, receive, environment change or new qualification run has been used for this investigation. Closure requires actual payload receipt and ACK across the affected real team sessions.

Bounded remaining-PR review: keep #297, #306, #299 and draft #278 open; none is superseded by #312. #297 must adapt its old `owned(id)` guard to the current `owned(id, item, signal)` API before qualification. #306 retains distinct ownership/idempotence work and should rebase after #297; its current Linux checks failed. #299 needs current roadmap statuses after #312/#302; its reliability ledger is not yet on main. #278 remains a separate History change requiring current-base qualification before leaving draft. Read-only simplification found only a possible small shared passive test observer; no production Relay deletion or redesign is justified by this review.

PR312 merged at `e0e08303f11c56d655c0801d3fa0782afb520302` after exact-head `bb7a592d08f40e75aeb38f2d86724c041d0eea86` passed all eight application lanes, ordinary CI, full qualification and governance. Root and independent final review verified saved log hashes, resolved review threads and merge readiness. The installed checkout is now clean at the merge, all three approved hotfix bytes are preserved, and the only package change is AnyIO 4.12.1 to 4.14.2. The installed wrapper restarted successfully; `/health`, `/status` and `/debug/queue/health` return 200 with initialized, ready, vector index and embedding provider all true. Primary roadmap changes and untracked work were preserved. Evidence is in `build/service-performance-20261012/rollout-e0e08303`.

The final installed Relay acceptance passed after exact sender scope was injected. One payload, `relay-msg-8754d0fed08142cc997bc8e460cb85b3`, reached the requested chat `01a130a6-b8af-75e1-bf82-4298e1bcb6dc` through its normal hook. The recipient confirmed marker `pr312-installed-e0e08303-20261016`; delivery `relay-delivery-24e0348df34544e1aaf79adcf2748dbe` records one claim and ACK at `2026-10-16T04:36:55.304199`. No receive, manual ACK, resend, recovery prompt, Desktop restart or hook repoint was used. The initial activation trace reported `native_unavailable`/uncertain before the delivery completed, so this verifies actual receipt without claiming universal native-wake reliability. The saved trace is `build/service-performance-20261012/rollout-e0e08303/relay-final-trace.json`. PR312 qualification, merge, approved rollout and installed acceptance are complete; the broader roadmap and remaining PRs retain their separate dispositions. All earlier checkpoints below are historical.

Reviewed candidate `bb7a592d08f40e75aeb38f2d86724c041d0eea86` is published by normal fast-forward. Prior `83d0a77e` full qualification passed every lane; ordinary CI failed only the restart-fixture case corrected here. Exactly one full qualification [38845566235](https://github.com/rore/Pallium/actions/runs/38845566235), ordinary CI [38845537726](https://github.com/rore/Pallium/actions/runs/38845537726), and governance [38845537659](https://github.com/rore/Pallium/actions/runs/38845537659) now target the exact new head. Root and independent committed review accepted its two-file scope and 60 passing cases with two existing platform skips. Complete green exact-head qualification and final review remain required before merge and approved rollout. Earlier checkpoints below are historical.

Local correction `bb7a592d08f40e75aeb38f2d86724c041d0eea86` prepares only the restart-recovery test's private session directory and lock byte before its timed hook journey, leaving session JSON absent and real publication, locking, HTTP and ACK unchanged. All 60 cases passed with two existing platform skips. A real 150 ms cold directory operation reproduced the original pre-attempt refusal; the same preparation outside the hook allowed the full journey, while held-native-lock and publisher-error controls retained fail-closed behavior. Root and independent result review accepted the evidence; committed review is completing. On published `83d0a77e`, ordinary Linux 3.12 failed this case, while ordinary Linux 3.13, both full Linux lanes and both smoke lanes passed. Full Windows lanes remain running. Publication awaits their combined disposition. No physical-delay cause, complete green qualification, merge or installed change is claimed. Earlier checkpoints below are historical.

Reviewed candidate `83d0a77e94521573a44e0ca04064f2148c60621a` is published by normal fast-forward after full Windows 3.13 on `b0b978d9` passed 70 serial and 7,099 remaining cases. The sole failed lane was Windows 3.12's second reconciliation send, addressed by this accepted correction. Exactly one full qualification [38841064307](https://github.com/rore/Pallium/actions/runs/38841064307) and ordinary CI [38841039695](https://github.com/rore/Pallium/actions/runs/38841039695) are running on the new head; governance [38841039718](https://github.com/rore/Pallium/actions/runs/38841039718) passed. Prior results and private-control failures remain preserved. Complete green qualification and final review remain required before merge and approved rollout. Earlier checkpoints below are historical.

Clean local correction `83d0a77e94521573a44e0ca04064f2148c60621a` passed root and independent committed review. On published `b0b978d9`, six application lanes plus ordinary CI and governance passed; full Windows 3.12 failed only the second send in the registry-reconciliation journey with a typed pre-transaction refusal. Full Windows 3.13 remains running. The test-only correction preserves concurrent send ordering and all original delivery assertions, permitting one replay only after exact pre-yield evidence, unchanged durable authority and the real bounded Retry-After wait. The affected file passed 165 cases; all 15 controls passed after repairing missing original-module fixture setup in the private harness. Both earlier failed control sets and the first set's warnings remain recorded; the initial worker-only diagnosis was withdrawn. Root verified the real 454.7 ms refusal, 1.0006-second wait, fail-closed negative cases and cleanup. Publication awaits the final Windows result and combined disposition; no additional local tests or installed changes are planned. Earlier checkpoints below are historical.

Reviewed schema-lock correction `b0b978d9660b5d4943cfba0c242265db8f38e89c` is published by normal fast-forward. Exactly one full qualification [38834497230](https://github.com/rore/Pallium/actions/runs/38834497230) and ordinary CI [38834475620](https://github.com/rore/Pallium/actions/runs/38834475620) are running on that head; governance [38834475434](https://github.com/rore/Pallium/actions/runs/38834475434) passed. Root and independent review verified the clean three-file commit against all 76 focused passes. Fresh import checks kept eight contracts with zero broken; full validation is selected and existing persistence, size and shadow advisories remain disclosed. Complete green qualification and final review remain required before merge and approved rollout. Earlier checkpoints below are historical.

All `8a26ab7d` qualification is terminal: ordinary CI, governance and seven application lanes passed. Full Windows 3.13 completed with 70 serial passes, then 7,090 passes and one concurrent fresh-startup failure reporting `OSError: Resource deadlock avoided`. The child traceback is truncated, so its exact failing acquisition and holder remain unknown. Connected-source and contract review found a Windows schema-lock mismatch: one native `LK_LOCK` call can exhaust ten attempts, while the accepted startup serialization contract and POSIX implementation wait for ownership. The smallest correction reuses the repository's existing exact-`EDEADLK` retry pattern, preserving all other errors, native waits, lock region and release behavior. All 76 cases passed in 62.45 seconds: real competing-process baselines observed the original error after about ten seconds, corrected schema and pair locks reacquired after release, and error-identity, interruption, ownership, empty-file and existing concurrent-startup checks passed. Root and independent review accepted the source and results. Fresh import and governance checks precede commit and full qualification. This is isolated native-mechanism evidence, not hosted runtime parity or proof of the truncated historical stack. No merge or installed change occurred. Earlier checkpoints below are historical.

Reviewed candidate `8a26ab7d468e4af8b1315be792af0c09d05e8f77` is published to PR312 by normal fast-forward. Exactly one full qualification [38827086600](https://github.com/rore/Pallium/actions/runs/38827086600) and ordinary CI [38827068497](https://github.com/rore/Pallium/actions/runs/38827068497) are running on that head; governance [38827068486](https://github.com/rore/Pallium/actions/runs/38827068486) passed. The combined four paths contain the Work Record and three reviewed test corrections, with 239 current passes and 189 reused passes. Root and independent review verified clean committed scope and source hashes. Complete green qualification and final review remain required before merge and the approved installed rollout. Earlier checkpoints below are historical.

All `417f7450` qualification is terminal: ordinary CI and governance passed, while full qualification failed on Linux 3.13 and Windows 3.13. Windows 3.12 completed successfully. The Linux callback-arrival correction is independently accepted in local commit `65bfea01`, with 189 passing cases. The two remaining Windows failures occurred before the lexical/vector journey was ready and before a retained-recovery hook returned. Bounded test corrections reuse the existing prebuilt-resource fixture and wait for real hook completion before the unchanged worker-join assertion. All 239 cases passed in 84.76 seconds, including both affected files and six controls using real 5.1-second preparation and 2.1-second hook delays. Broken readiness and a post-hook stuck worker still failed the original assertions. The fake reconciliation worker joins the existing ownership list; vector controls observed actual storage close after settlement. Hook controls proved settlement before custody drops and clean original teardown, but their late-installed storage-close observer did not run. Root and independent review accepted the evidence with that limitation; final commit checks precede one full qualification. No production deadline change, physical-delay cause, complete green qualification, merge or installed update is claimed. Earlier checkpoints below are historical.

Clean local correction `65bfea01e073810e2b67ac44a7eedd22518d8175` passed root and independent committed review. Full Linux 3.13 on `417f7450` failed before the fresh-authority observation callback entered; the saved trace does not establish the physical scheduling cause. The test now pauses at callback entry, establishes the real native-owner lock, then runs the original one-second progress assertion. All 189 selected cases passed, including real delayed-arrival, lock-taking regression and cleanup controls. Production code and native budgets are unchanged. Ordinary CI and governance are green; both full Windows jobs remain running. Publication of this correction awaits their combined disposition; no extra local tests or installed changes are planned.

Reviewed candidate `417f74505f0015dcd8ad493cc09c6dbc0e5dd854`, including launch-token fix `7ef3524d`, is published to PR312. Exactly one full qualification [38818183610](https://github.com/rore/Pallium/actions/runs/38818183610), ordinary CI [38818167789](https://github.com/rore/Pallium/actions/runs/38818167789), and governance [38818167821](https://github.com/rore/Pallium/actions/runs/38818167821) are running on that exact head. Root and independent review verified the clean committed scope and accepted evidence. Full validation is selected; boundary checks passed and existing shadow advisories remain disclosed. Complete green qualification and final review are still required before merge and approved rollout. Earlier checkpoints below are historical.

Full `adbc66ac` qualification finished failed only on Windows 3.12, with 70 serial passes followed by 7,084 passes and two failures; the other seven application lanes passed. The restricted-prompt adapter encountered an observed pre-transaction `SQLITE_BUSY`, and retained recovery setup reached its incidental thread join before native dispatch settled. Narrow test corrections passed combined validation: 294 initial passes and exactly 12 corrected follow-up passes. Initial failures remain recorded; native budgets and original delivery, authority and post-dispatch join assertions remain. Root and independent review accepted the results, including real competing-writer and stuck-worker controls. These corrections are being committed with the already-reviewed launch-token ownership fix `7ef3524d`; fresh complete qualification remains required. No hosted work is currently running and no installed change has occurred.

Final review identified an unresolved launch-token ownership defect: inner runtime or MCP-entry failure could remove the outer production process's token and prevent supervisor fail-fast. The minimal correction leaves token ownership with the existing outer wrapper while preserving eager factory ownership. All 125 affected health, token and supervisor cases passed, including five new real-token lifecycle cases; six mutation controls passed after correcting one private exception-group matcher. The initial matcher failure is retained. Root and independent review accepted the evidence; commit checks are in progress. Ordinary `adbc66ac` CI and governance are green, with both full Windows lanes still pending. That earlier revision cannot qualify the new production correction. No merge or installed change has occurred.

Reviewed candidate `adbc66acb416b653b47a8348cb9324af01417dce`, including `8828def1`, is published to PR312. Exactly one full qualification [38808942384](https://github.com/rore/Pallium/actions/runs/38808942384) started at 21:19:08Z; ordinary CI [38808900859](https://github.com/rore/Pallium/actions/runs/38808900859) and governance [38808900938](https://github.com/rore/Pallium/actions/runs/38808900938) target the same head. Root and independent review accepted the committed sources, 145 reused passes, the original Stop journey pass and all 14 final ACK controls. Three private harness failures remain recorded. The capacity failure remains unexplained and its test is unchanged. Full validation is selected; boundary checks passed, while size/checkpoint/commit-order advisories remain. Complete green qualification and final review are required before merge and approved rollout. Earlier checkpoints below are historical.

The latest isolated batch recorded 145 passes, one failure and two skips in 63.33 seconds. All 26 controls and the three bounded corrections passed. The single unchanged capacity case passed every observed acquisition, absence, reclamation and publication gate; its historical refusal remains unexplained and its source stays unchanged. The remaining Stop batching test emitted three messages before its local ACK adapter raised on a recorded 523 ms `late_begin` refusal. A narrow adapter correction is undergoing independent review; validation will repeat only that failed node and its new controls. Existing passes remain reusable. No new hosted run or installed change has occurred; the checkpoints below describe earlier states.

All `8b51c768` qualification is now terminal. Full Windows 3.12 finished with 70 serial passes, then 7,081 passes and four failures. Bounded review supports corrections to a trace-completion test fence, a missing-name validation request refused before BEGIN, and a final send refused after the intent-race checks. The fourth failure, a direct capacity registration returning `False`, has no recorded refusal category; one local passive gate observation is authorized before changing that test. The reviewed `8828def1` candidate remains held while this work proceeds. No new CI, production fix or installed change is claimed.

Full Windows 3.13 on `8b51c768` passed 70 serial tests and 7,085 remaining tests; only Windows 3.12 remains running. Clean local candidate `8828def151debdb2146e14db9d33aeb5f3ad316b` passed root and independent committed-hash review. Its four paths contain only the Work Record and the accepted shared-setup/scope-move test corrections. Publication follows the final Windows result and combined disposition; no additional local tests are pending.

Partial `8b51c768` qualification found a shared empty-registry setup refusal on ordinary Linux 3.12 and a precommit scope-move refusal on full Linux 3.13; the other Linux and both smoke lanes passed. Both full Windows lanes remain running. The bounded correction reuses the strict empty-state helper for the shared functional fixture and permits one scope-move retry only after exact typed refusal, unchanged durable authority and a real bounded `Retry-After` wait. All original state/history/no-duplicate assertions remain. Validation recorded 517 passes and six failures caused by the new guard checking the recency field instead of activation. After correcting that field, exactly those six cases passed in 6.87 seconds; all caller files and unchanged protected contracts were reused. The real-delay control measured 1.000298 seconds before its successful retry; persistent and altered-state paths remained failures. Root and independent review accepted the combined evidence. Final commit checks continue while the remaining Windows results are collected; no additional CI or installed change has occurred.

Reviewed candidate `8b51c768cf6733c1d14b42de9b14667602aaf060`, including `08ac1175`, is published to PR312. Exactly one full qualification [38797247459](https://github.com/rore/Pallium/actions/runs/38797247459) started at 19:51:20Z; ordinary CI [38797213256](https://github.com/rore/Pallium/actions/runs/38797213256) and governance [38797213267](https://github.com/rore/Pallium/actions/runs/38797213267) run on the same head. Root and independent review verified the committed sources against accepted evidence. Full validation is selected; local boundary checks passed, while size/checkpoint/commit-order shadow advisories remain disclosed. Complete green hosted qualification and final review remain required before merge and the approved installed rollout. Earlier checkpoints below are historical.

The bounded follow-up keeps real database preparation outside seven lifecycle observation windows using the existing prebuilt-resource pattern. Production delegation still runs once off-loop; original task, close, drain and deadline assertions remain. Initial validation recorded 268 passes and three failures in a new refusal guard; all lifecycle controls and 53 health tests passed. Connected-source review showed a refused first native attempt successfully releases its prepared reservation. The corrected guard verifies that exact release, initialized-empty durable authority and zero delivery attempts before one real recovery into the next generation. Seven guard controls and the affected retry file then passed all 34 tests in 14.65 seconds. Initial failures remain preserved; passing health/retained files were not repeated. Root has verified the results; final independent evidence review and commit checks precede one complete hosted qualification. No production delay cause or installed change is claimed.

Final `0b545ce2` qualification failed. Windows 3.12 completed with 70 serial passes, then 7,075 passes and eight failures in the remaining selection. One wake-recovery case encountered a typed native-attempt refusal; seven production-factory lifecycle cases failed at initialization or shutdown waits. Recorded early-storage durations span 4.203–9.860 seconds, but the logs do not establish a shared cause or permanent resource leak. All CI is terminal. The reviewed local `08ac1175` corrections remain unpushed while the implementer and independent reviewer examine these exact contracts and connected failure paths. Supported corrections will advance through focused controls and qualification; no blind rerun or installed change is planned.

Reviewed local commit `08ac1175fccb332cc6a42a77f558b6818d98fc1c` is ready with the bounded health-lock oracle and selected empty-registry setup corrections. Full Windows 3.13 qualification on published `0b545ce2` passed 70 serial tests and 7,083 remaining tests; only full Windows 3.12 remains running. Publication of the reviewed correction follows that final result and combined disposition. The prior Linux 3.12 failures remain recorded; neither complete qualification nor a native-delay cause is claimed. No installed changes have occurred. Earlier partial checkpoints below are historical.

Partial `0b545ce2` qualification: both Linux 3.13 suites completed with 7,098 passes, both Windows smoke suites passed, and governance passed. Linux 3.12 failed two different tests; the full run completed its selection rather than stopping early. One failure occurred in empty registry setup before the crash/recovery journey. The other inferred native-lock blocking from a two-second health-read wait, but its captured worker stack was in SQL compilation. The bounded correction reuses the reviewed empty-setup helper only for selected functional journeys and directly detects forbidden lock acquisition while a real owner holds the lock. Full HTTP/readback, no-mutation and hook/ACK assertions remain. All three affected files and 12 controls passed (469 passes); five private controls initially had an isolation-fixture setup error, then all five passed after importing the existing isolation fixture. Initial errors remain recorded. Root and independent review accepted the combined evidence; final local commit preparation continues while the two full Windows jobs run. No native-delay cause or complete qualification is claimed.

Reviewed candidate `0b545ce256e5e4921e83c9ab6083ff24126ac2c8` is now published to PR312. Exactly one full qualification [38784596502](https://github.com/rore/Pallium/actions/runs/38784596502), ordinary CI [38784571784](https://github.com/rore/Pallium/actions/runs/38784571784), and governance [38784571465](https://github.com/rore/Pallium/actions/runs/38784571465) are running on that head. The combined nine-path change contains six test-file corrections, the manual-continuation workflow and its tests, and the Work Record. The complete manual run now collects subsequent failures without making failed selections green. Local evidence and committed hashes passed independent review; hosted qualification and final review remain required before merge and the approved installed rollout. Earlier checkpoints below are historical.

The last `46ea1b1b` lane, Windows 3.12, finished failed: 6,122 remaining tests passed before a participant lookup returned `relay_busy` during an injected concurrent detach. All prior qualification jobs are now terminal; no release qualification passed as a whole. Review found the fixture marked detach completion before performing the write. The correction distinguishes callback entry from completed detach and scopes its setup clock only to that injected write, restoring the native clock before the lookup executes. The real detach, page-full assertions and native locks remain. The affected file and five controls passed 24 tests in 10.04 seconds; the faithful stale-page mutation returned four rows and failed the unchanged five-row assertion. Root and independent review accepted the evidence. This final correction is being committed with the previously reviewed candidate, followed by one full hosted qualification that continues collecting failures. No production cause, merge, or installed update is claimed.

Earlier partial qualification checkpoint: ordinary CI on `46ea1b1b` failed; the manual run still has its full Windows 3.12 lane running. Both Windows smoke lanes and hosted governance passed. Linux failures exposed two typed transition-refusal assumptions and two setup boundaries, before the later functional assertions. The bounded corrections preserve exact durable authority and require one real recovery after an observed typed refusal; setup-only transport/retry handling retains native acquisition limits and does not replay message sends. All four affected files and 16 controls passed together (293 tests, 106.31 seconds), independently reviewed. Windows 3.13 subsequently failed empty registry initialization before the claim-generation contract. Its exact functional setup now observes native initialization and permits one retry only after exact typed refusal plus verified uninitialized, empty authority; generic, persistent and ambiguous errors remain failures. That affected file and nine controls passed 191 tests in 36.35 seconds. Manual qualification continuation checks passed 14 tests in 20.00 seconds, plus two portability controls: manual runs collect subsequent failures while preserving a failed final outcome. The combined clean local commit `12314cdfcf40b59694bbc306818887d9b1b119d3` passed independent committed-patch review; eight paths contain only five test-file corrections, CI workflow and its tests, and the Work Record. Publication awaits the current Windows 3.12 result and combined disposition. No merge or installed update has occurred; these results do not establish the historical native delay causes.

User-directed continuation: the remaining qualification-boundary corrections passed independent review and focused validation. Explicit entry/completion handshakes preserve the original assertions; only the Unicode functional case uses the existing longer readiness harness parameter; the shared HTTP-wake fixture restores its local registration clock before test bodies. A separately observed typed release refusal now verifies pending authority and real recovery before the original empty-reservation assertion, while generic errors still fail. The initial batch recorded 505 passes and five failures, including four embedded-interpreter bootstrap failures and one release refusal; three service-contact attempts were blocked by guards. The four exact subprocess cases then passed under an existing standard interpreter, and the release controls plus affected retained file passed 176 tests. All 11 original boundary controls passed. This is focused mechanism evidence, not hosted parity or historical cause closure. The reviewed candidate `46ea1b1bc6df50f9c7977c3c5b71b2b9a3bd3bad`, including cleanup commit `8308710f`, is published to PR312. Ordinary CI [38776092305](https://github.com/rore/Pallium/actions/runs/38776092305) and exactly one full qualification [38776098961](https://github.com/rore/Pallium/actions/runs/38776098961) are running on that head. Complete green qualification and final review remain required before merge or installed rollout. The checkpoints below describe prior revisions.

PR312 points to reviewed candidate `1a52aa49eb41e6a1d39e0cc152d87d06ec99298a`. Its four supported test corrections passed their controlled checks and affected-file validation; diagnostic scaffolding is excluded. Ordinary CI [38758834909](https://github.com/rore/Pallium/actions/runs/38758834909) and full qualification [38758871260](https://github.com/rore/Pallium/actions/runs/38758871260) both finished failed. Full Windows 3.12 passed 70 serial tests and 7,076 remaining tests; full Linux 3.13 and Windows smoke also passed. Other lanes failed at worker-entry waits, Windows harness readiness/process-lock completion, or an HTTP-wake fixture's initial registration returning 503 before its target test. Passing lanes do not waive those failures or establish their causes. Hosted Agent Workflow passed; existing local shadow advisories remain. The current bounded correction addresses a source-proven cleanup gap in `test_operation_tracking_covers_cancellation_and_failure_boundaries`: its first four-worker phase can fail before releasing and draining work, then close storage. The minimal cleanup correction and regression passed independent review: removing only the new cleanup failed at the expected missing-drain assertion, and the corrected affected file passed all 56 tests in 22.96 seconds. Original assertions and deadlines remain unchanged. The Work Record and cleanup correction are committed locally as `8308710fa607082c1433cc6e7f5efd34a0cb5fbb` in the clean integration worktree; publication and full qualification remain outstanding. This defect is not established as the cause of hosted delays. No new CI, merge, or installed change occurred. Saved qualification evidence is in the integration checkout under `build/functional-timing-controls/release-1a52aa49`. The checkpoints below are historical.

The approved two-lane diagnostic [38745645068](https://github.com/rore/Pallium/actions/runs/38745645068) finished failed on separate branch `codex/pr312-native-cause`, commit `7077505d8b1ee0e8102d9b4b55369f5d4a68d50a`. Both original targets passed on both platforms with complete body receipts and whole-case JUnit results: initialization returned once and reservation returned twice, without an observed exception. Linux Python 3.12.15 / SQLite 3.45.1 matched all 66 pins; Windows Python 3.12.10 / SQLite 3.49.1 matched all 67 pins. Neither original native failure recurred, so their causes remain unresolved. Linux completed 7,091 passed, 1 failed, 89 skipped and 2 xfailed in 409.56 seconds; its different MCP lifecycle failure returned 503 with `late_begin` after 1,983 ms. Windows completed 70 serial passes and 2 skips, then 7,076 passed, 1 failed, 32 skipped and 2 xfailed in 2,461.19 seconds; its different retry-edge failure left a worker alive after `join(2)`. These different nodes do not establish independent or shared causes. Root and independent review verified the saved evidence under the diagnostic checkout's `build/native-cause-controls/hosted-38745645068`. The target-survival mechanism worked, but this is not release qualification. Exactly one run was created after repairing an initial workflow validation rejection that created no jobs. No further run was started; PR312 remains at `36fb54f31e1326881034123e06f932cd9a76796e`, unmerged and undeployed.

### Local test-fixture corrections validated — unpushed (2026-10-15)

On PR312 candidate `36fb54f31e1326881034123e06f932cd9a76796e`, two local test-only fixture corrections passed focused validation. The callback-entry cleanup regression now waits for its existing worker-entry handshake before deliberately reaching the original assertion; its reviewed missing-drain RED failed at `drain_entered`, the focused GREEN passed all four cases, and the affected capacity file passed 55 tests. The character-budget journey now uses a test-local SQLite queue clock copy so incidental sender/recipient setup does not consume its functional assertion budget. With a real 460 ms stall after the first sender registration’s `session.connection()` returned, the original setup returned 503 `setup_deadline` without the fixture and returned 200 with it; the test passed under the same stall, and the affected hooks file passed 123 tests. A temporary notice-reservation sensitivity control still failed the original rendered-versus-claimed assertion when the reserve was removed.

These are unpushed local test-fixture changes, not production changes; `app/main.py` is unchanged. They validate the controls and functional journeys but do not establish historical hosted failure causality. The full CI on `36fb54f` remains failed and the two native failure causes remain unresolved. PR312 is still unmerged and undeployed; there was no new CI dispatch or rollout.

### Terminal diagnostic update — 2026-10-15

The single authorized hosted run [38716662378](https://github.com/rore/Pallium/actions/runs/38716662378) completed on diagnostic commit `3dab9b7fe0d55a69997cf318d9a1904c30a1f045`. Its pinned Windows Python 3.13.15 lane matched all 67 active dependency pins, including AnyIO 4.15.1 and filelock 4.2.0. The serial prelude passed 70 tests with 2 skipped. The four-worker remaining selection completed with 1 failed, 7,076 passed, 32 skipped and 2 xfailed in 2,359.40 seconds. The receipt and JUnit report show the selected second direct registration passed; its scoped lock took 302,700 ns and the complete case took 0.113 seconds. This is a non-reproduction, not causal closure.

The separate full-suite failure was a Codex hook delivery assertion: expected cross-container delivery was absent, with `relay operation=turn outcome=busy duration_ms=1663 acquisition_stage=setup_deadline`. That duration covers the whole Relay operation and does not isolate the cause of the setup-deadline refusal or connect it to the earlier registration result. Standard Linux 3.12, Windows 3.12 and Windows 3.13 lanes also failed; Linux 3.13 and Windows smoke passed. The diagnostic run is not a green release matrix. PR312 remains unmerged at candidate `b84a54c156b4fadaa2867409e7ebf6e45c3aef87`; no installed change occurred. Earlier checkpoint details below are retained as history.

### Prior diagnosis checkpoint — before run 38716662378

PR312 remains unmerged at `b84a54c156b4fadaa2867409e7ebf6e45c3aef87`: ordinary PR CI passed, but both full Windows lanes failed. The single approved Windows 3.13 retry also failed; its remaining suite stopped after two failures, leaving coverage incomplete. Earlier pending-run statements below are historical. No installed rollout or final Relay receipt has occurred.

The selected Claude credential-revocation case passed once in isolation and then under the original four-worker remaining-suite selection on Python 3.13.15 and all 67 CI package versions, including AnyIO 4.15.1; earlier local full qualification used AnyIO 4.14.2. Its parallel artifact records HTTP 204 for both registrations and close, with publisher lock acquisitions of 1.0877, 0.6973 and 0.3434 ms. This is non-reproduction, not causal closure. The hosted failure exhausted the 100 ms intent-lock acquisition budget before a native lock attempt, during initial valid registration; the exact setup/scheduling consumer remains unknown. That budget covers local lock acquisition, not an end-to-end registration SLA; the revocation test implicitly requires timely successful setup.

The parallel run stopped at 1 failed, 1,821 passed, 2 skipped and 1 xfailed in 158.91s on a later subprocess-bootstrap test. Embedded Python did not load that test's child PYTHONPATH bootstrap, so full hosted startup parity was not achieved. The outer guard denied two installed-port resolution attempts; all 14 tracked processes drained. An earlier harness attempt stopped before the target on proven excessive temp-path lengths; the corrected run used a short private root. Evidence: PR worktree `build/service-performance-20261012/windows313-reproduction/parallel-94ba0a1ec0454e379189a38db3b2979a`. `windows_reproduction` owns evidence/restoration; `lock_contract_review` independently accepted the bounded result and limitations. No budget/assertion/product change or causal fix. The next proposed diagnostic uses standard hosted Python and retains the early-failure timing artifact; no further CI run is dispatched. Existing Work Record: `.agent-workflow/tasks/service-performance.md` in the PR worktree.

## Historical incident execution checklist (2026-10-13)

Root owns this ordered checklist and the final installed result. A component report,
queued assignment, passing experiment, or healthy HTTP endpoint does not close it.
Existing Work Records apply; no separate tracker or duplicate implementation.

| Step | Owner | State | Completion evidence / next handoff |
|---|---|---|---|
| 1. Implement bounded Relay writer coordination. | Performance developer (`discovery_contract_review`) | Implemented and integrated at `631d3dd2`. | Provider-owned mutex with one shared 450 ms acquisition allowance, at most three attempts, unchanged caller deadlines, release on every exit, and native SQLite arbitration across providers/processes. |
| 2. Review and test the production implementation. | Architecture reviewer + performance developer | Component review and regressions accepted. | Lock-order/non-recursion audit; deadline, external-writer, multi-provider, cancellation/cleanup and non-BUSY recovery regressions passed; no weakened budgets. |
| 3. Pass the real delivery acceptance test. | Performance developer + architecture reviewer | PASSED on the combined authority-envelope and AnyIO 4.14.2 candidate. | Original shared-process 50-thread barrier, 750 ms claim and 500 ms ACK budgets, observer-free: all 50 claim/emission/ACK/public-readback journeys passed in 7.58 seconds. Five owned processes drained; guards empty. Private `162e969e6fea4be3887795dada126ed2`, stdout `15079EFEF17F01663F43FF77E1F514BE0674CCD47044CCFA593B7CA729DA7E1A`. Earlier failures remain preserved. One qualified sample is not universal reliability or installed receipt; final combined full, CI and step 7 remain required. |
| 4. Integrate all accepted incident fixes. | Root | Integrated at `d9bedaca`; combined corrections in progress. | Recovery, ACK completion, writer coordination, retention, startup, inventory, shutdown and exact wake-continuity guidance combined. Installed emergency changes and unrelated work preserved. |
| 5. Finish combined regression and independent review. | Root + reviewer | Fresh configured full PASSED; final evidence review underway. | 6,992 passed, 45 skipped, two xfail in 392.56 seconds on isolated AnyIO 4.14.2, verified in the master and all four workers. All 79 owned identities drained; guards empty. Private `0f0f27c3ef5f4b328aa06017319ecf95`, stdout `BECC98F8D183621501C30FBC67F56D7E95D7F2896FF4C21BAF8C2CFFD942CA54`. Focused authority 49, affected authority/retry 206 and original 50-message test also pass. Historical hosted timeout causes remain unproved. |
| 6. Publish and merge. | Root | Preparing the qualified update to [PR #312](https://github.com/rore/Pallium/pull/312); current remote head `cafc9a85`. Independent TLS PR313 merged at `428d796f`. | Prior CI `38371648429` failed Linux 3.13 on absent observation entry and post-restart send-busy; bounded diagnostics retain original assertions/deadlines, and exact nodes pass on the fixed runtime. Fresh 6,992-test full and original 50-message acceptance now pass. Publish the reviewed candidate, inspect every review thread and run one final-head Linux/Windows full matrix. No merge past failed or pending selected CI. |
| 7. Deploy and verify the installed service. | Root | Waiting on step 6; installed backup prepared and rollout scope explained. | Preserve code/data/settings and rollback; reconcile the three-file emergency hotfix; use installed restart wrapper; verify health/status/queue/embedding and real Relay receipt after restart. Reuse exact approvals; surface only genuinely additional live scope. |
| 8. Resume coordinated dogfooding. | Root | Waiting on step 7. | Notify managers through Relay with truthful qualification/known limits; verify representative actual receipts, not only pending send results. |
| 9. Reconcile every remaining bug and close the incident honestly. | Root; recovery reviewer for independent triage | Open. | Each REL row has verified closure or an explicit unresolved cause/host limitation and next action. REL-11 historical cause, REL-12 archived-target eligibility and REL-13 task continuity must not disappear behind the load-test success. Preserve evidence and complete checkout cleanup only when safe. |

Latest load investigation: fresh endpoint projection was reduced from three reads to one, with 138 focused tests passing, but clean synchronized load still completed only 37/50. Capacity and static authority-query experiments did not improve delivery and were reverted. A separate-server-process comparison also failed (35/50), ruling out shared server/client GIL contention alone. The bounded authority-read probe measured 1,045 of 1,304 ms of aggregate read wall time in row execution/fetch/materialization; connection churn and validation were not the dominant cost. Raw DBAPI fetch passed nine boundary checks and reached 44/50, with all 44 emitted payloads ACKed, but six claim refusals still block acceptance. One sample is not stability proof. A bounded aggregate-read candidate preserved exact values and passed 51 boundary/compatibility checks but reached only 34/50; its additional codec was withdrawn. In that run every claim route logged ready within 648 ms while outer hook claims reached 774 ms. The next bounded capture separates execute/fetch, request-thread entry/exit and outer hook return, paired by delivery, before another source change. Proxy/scheduler attribution is unproved. No installed changes, deadline increases or release acceptance.

Follow-up attribution supersedes the aggregate candidate's initial withdrawal: paired captures reached 41/50 with raw fetch and 39/50 with the identical reviewed aggregate reader. Both fail acceptance. All refusals occurred before HTTP-result admission, never in final confirmation writes; cold registration still requires its durable intent. The aggregate reader reduced 100 snapshot reads from 1,068 to 306 ms and total 50-worker residence from 2,119 to 1,692 ms, so it is retained provisionally with its 51 passing parity checks. Writer acquisition time increased as reads completed faster; these overlapping durations are not additive elapsed time. Next accepted small change joins the initial session/generation lookup and disables unnecessary ORM synchronization for unchanged global expiry SQL. Scope, expiry and OpenCode caller regressions precede another clean load check. No deadline relaxation or installed update.

Rollout preflight: all three approved installed hotfix files match current integrated source byte-for-byte; existing iteration-2 backup and candidate hashes were verified. No dependency or integration reinstall is indicated. Recheck against the final merged revision before reconciling only those files. Wrapper health alone does not establish readiness: root must also verify initialized/ready, embedding, native custody and actual payload/ACK. Stage2 publishing remains after verified installed Stage1, with Stage1 as rollback floor.

Writer lookup/expiry correction passed causal RED and 74 lifecycle checks, but clean synchronized load still completed only 37/50; release remains blocked. Review then found best-effort trace/cleanup work starts even while correctness owns local writer admission. Holding that mutex across diagnostic reads was rejected because the existing paused-trace test requires later correctness work to proceed. The accepted next candidate is only an advisory early skip when the mutex is already locked, with existing DEFERRED/25 ms SQLite arbitration unchanged and expected busy refusal returning false/zero. Both concurrency directions must pass; this is not a new fairness or priority guarantee. No additional queue, configuration or deadline change.

Current acceptance checkpoint: the advisory trace/cleanup preflight passed 123 regressions, including the opposite-direction paused-trace contract, but clean synchronized load completed only 44/50. Exact request pairing then located substantial delay after request transmission and before ASGI entry; no proxy-bypass calls occurred. An instrumented 50/50 pass does not supersede the clean failure. Architecture approved one observer-free comparison of the current candidate with the service in a separate process, matching installed topology. The earlier separate-process failure predates the current read/writer improvements. All caller deadlines, 50 journeys and lifecycle assertions remain unchanged; process isolation alone is not a proven cause or fix.

The current observer-free separate-service comparison also failed: 40/50 completed and ACKed, ten claim refusals, all seven owned processes drained (`51cfaa18849a49f7af4c957936146b06`). Process separation is therefore insufficient for this candidate. A one-query exact-candidate/count alternative was rejected without a production edit: paired settled writer time worsened from 31.36 to 34.63 ms across 50 calls. The next actual writer-phase capture reproduced 42/50 completed and ACKed, eight refusals (`abf3334d540c49a08b6d0372a55a5b9c`); all five owned processes drained. Its query/flush/commit/cleanup attribution is under review. Release stays blocked. No blind repeat or installed update.

Cold-client cause reproduced on Python 3.13: the default HTTP opener eagerly initializes HTTPS/TLS for plain localhost HTTP. Fifty independent cold hook processes measured opener construction at median 229.14 ms / maximum 295.56 ms, while nested proxy discovery was median 0.158 ms. This explains a substantial client-side budget cost, not every prior threaded failure. Both hook integrations now have a reviewed local lazy HTTPS handler candidate that delegates original TLS initialization on actual HTTPS, retaining certificate/hostname verification, proxies, redirects and credential redirect restrictions. Corrected RED evidence: six failures demonstrated eager initialization; two were fixture route-parsing failures, and the initial HTTP redirect fixture did not actually redirect. The fixture is being corrected with route assertions. Twelve final boundary tests, affected callers and clean load remain required before acceptance. No installed update yet.

Lazy TLS qualification: all twelve corrected boundary tests pass. The affected run passed 753 tests with two skips and two state-write failures; both failed nodes subsequently passed unchanged contracts with transparent operation diagnostics. Original write failures remain unattributed and preserved. The fixed-source observer-free independent-process 50-message test passed all claim/emission/ACK/public-readback and health assertions in 18.77 seconds; all 90 tracked owned processes drained (`5b5bc70e91954c41b6875c6e8fea0553`). This qualifies that topology only. Original threaded load and remaining final validation, CI, merge and installed verification are still pending.

Release split: the original observer-free threaded synchronized case still fails on the TLS-fixed candidate (36/50; all 36 ACKed). PR312 remains blocked on that requirement. Root assigned the recovery developer a minimal independent lazy-TLS patch against current main, excluding combined REL-14/REL-15 and storage changes, with exact-base regression/CI before publication and merge. The performance developer retains the load issue and will move child assignment parsing before a second ready barrier for a more faithful process comparison. Neither that comparison nor the partial TLS release closes the threaded failure or unexplained atomic-write failures.

Independent TLS slice (`fix/hook-lazy-tls`, base `cf558114`): six exact-base reproductions fail for eager TLS initialization; all twelve boundary regressions and 667 affected tests pass. The small paired warm-call sample showed approximately 0–1.2 ms median overhead; review accepted it without adding shared caching. Required full validation is running. The revised process test stopped before release on two assignment-file PermissionErrors, with no hook requests and all 107 owned processes drained. A reviewed pre-release-only retry stays within its existing readiness allowance; underlying file denial remains unattributed. The original threaded failure remains open. A private complete ACK-transaction comparison is the next measured candidate, preserving validation, expiry, idempotence and transaction boundaries; no production ACK change is accepted yet.

Independent release checkpoint: [PR #313](https://github.com/rore/Pallium/pull/313) published at `14eccb74ac5b07776ea46b4bb8ab295d99258cd1`, with independent publication acceptance and workflow/import checks clean. Full main-base validation passed 6,629 tests with 45 skips and two expected failures; all 85 owned processes drained. CI is running; the additional installed two-hook-file scope is awaiting the human's answer. Preserve all three existing emergency service patches during this independent fast-forward. Corrected process qualification subsequently passed all 50 journeys with a 5.224 ms start spread. The private ACK rewrite saved only 1.829 ms across 50 settled transactions and was rejected without a production edit. One current-source separate-service/threaded-client comparison will isolate service placement; original threaded failure remains open.

Latest release qualification: PR313 is now at `3edb101125cd9966f669cc03ab8c603172363c41`, with CI run `38327515995`. Previous hosted failures exposed an unattributed delayed HTTP response and a cold-route arrival timeout in a cancellation fixture. The fixture now verifies a rejected, operation-free warmup before testing steady-state settlement; real SQLite, cancellation and deadlines remain unchanged. Bounded timing metadata is captured in failure logs. Six focused cases passed in 9.69 seconds, with all three owned processes drained. This is test isolation and diagnostic evidence, not proof that the historical delays were fixed. The combined performance candidate's final non-slow suite is running on frozen source. No merge or installed update has occurred.

PR313 merged at `428d796ff7e5d46768316017c9085128acfa5fb5` after CI `38327515995` passed Linux 3.12, Linux 3.13 and Windows smoke, workflow checks passed and no unresolved review threads remained. Development main is synchronized, preserving local roadmap and unrelated files. Installed deployment still awaits the already-asked two-hook-file scope approval; all three emergency service patches remain untouched. PR312's frozen combined full suite is still running. Neither the threaded-load failure nor historical timeout attribution is closed by this merge.

Combined qualification correction: the frozen full run mistakenly retained the focused runner's `-n 0` override instead of repository-default four workers. It reached 96% without visible failures but hit its unchanged 1,800-second outer watchdog; this is incomplete evidence, not a pass or a product failure. All 76 owned identities drained and guards were empty (`f2e71422830243048ad635e9e154b9a3`, stdout SHA256 `304015B53D159CC2D006267D355BC220CB2A512653F6541EC6DCEAB0604BCD86`). Preserve this result, checkpoint the candidate and merge the already-reviewed PR313 overlap before one final configured four-worker run. No production deadline changes.

Current investigation checkpoint (`1136a58a`): the private separate-service threaded scheduling comparison completed 50/50 at both the actual default 5 ms client switch interval and 1 ms. Maximum claim/ACK times were 663.066/84.699 ms and 719.159/92.191 ms respectively. The second arm required a separate invocation after correcting private wake-directory isolation; the default arm was not repeated. Both services retained their default interval, clients restored it, all owned children drained, and caller deadlines/assertions stayed unchanged. This did not reproduce the prior threaded failures or justify tuning; those failures remain unexplained.

PR CI `38364824821` failed on both Linux versions: a Codex retry-edge hook received `relay_busy`, a Claude durability setup registration returned false, and a reconnect retry-deadline assertion failed. The full matrix `38364892014` is already running; do not duplicate it. The existing Busy error conflates local mutex refusal, connection/setup deadline expiry, native SQLite exhaustion and successful BEGIN followed by deadline expiry. The incident owner is adding bounded, correlated test-only attribution without changing deadlines or refusal behavior; the performance owner is examining registration and full-matrix evidence. Local health/status/queue checks still return HTTP 200 with embedding healthy, which does not establish Relay receipt. No new installed changes.

Management rule: at each test result, review completion, handoff or user status
request, root checks actual agent state and resolves the next dependency. Resume a
completed agent with a follow-up task, not a message that leaves it idle. A worker
waiting for a root decision is root's active task. Report verified milestones and
new blockers; never describe pending transport as accepted work. Minimap refresh
remains deferred until incident stability; do not add unrelated work here.

## Open reliability bugs (updated 2026-10-12)

This is the current consolidated closure list, maintained by the Pallium manager.
The historical delivery and merge evidence below does not close these incidents.
Every row remains open until its regression passes, the reviewed fix is merged,
and the installed result is verified. Shared causes may close multiple rows with
one fix; do not create separate mechanisms merely to match the rows.

| ID | Bug / evidence | Owner and current state | Required closure evidence |
|---|---|---|---|
| REL-01 | Concurrent claims and ACKs exceeded their budgets; repeated authority reads and a reproduced AnyIO limiter handoff defect contributed avoidable work and unsafe capacity accounting. | Combined authority-envelope and upstream AnyIO fix passed the original observer-free shared-process 50-message test: 50/50, claim maximum 649.654 ms, ACK maximum 83.807 ms under unchanged 750/500 ms limits. Earlier failures remain preserved; full regression, CI and installed verification are pending. | Complete combined regression, merge and installed real-delivery verification. One load sample does not establish universal stability or explain every earlier refusal. No budget increase or blind rerun. |
| REL-02 | Retained Codex enrollment disappears while the service survives; subsequent reconnects fail. | Resolved idle-readiness failure permanently disabling the worker reproduced and corrected in `08b2f078` (229 affected tests passed). Approved local hotfix installed; service-owned idle wake delivered one real payload and hook ACK at 15:07:40 UTC. Earlier live failure trigger remains unproved; combined merge and broader acceptance remain open. | Same-service-epoch connection-loss reproduction becomes green; authenticated recovery preserves peer identity, continuity, and uncertain-I/O fences, without replaying application operations. |
| REL-03 | Messages remain pending and arrive much later, including old developer reports received here. | Performance/recovery owners share cause analysis; root owns integration. | Busy-to-idle and multiple pending messages on one endpoint progress through real scheduler, hook and ACK without loss or duplicate action; growing delivered history covered. |
| REL-04 | Live Relay operations take up to five seconds. | Performance developer, active; do not assume identical cause to REL-01. | Locate wait versus work; compare before/after under concurrent load and verify installed delivery. |
| REL-05 | Database lock failures and exhausted retries; retention unnecessarily holds the writer while doing later reads. | Reviewed fix integrated at `351ad670`; 33 retention checks pass. Writer interval sample 70.38 to 5.69 ms; total elapsed sample increased, so no overall throughput claim. | Fresh protection/lease checks and deletion correctness survive concurrent writes; measured writer hold reduction and contention regression. Historical live writer attribution remains open. |
| REL-06 | Heavy startup can block responsiveness; readiness must reflect completed initialization. | `relaydev` handed off reviewed startup fix; root combined validation passed, deployment pending. | Real lifecycle tests keep HTTP responsive during initialization, gate readiness correctly, and expose failure; installed startup verification. |
| REL-07 | Rebuild inventory performs repeated reads and hydrates already-indexed sources. | Reviewed fix integrated and combined checks passed. At 5,000 rows all-present sample improved 2,899 to 8 ms; deployment pending. | Eligibility, missing-tail, resume, cancellation and startup caller tests; comparable measurement. Single private samples are not live attribution. |
| REL-08 | Shutdown can skip cleanup after worker start/stop failure or close storage before active children drain. | `relaydev` handed off reviewed correction; root combined validation passed, deployment pending. | Start/stop failure and held-child caller regressions; actual workers drain before storage closes, including error paths. |
| REL-09 | Embedded NUL text exposes disagreement between SQL and Python length eligibility. | Reviewed fix integrated at `dc8b9798`; combined verification and deployment pending. | Preserve actual end-to-end eligibility at 39/40 characters and across pages, including Unicode and NUL; verify subsequent eligibility rechecks too. |
| REL-10 | Healthy service does not imply working native wake; generic `peer-mismatch` also represents absent registration and can obscure the initiating failure. | Missing status allowlist entry corrected in `0aaf20ff`, four HTTP regressions passed and approved installed correction verified. Bounded source-channel/maintenance failure logs added; installed status now exposes registered custody with no unresolved handles. Combined merge remains open. | Distinguish unavailable registration from actual peer mismatch, retain initiating failure evidence, and verify status reflects wake availability without claiming receipt. |
| REL-11 | Historical outage and remaining unexplained startup duration are not fully attributed. | Root + startup developer; investigation open. | Identify reproducible causes or explicitly document evidence limits; measure startup phases and prove relevant regressions. A 120-second allowance is mitigation, not closure. |
| REL-12 | Two old pending deliveries repeatedly receive native owner refusal despite healthy retained custody. Both exact target chats are archived, confirmed through supported archive listing; readable `notLoaded` alone was insufficient. | Bounded recovery review complete: current per-wake `read_thread` and hooks expose no archive signal, and owner refusal is untyped. No justified eligibility change yet; no resend or unarchive. | Needs authoritative messageability or typed refusal to use existing unreachable fencing while preserving payloads. Do not infer archival from age, `notLoaded`, or generic failure. Archived status is established; exact refusal attribution remains pending. |
| REL-13 | Downstream manager reports an agent ended an unfinished implementation turn after handling an empty wake, then needed direct resumption. | Reported turn completed normally after trace calls; runtime cancellation was not established. Exact continuation guidance and backward-compatible hook matching integrated at `d9bedaca`, focused tests pass. | Autonomous task-continuation witness remains unproved; text regression is not proof of agent behavior. |
| REL-14 | Full regression observed Claude registration still advertising ready after unusable credentials. | `incident_integration_review` owns the staged correction; real-lock RED reproduced stale ready. Exact-admission correction passed 22 focused, 216 affected plus corrected fixture and seven malformed-notice checks. Reader-compatible Stage1 is integrated in PR312 development; it emits legacy rows and no deferred notices. Stage2 checkpoint `3edac09a` passed causal RED and 38 focused checks with independent acceptance; final combined validation remains. Stage2 stays separate until installed Stage1 is verified, then rollback must target Stage1 or newer. Legacy publication refusal and historical attribution remain open; Stage1 alone does not fix them. | Deterministically exercise publisher-lock refusal through the hook and public state. Durable recovery must preserve newer valid registrations: generation alone is unsafe because it can be reused after deletion/restart. Verify actual Stage1→Stage2→Stage1 current-state compatibility without restoring stale state; no weakened authority or deadlines. |
| REL-15 | Full local regression observed a Codex repository switch leaving the previous session pin. | `discovery_contract_review` owns the correction. Real-lock RED proved new context cached with an old pin and wrong-scope history on the next turn. Initial prevention and legacy repair passed 281 affected tests with two skips. Final review found unqualified hook callers could revalidate the wrong association, and older writers could retain an association while replacing its context. Both are corrected with caller regressions and exact scope/context binding, integrated at `546dc733`. The combined full exposed only an outdated observer mock; its one-line signature correction passed the whole 90-test file. Separate file-write refusals remain unattributed and are not erased by later green runs. | Preserve real clocks and scope-generation fencing; prove next-turn recovery, existing poisoned-state repair, unqualified callers and rollback/re-upgrade through actual hook/history/pin paths. Verified warm resolution must avoid extra Git lookup. A later green run alone does not close an unexplained refusal. |

Execution: delivery performance and authenticated recovery are independent developer
lanes; relaydev finishes startup/cleanup. Keep source ownership explicit. Run heavy
private qualifications serially on this machine to avoid contaminating timings;
source analysis, implementation, and review proceed in parallel. Root merges the
lanes, runs combined validation, and owns rollout and live receipt verification.
Current implementation records are `service-performance`, `service-async-startup`,
and `codex-enrollment-recovery`.
Preserve installed configuration/data and use the approved installed restart wrapper.

Integration checkpoint: startup component `88004c9b` and recovery `ff8d9825` are
combined in development at `dcf2d0a3`; neither is deployed. Recovery has a genuine
same-epoch loss RED/GREEN, 34 recovery/guard checks, 86 worker checks, and 20 final
race/caller checks passing (overlapping selections, not an additive total).
Startup affected evidence is 214 passed / 2 skipped plus the two corrected fixture
nodes passing separately. Performance remains open: the diagnostic found about
755 ms of serialized correctness-transaction hold time during the failed burst;
commit execution was not the dominant tail. Accepted performance baseline
`b16d1467` and the NUL eligibility fix are now combined at `dc8b9798`.
The separate completion-capacity candidate passes 58 safety checks but fails
instrumented 24/50-message acceptance. It remains unaccepted and unmerged.
The next exact 50-message qualification disables heavy diagnostic observers
while preserving real caller deadlines and every delivery/ACK assertion.
Combined startup/recovery/inventory checks passed 228 cases plus one corrected
completed-checkpoint node separately. Reviewed checkpoint `4caecee8` records the
evidence; no installed change occurred. The observer-off 50-message check still
failed (19 completed, 31 claim refusals), so instrumentation is not the sole cause.
Retention and read-only native lock separation are now integrated locally at
`9db51338`. The latter has 104 passing focused checks, but does not resolve the
50-message failure. A two-slot admission experiment was withdrawn; original
capacity still produced 27 claims and no ACKs. The current simplification reuses
the exact claim's durable generation instead of duplicating correlation writes,
with native/recovery consumers and legacy behavior covered together. It remains
incomplete until load evidence passes. The canonical generation and native guard
correction is independently reviewed and integrated at `4fc8f457`, with 116
focused checks passing. Its clean load run reached 39 claims/emissions but only
three confirmed ACKs; this is not release acceptance. One private execution slot
is shared between lanes; no installed change has occurred.

Final acceptance must run the slow ordinary and synchronized 24/50-message
HTTP/hook tests separately: the default full suite excludes them. These bursts
use distinct endpoints; existing same-endpoint backlog and restart regressions
cover their functional contracts separately. Do not claim a combined
same-endpoint restart/load witness from these results.

Additional live incident, inspected October 12: message
`relay-msg-0717eb474c454a7698ab0adf071738cf` was prepared at 12:42:18 UTC,
repeatedly deferred as `native_unavailable`, and claimed/ACKed once at
14:25:25 UTC. The bounded trace is incomplete. This proves a delivery delay of
about 103 minutes, not its complete cause or duplicate claiming. It remains
part of REL-02/REL-03 installed recovery acceptance; no receive or resend was used.

## Historical execution status (reconciled 2026-10-07)

The closure follow-up is owned by relaydev in
`.agent-workflow/tasks/relay-recovery-closure.md`. On October 6 the user explicitly
approved automatic re-enrollment by the same surviving previously authenticated
MCP child after service restart. The reviewed implementation binds reconnect to
the original source/Desktop/ancestor identity and capability, retains durable
fences, retries verified startup gaps only (12 attempts/five minutes), and never
replays application operations. Independent smart source/harness review approved;
the full non-slow source baseline passed 6,239 cases, and the real Windows channel
cross-epoch fixture passed. PR #290 merged at `8c4f38a0` after green CI and
separate human result approval. Both stable clones are synchronized; the installed
wrapper restart and health/embedding/queue checks passed. Six installed
no-restart original/backlog journeys passed through real hooks with payload-only
recipient responses: lost claim response, ACK precommit failure and committed
ACK response loss. Their exact evidence is in the closure Work Record.
Restart qualification did not reach its first claim and is not a passing
witness. Review found registration can exceed its three-second deadline while
dispatch holds custody across multiple native exchanges. PR #291 reproduces and
fixes that contention without dropping previously authenticated custody or
weakening identity, unresolved-I/O or replay fences. Independent smart review,
the genuine Windows pipe regression and 6,269 local non-slow tests passed.
Initial Python 3.12 CI exposed a raw-HTTP test caller that ignores explicit
retryable SQLite backpressure; its bounded same-ID fixture correction passed
155 retained-wake cases and independent review. Fresh CI and separate human
result approval passed; PR #291 merged at `17f9304b`. Both stable main clones
are synchronized, and the supported installed wrapper restart plus independent
health/embedding/ingestion/queue checks passed. Installed restart qualification
has not started: a plain status read did not enroll its dedicated source, and
the corrected Relay read did not expose verifiable custody admission/ownership.
No fault or qualification message was armed; provisioning quiet requests were
released. Current native-source ownership is unknown, not an established busy
rejection or product failure. The closure Work Record retains the exact gap and
next safe step. Historical causality is unproven, and none of this source or
deployment evidence qualifies installed unattended restart recovery.
An October 7 Minimap incident reached a second hook emission/ACK only after app
fallback. The first native owner-result timeout and missing first emission are
distinct observations; existing host logs do not identify that hook's failing
stage. PR #294's reviewed passive exact-session observer merged at `0311aa61`
after separate human result approval and green CI. Both stable clones and the
installed service reached `f062cc72` before a bounded real-host observation.
One unloaded recipient's real SessionStart claim, emission and confirmed ACK
produced its exact payload-specific native response without a manual turn.
Hooks/configuration were restored and verified unchanged; the window is released.
This qualifies the observer, not automatic recovery or authenticated MCP transport.
Installed restart, scope-move and pre-hook lost-notification recovery, both
unexplained parallel test failures, historical attribution and native-source
ownership remain open. Exact evidence and the blocked next step are retained in
the closure Work Record; the umbrella remains queued.
The Dictation 13:32 hook did deliver and ACK one 1,125-character payload. The next
1,101-character payload plus headers did not fit its 2,400-character output cap;
that turn is not evidence of a missed hook. The earlier idle 12:54–13:32 interval
and historical incidents with incomplete traces remain unexplained.

The user assigned the follow-up recovery round to relaydev after an independent
acceptance critique. `.agent-workflow/tasks/relay-recovery-round.md` owns the
round, including the manager handoff. An actual SessionStart/HTTP regression
reproduced committed uncorrelated claims with lost response or failed ACK
stranding the wake fence after lease expiry, including scope move and restart.
The narrow implementation reuses bounded retained notification retry, preserves
active claims/committed ACKs and correlated replacement, and covers repeated
missed retry notifications followed by original/backlog receipt. Also in scope:
authenticated reconnect after a well-formed native tool failure, bounded dispatch
diagnostics, and trusted-local trace when no scope was injected/configured.
Independent plan and result review approved these boundaries. Whole-change
validation passed 6,071 tests with 34 skips and two expected failures; existing
legacy and protected behavior contracts remain unchanged. PR #286 merged at
`6b49ff75` after Python 3.12/3.13 full CI, Windows smoke, workflow and CodeRabbit
passed. Both stable main checkouts were synchronized; the installed restart
wrapper and independent health/status/queue checks passed with embeddings healthy.
The historical native-unavailable incident's first fault remains unexplained;
simulated failure recovery does not establish its cause or installed recovery.

Installed October 6 qualification used the existing dedicated receipt-only
Codex thread `01a10580-ac6e-74d2-8a1e-5bc79cf327f1`. An unloaded fresh send,
`relay-delivery-f5ce8226f1344e84973282bda67fedb5`, ACKed at 14:49:27.977578 UTC
and produced payload-only `RECOVERY_ROUND_NATIVE_6B49_91D4_OK` despite an uncertain
owner response. This is receipt evidence, not notification-loss recovery.
Next, a 45-second lock on only that test session prevented its first hook claim.
The same `relay-delivery-bbc66ebc9dc34ad8aa024ebd2ddb0b00` remained pending with
attempts=0 after its accepted wake. The service restarted with this original and
later `relay-delivery-07966b9f1ebe4a79bff08c894522a60d` still pending. A fresh
sender-side Relay read restored native custody; this is an explicit dependency,
not proof of unattended restart recovery without registration. Automatic recovery
re-notified the original at 14:53:53.194225 UTC; its hook ACKed at
14:54:01.831817 and the recipient emitted `MISSED_HOOK_RECOVERY_6B49_E271_OK`.
The backlog first respected target-not-idle, then queued at 14:54:22.901170,
ACKed at 14:54:32.150285 and produced `BACKLOG_RECOVERY_6B49_A87C_OK`.
Full paginated traces had no gaps. No manual recipient turn, receive, payload
lookup, resend or Relay reply was used; markers existed only in delivered payloads.
Independent smart result review accepted this limited installed witness.

Still unqualified on the installed host: actual pre-hook lost notification,
unattended restart and scope-move recovery. Real hook/HTTP/SQLite
regressions with simulated native transport cover those failure boundaries, but
do not replace their installed witnesses. New diagnostics identify native-tool-failed
at owner-result and peer-mismatch at reopen; they do not prove historical root
causes. Historical stranded-message incidents remain open; the umbrella stays queued.

New incident handed over by the manager: `relay-delivery-ba9b0b8b256140049f91095ea76af1e1`
remains pending, attempts=0, with no claim/ACK or endpoint wake reservation after
deployment. Its surviving pre-deployment trace records native_unavailable;
pagination is exhausted but trace truncation/gaps prevent a current causal claim.
The exact recipient is in a continuing active turn begun at 13:32:20 UTC, before
this delivery's 14:38:42 send. Idle-only activation must defer that active turn;
there is no expired-claim fence here. Older pending messages predate that turn,
so their missing original hook admission remains unexplained. Matching persisted
hook scope/endpoint and bounded payload sizes do not establish historical emission.
No resend, manual recipient turn, receive or ACK was used. Keep this incident open
until its specific hook/activation journey is explained; the dedicated success
does not close it. Already-running MCP children also retain the old scope-required
trace implementation until host/MCP reload; the installed source update alone
does not hot-reload them.

An October 6 incident confirmed that a
September 15 uncertain, unclaimed wake reservation blocked later messages to the
same Codex endpoint. A manual target turn recovered the backlog, but is not the
product fix. The isolated HTTP regression reproduces the permanent fence after
restart. The user approved spaced automatic re-notification, including the risk
of an extra empty turn from a delayed original wake. The correction in
`.agent-workflow/tasks/codex-wake-recovery.md` reuses the recovery sweep, persists a
60-second cooldown, requires fresh authenticated idle/unloaded eligibility, and
preserves claim/ACK exclusion and exact generation/scope checks. Combined affected
validation passed 596 tests; the full suite passed 6,014 tests with 34 skipped and
two expected failures. Independent technical review accepted the correction.
Human result review was approved on October 6. PR #284 merged at `bd1c39f6` after
Python 3.12/3.13 CI and Windows smoke passed. Both clean clones were synchronized;
the installed restart wrapper exited successfully, and independent health,
embedding and queue checks passed. Automatic recovery is covered through the
HTTP/hook caller surface; a new installed lost-notification witness is not claimed.

Separate Claude qualification found a conditional stale-registration defect when
socket credentials disappear. Its reviewed exact-scope revocation fix is included
in the same integration branch and combined validation. The installed Claude 2.1.278 does not
qualify the reported 2.1.290/2.1.291 behavior. Neither source review nor passing
existing tests establishes that live lifecycle witness.

An isolated actual-hook reproduction found that a 300 ms session-lock conflict
can make Codex SessionStart emit scope without claiming a pending Relay message.
The narrow correction shares the existing Relay budget across lock acquisition
and scope-recovery requests, retaining the emission/ACK reserve and the short
default wait for other state writes. The new HTTP regression fails on the old
100 ms limit and passes with one payload emission and ACK after brief contention;
held-lock and exhausted-budget cases remain unclaimed. This reproduces a failure
class, not the proven cause of the separate live `native_submitted` incident.
Independent review accepted the correction; final full validation passed 5,980
tests with 34 skipped and two expected failures. PR #283 merged at `f5dad2bd`;
Python 3.12/3.13 CI and Windows smoke passed with no review findings. Both clean
checkouts were synchronized, the installed restart wrapper exited successfully,
and independent health/status/queue checks returned 200 with embedding healthy.
The implementation and incident limits are tracked in
`.agent-workflow/tasks/codex-hook-lock-budget.md`.

On 2026-10-04, one live Relay delivery's Codex queue wake timed out at
05:59:36 UTC and the message expired at 06:09:05 with attempts=0. Later,
same-target cold→idle and another idle probe both ACKed with attempts=1.
Subsequent service health, status, queue, and embedding checks were healthy. No
resend or service/config change occurred during the investigation. The native
timeout cause remains unproved. Timeout diagnostics improve evidence only; this
does not establish delivery reliability. See
`.agent-workflow/tasks/codex-queue-timeout-evidence.md`.

A follow-up review confirmed a narrower pre-start recovery defect: when thread
start and durable release both fail, a local schedule marker blocks the surviving
prepared reservation. The fix covers worker-start failure and retained prewrite
deferral. Both HTTP failure-to-ACK regressions and 324 affected tests passed;
full validation passed 5,955 tests with 34 skipped and 2 expected failures.
Independent review and CI passed. PR #281 merged at `8422e988`; both clean clones
were synchronized and the installed restart wrapper exited successfully.
Independent health, embedding and queue checks passed. The implementation record
is `.agent-workflow/tasks/codex-wake-worker-start-recovery.md`. Existing submitted
or uncertain reservations remain fenced.

PR #277 merged at `d993f639`; required CI passed and the installed service was
updated and healthy. Real dogfooding then exposed unfinished recovery behavior:
an abandoned unclaimed wake reservation blocks later notifications, and a native
timeout followed by lost retained custody defers other recipients. These incidents
affect the reliability claim despite the successful idle/unloaded witnesses below.
Reservation recovery shipped in PR #280 at `01213c1d`; its record is
`.agent-workflow/tasks/codex-wake-reservation-recovery-v2.md`. Both clean clones
were synchronized, the installed wrapper exited successfully, and independent
health, embedding and queue checks passed. Local full validation passed 5,953
tests with 34 skipped and 2 expected failures. Final CI and independent review
passed. One unchanged Claude hook test encountered a busy ACK in Python 3.12 CI;
its exact local test and the single failed-job rerun passed, with no speculative
Claude code change. The original record preserves connection-repair history.
The connection repair shipped in PR #279 at `9454dd80`. Both clean clones were
synchronized and the installed wrapper exited successfully; independent health,
embedding and queue checks passed, and authenticated retained registration was
observed after restart. Local validation passed 5,949 tests with 34 skipped and
2 expected failures; CI and independent review passed. One existing hook test
failed in the initial Python 3.13 CI run, passed locally, and passed on the single
failed-job rerun; its cause remains unconfirmed. No speculative hook change was made.
The workflow-manager notice was acknowledged on its first claim at
2026-10-02 14:22:30 UTC, after the older reservation naturally expired and before
the PR #280 deployment. No reset or resend was used; ACK proves receipt, not action.
The user renewed approval for reservation recovery on 2026-10-02. Independent
plan review accepted recovery of new durable prepared generations, with an exact
atomic fence before either native wake path writes. Implementation and regression
validation, review and merge passed. Legacy reserved rows remain fenced until
their existing receipt or expiry reconciliation; this change never relabels them.
Database inspection distinguishes pending/expired delivery from confirmed hook ACK;
neither a native submission nor a healthy HTTP service proves message receipt.

One bounded Windows trial proved the full retained authenticated MCP path:
service-owned wake of a supported `notLoaded` Codex target, hook payload emission,
and one claim/ACK. The target returned a marker supplied only through the Relay
payload. Cleanup restored normal service health. This establishes that the path
works; it does not establish general connection lifetime or busy-turn safety.

Product integration shipped in PR #277 from `feat/codex-retained-wake-product`.
The approved behavior is default automatic wake on supported Windows Desktop
for registered Codex recipients across sender runtimes: check fresh Desktop state, select existing queue delivery
for loaded-idle targets or retained MCP for unloaded targets, and defer working
or unknown targets through the existing recovery loop. Never try the other path
after an uncertain attempt. The
check/send race makes non-interruption best-effort. Reuse the current scheduler,
durable reservation and hook ACK path; no new message store or scheduler.
Final focused regressions passed 74 cases, including both actual payload hooks and ACK.
Affected-test isolation failures were corrected and replayed; native validation had
one isolated transport failure that passed its exact rerun.
Normal default-on idle and unloaded paths both passed live payload-only marker
and hook ACK checks on one attempt, at 16:03 and 16:22 UTC respectively. The
unloaded check used ordinary authenticated source activity and a service-owned
wake, without a manual target wake or finite trial procedure. Latest validation:
115 retained-feature cases, 2 protected contracts, 4 setup checks, and 15 hook
deadline/lifecycle cases passed; independent reviews accepted the changes.
The initial product slice shipped in PR #277. Both Linux CI versions passed
5,902 tests with 72 skipped and 2 expected failures; Windows smoke and required
checks passed. The subsequent recovery fixes and remaining follow-up are recorded
above. New test chats use `pallium-test`.

An earlier 16:06 unloaded attempt claimed without ACK and expired. Its exact
cause remains unknown. A real delayed-response regression independently exposed
the arbitrary two-second hook cap; removing it within the existing eight-second
budget preserves emission/ACK reserves. The subsequent unloaded witness passed.
This does not prove universal transport reliability or atomic busy exclusion.
Broader platform/recovery roadmap work remains open. Earlier entries below are
historical checkpoints, including blockers that the successful trial resolved.

### Earlier shipped checkpoints

[PR #273](https://github.com/rore/Pallium/pull/273) merged the separately armed
unloaded-target trial at `9ad54da4d622030147b8e8161c92dec604f68592`. It binds
runtime-owned caller identity, suppresses ordinary native dispatch for the enrolled
endpoint, and spends a durable one-call fence before the Desktop write. The approved
trial can retain a live source; post-source-exit lifetime remains a separate claim.
Independent review and final-head CI passed. Both clean checkouts include the merge
at `dc78a30368299ead3d18d6ac971681c53211f59b`; the required installed wrapper and
health/status/queue/embedding checks passed.

The delegated target bootstrap returned not registered and exact discovery found
no endpoint. SessionStart explains its saved identity; no UserPromptSubmit marker
update, registration intent, or prompt-hook context was observed. The host's exact
reason is unknown. One interactive composer turn in the same disposable target is
needed to check registration before the timed trial. No trial authority was enabled
or payload sent. Genuine unloaded-target payload receipt, post-exit lifetime,
zero-child startup, and general busy-turn safety remain unproved.

[PR #270](https://github.com/rore/Pallium/pull/270) merged test-helper isolation
at `5ed3cf96342d61ff4d3740e800a86e0232f8c28b`. Claude hook tests now rebind wake
directories to temporary state and block unmocked HTTP on a helper-local copy;
installed bindings and process-global HTTP helpers remain unchanged. Caller
red/green coverage, independent review, final-head CI and a disposable-profile
Windows full run (5,771 passed, 34 skipped, 2 expected failures) support the fix.
Earlier intermittent test failures remain unexplained. Both checkouts were
synchronized; the required installed restart and health/status/queue/embedding
checks passed. This is test isolation, not live unloaded-wake qualification.

[PR #269](https://github.com/rore/Pallium/pull/269) merged the native `tools/list`
request correction at `0d82bffbbca551448389d12060854de5c7e0a331`: omit the empty
`params` object so Desktop uses its default. A private-pipe regression reproduced
the invalid-request error before the edit; independent review and final-head CI
passed. This corrects the identified request mismatch; live inventory lifetime
and genuine unloaded delivery remain unproved.

[PR #268](https://github.com/rore/Pallium/pull/268) merged advisory stale-message
reconciliation guidance at `7f4079274c1c7cd83ce17ca945caa7697aa47be5`.
Installed Codex and Claude skill copies match the bundled 3,054-byte guidance;
configuration was preserved. The bounded synthetic comparison demonstrated no
semantic reconciliation improvement, so this is instruction clarification, not
automatic stale-message recovery or completed unloaded-wake qualification.

The wake architecture review in [PR #258](https://github.com/rore/Pallium/pull/258),
sanitized native failure diagnostics in [PR #259](https://github.com/rore/Pallium/pull/259),
and SQLite wake authority in [PR #260](https://github.com/rore/Pallium/pull/260)
are merged and installed at `936f20aedf2a6bb7cd7b136cb5b1cc24a801529f`.
The required service wrapper drained the old owner before verified database and
legacy-file backups, then imported and verified all six reservations (four accepted,
two uncertain), preserving the legacy bytes. Restart, service, queue and embedding
health checks passed. This replaces reservation-file writes with transactional
SQLite authority; conservative native retry behavior is unchanged.
[PR #261](https://github.com/rore/Pallium/pull/261) subsequently shipped duplicate-aware
hook/MCP envelopes at `a91dac91d54941a91f0a04711e78a79061e2f27d`, with the required
installed restart and health checks passing. Claim-attempt metadata and stable-ID
guidance fit existing budgets; previews may shorten, with continuation preserved.
These fields do not prove prior emission or completed actions.
[PR #262](https://github.com/rore/Pallium/pull/262) shipped wake-health reporting in
the status API and existing dashboard Relay panel at
`2311fe0159553c113d1728b0aabf30c4e6a81e51`. The installed wrapper and service,
queue and embedding checks passed. Scheduler health and uncertain deliveries are
reported separately; this does not establish recipient reachability.
[PR #263](https://github.com/rore/Pallium/pull/263) adds a 24-hour default for new
messages and replies, explicit null for durable delivery, and dashboard age counts
at `f940e02b6abf9bf174658e6aa8fffc6cae2bfaf3`. Existing assignments and expiry
values remain unchanged, including idempotent retries. Physical history retention
and disposition of old durable backlog remain separate work; no purge is included.
[PR #264](https://github.com/rore/Pallium/pull/264) safeguards the existing trace
cleaner at `e9eaefee9a6efd3df91f160a689950ee7fc4e3fc`: an attempt with active,
reserved, missing or mismatched delivery references is retained. Eligible terminal
diagnostics keep the existing 30-day/cap policy and 64-row batch. Message payloads
and stable IDs remain untouched. Earlier discovery incorrectly said no time-based
trace cleanup existed; the shipped Work Record now records that correction.
The one-lifetime-rescue retry proposal was deferred because its permanent state
offers limited recurring recovery. Retry behavior is unchanged.
[PR #266](https://github.com/rore/Pallium/pull/266) adds fixed diagnostic stages
for individual inventory-response validation checks. Response acceptance,
authority, custody and public failure behavior remain unchanged. Both Linux CI
suites and Windows smoke passed; the installed service wrapper and health,
queue and embedding checks passed. A bounded trial localized rejection to the
first response envelope. [PR #267](https://github.com/rore/Pallium/pull/267)
adds fixed labels for two exact known error envelopes without accepting either
response or changing authority. It is merged and installed at
`dfcd35abc5690cfb88f91bf7a7646cc3b6871c1f`; required CI, independent review,
installed restart, and service, queue and embedding checks passed. The actual
Desktop error branch remains unproven. The next bounded diagnostic trial must
verify the registration tool through discovery before arming; model self-report
alone does not establish catalog absence.
Unloaded-session delivery and the source-child lifetime witness
remain unproven; this rollout makes neither claim.

The Windows/Linux Claude wake foundation, loaded-task Codex wake, Codex first-run
setup, MCP recovery integration, and live no-manual-turn reply/remediation journey
are shipped. RW-024 removed unsafe unattended Codex cold resume: unloaded tasks
retain Pallium's pending next-turn delivery instead. PR #209 added exact-delivery
hook-start, payload-emission, ACK, and bounded-failure evidence. An installed
busy-to-idle witness then delivered and ACKed once after one native submission;
that proves the normal safe-turn path, not recovery from uncertain native failure.
RW-031 diagnostics are shipped. The reviewed supported public CLI and app-server
surfaces still lack owner-routed cold activation and caller-idempotent admission/
readback for uncertain public-CLI submissions. Replaying an execution descriptor
would start another runtime, not wake the Desktop-owned task. A private Desktop
owner bridge is now experimentally feasible: one combined native-plus-owner cold
trial delivered through the trusted hook once, without proving loading causality
or busy-safe admission. Its integration is separate from the supported public-path
limit and does not change shipped loaded-task behavior. RW-034 separately reduces avoidable
hook response timeouts for exact loaded-task wakes; it does not change native
uncertainty or make cold activation automatic. Session-to-work associations are
complete. RW-035 has a shipped forward exact-claim fence fix; the
umbrella remains queued for other runtime and platform qualification below.

The optional Codex MCP Desktop bridge **inert lifecycle foundation** shipped in
[PR #252](https://github.com/rore/Pallium/pull/252) and was installed at
`bce09405353f7c9d968d12f3c57c260db993f0a9` on 2026-09-27. Installed service,
queue and embedding health passed. It remains off by default and makes zero
Desktop/service bridge calls. This milestone is not automatic unloaded delivery.

The Windows **shadow-only enrollment and observation** slice shipped in
[PR #255](https://github.com/rore/Pallium/pull/255), merged at
`2e3f9316f20fdbb6d6c81f18f967f679ef6321c7`. It adds a protected local pipe,
one explicitly approved pair, finite process-local enrollment and read-only Relay
observations. Real stdio-to-native-pipe-to-SQLite coverage and Linux/Windows CI
passed; the final local suite passed 5,461 tests. It remains off by default.
A finite shadow-only policy was provisioned for the supervised trial below and
then revoked and removed; no wake action was enabled. Actual native
anchors remain held because their trace correlation is insufficient. Desktop
child lifetime and zero-child bootstrap remain unqualified. Trusted-child
assertions use the documented trusted-local boundary, not Desktop attestation
or isolation from compromised same-user code.

The first supervised 2026-09-28 trial reached one genuine user turn in the existing
disposable Desktop chat. Neither dedicated shadow tool was exposed, so the chat
stopped without enrollment, status calls or retries. This result alone does not
distinguish project trust, cached configuration or an MCP launch failure. Existing
trial logs did not establish the cause. Subsequent source inspection and the
fresh-chat trial below established a usable configuration-loading path; do not
repeat the existing-chat experiment or assume a per-server restart control.

Cleanup completed through the shipped revision-checked provisioning command and
required service wrapper: the pair was revoked, the service drained, and exactly
five owned trial files and two empty directories were removed after identity,
ownership and hash checks. Normal service, embedding and queue health passed.
Global configuration was preserved; model, effort, approval and effective access
were unchanged. Raw permission-profile labels and duplicate entries differed, so
the full context was not byte-identical. No Relay message was sent; target pending,
claimed and matching reservation counts remained zero. Child startup/lifetime,
natural unload and zero-child bootstrap remain unqualified. Next-natural-turn
fallback does not satisfy automatic unloaded wake. No live configuration remains
armed; the recurring manager follow-up was paused at that stage.

The later fresh-chat trial in the separate approved test project exposed both
shadow tools before policy provisioning. App-created/delegated turns did not
register a Relay endpoint: matching Codex source runs UserPromptSubmit for user
input but not function-call-output or inter-agent input. One ordinary user message
then established a provider-confirmed endpoint, with pending/claimed/reservation
counts zero. The user turn also supplied a broader writable Documents/Codex root;
the current host-provided context was accepted and preserved, not described as
unchanged from the initial delegated turn. Normal project trust was preserved.

A finite policy for that exact fresh pair was provisioned and service health
passed, but automatic approval review rejected enrollment before execution because
the target retained the user's earlier no-tools instruction. Status was not called
and no retry occurred. That attempt did not test enrollment. The policy was revoked through
revision-checked provisioning, service storage removed, and normal service,
embedding and queue health verified. A failed stop caused by an already-absent PID
was recovered with one evidence-based invocation of the required wrapper.

At that checkpoint, project cleanup was incomplete: Windows accepted deletion of the exact owned
config and empty directory, but the directory remained visible and reopening it
returned access denied. A retained handle is possible, not proven. Original file
identities, owner and config contents were verified; a narrowly reviewed exception
allowed only the recorded additive ACL changes while preserving parent permissions.
No ACL reset, forced handle close, shared process kill or Desktop restart occurred.
Native status queries subsequently proved STATUS_DELETE_PENDING for both paths.
Normally archiving only the idle disposable released them; native absence checks
then passed, without a Desktop restart or permission change. The user explicitly
lifted the earlier no-tools restriction in the restored chat.

The next finite window still did not exercise enrollment: the restored chat had
no callable shadow entry, despite the earlier fresh-load catalog success. That
evidence was incorrectly reused across archive/restore. Ordinary MCP servers were
ready in the bounded log evidence; no shadow-server startup was recorded. This
does not establish a native enrollment failure. Cleanup archived the idle test
chat before project-file deletion, revoked the exact policy, removed both temporary
directories and restored normal service with all health checks passing. Global
trust, settings and empty delivery/reservation state were preserved. Shadow
authority is off and namespace cleanup is complete.

The replacement fresh chat remained loaded through an explicitly authorized
enrollment/status attempt. Both actual MCP calls succeeded exactly once: enrollment
returned `enrolled` / `ok` with a 300-second grant; status returned `inactive` /
`observed` with 294 seconds remaining. This proves eligible Desktop-launched MCP
startup, inherited capability presence, genuine request metadata and enrollment
through Pallium's protected native pipe. Neither shadow tool connects to Desktop;
the result does not prove use of Desktop's app-tools connection or automatic wake.
The idle test chat was normally archived before cleanup. Revision-checked revocation,
owned-file removal and the required service restart completed; service, embedding
and queue health passed. Temporary authority/configuration are absent, global
configuration and effective caller settings were preserved, and target pending,
claimed and matching reservation counts remain zero. Child lifetime/unload and
zero-child bootstrap remain unqualified. The next architecture decision is executor
availability; do not repeat enrollment or restored-chat configuration investigations.
The design document's header still describes shadow implementation as under review;
PR #255 and this live enrollment result supersede that stale delivery status.

A user-operated Desktop restart on 2026-09-28 was captured by an independent
PowerShell process. The capture shows the old Desktop/app-server/MCP processes
disappearing, followed by a new Desktop at 14:33:39 UTC and new MCP children at
14:33:50 UTC. Surviving process identities resolve to the installed Pallium MCP.
However, Desktop logs show automatic chat restoration beginning at 14:33:49 UTC,
before the first captured MCP child; Pallium became ready for a restored chat at
14:33:58 UTC. This qualifies ordinary MCP startup during Desktop chat restoration
without a new user turn, not executor availability with zero loaded chats. A
null-thread MCP inventory request also overlapped this startup, but the capture
does not attribute individual children to that request or establish its lifetime.
No bridge opt-in, grant, wake action or settings change was made for this witness.
Do not repeat the same restart while automatic restoration confounds the question.

Exact-version source resolves the separate discovery-lifetime question. The
[status handler](https://github.com/openai/codex/blob/0d9c7cbfa6cf1489f55a8a9542b75ddd2c061807/codex-rs/app-server/src/request_processors/mcp_processor.rs#L268)
uses a threadless snapshot for a null-thread request. Its
[snapshot implementation](https://github.com/openai/codex/blob/0d9c7cbfa6cf1489f55a8a9542b75ddd2c061807/codex-rs/codex-mcp/src/mcp/mod.rs#L485)
creates a local eager connection set, cancels startup at completion and returns
only snapshot data; connection destruction cancels its client token. This path
cannot supply a persistent executor. It does not prove which captured PID served
which request, or rule out every other host mechanism. The earlier supported-only,
child-owned custody constraint is superseded by the reviewed continuation below;
a detached helper or competing Codex runtime remains outside scope.

The task owner accepts useful partial coverage after normal use of one chat.
Before-first-chat availability after Desktop restart is not a prerequisite.
The accepted next slice is a default-off, inventory-only connection owned by the
existing Pallium service after explicit handoff from a legitimate MCP child.
Independent security review required distinct finite inventory authority, separate
from shadow enrollment and endpoint possession; the corrected plan is accepted.
Implementation shipped in [PR #256](https://github.com/rore/Pallium/pull/256); see
the [Work Record](../../.agent-workflow/tasks/codex-service-custody.md). The
default-off, inventory-only service-custody foundation was installed on
2026-09-28. It permits only the reviewed finite handoff for fixed inventory reads.
The child-exit custody witness is pending; this installed transport foundation does
not establish unloaded-recipient delivery or wake authority.

One exact child/service/Desktop process tuple may authorize one RAM connection.
Only fixed native tools/list is permitted in this slice. A bounded disposable
trial must observe the originating child actually exit, then successfully list
on the retained service connection. Archive alone is not exit evidence. A passing
transport test leads directly to a separately reviewed unloaded-recipient delivery
witness; it does not establish wake authority or delivery by itself. Service loss
requires normal-use bootstrap; Desktop loss invalidates the old connection.
Persistent credentials, automatic zero-child startup and an exhaustive restart
matrix are deferred. Existing uncertain-action fences and deferred busy-turn
semantics remain unchanged. No live handoff or new wake is armed; the manager's
recurring follow-up is active.

Remaining work:
- Qualify actual Desktop child startup/lifetime for the
  [optional Codex MCP Desktop bridge](../../docs/designs/codex-mcp-desktop-bridge.md);
  live enrollment passed as recorded above. One private offline exact-owner launcher-exit check passed:
  the child survived launcher exit, exited within a finite bound, and fake-baseline
  restoration cleaned only the exact owned files and root. This proves only the
  tested offline launcher-exit and cleanup path. Read-only inspection of installed process
  topology confirms ordinary Desktop → Codex → venv launcher → base interpreter MCP
  startup; it does not prove Desktop steering/cancellation, live inert-child lifetime,
  usable Desktop connection, or zero-child bootstrap. Earlier temporary opt-in attempts
  remain inconclusive: Desktop rejected programmatic initialization, and manual
  preparation initially ended before an observed user turn. The subsequent
  first supervised user turn found neither dedicated tool; the later fresh-chat
  catalog and registration checks passed as recorded above. Namespace cleanup is
  complete, including the successful replacement trial. Existing `env`/`env_vars`
  and server eligibility already express inert
  opt-in, so no new setup feature is needed. Live configuration remains held.
  Qualify service-owned connection lifetime after normal-chat bootstrap, then
  unloaded-recipient delivery. Automatic startup before any chat is deferred;
  host-safe admission including cold-to-busy races remains a separate requirement.
  New grants or generations must not bypass uncertain action fences.
  This is work in progress, not shipped automatic unloaded delivery.
- Qualify still-unproven interrupted/restart combinations with a bounded matrix
  of runtime, platform, interruption, existing evidence, and missing witness.
  Reuse passed recovery tests and live witnesses; do not repeat them without cause.
- Qualify Claude/Codex on macOS when that platform is needed.
- OpenCode V2 automatic wake has a happy-path live witness on the native Windows CLI
  and desktop 2.0.24. The configured-model witness delivered the exact Unicode
  payload unattended and verified its response and ACK; all 87 existing sessions
  and settings were retained. The earlier 2.0.22 qualification is historical. PR #292
  is merged and its consumer switch is installed. The V2 native inbox uses stable
  native IDs, coordinated by Pallium's existing endpoint state and one scheduling
  fence; there is no separate plugin pending-delivery ledger. PR #297's minimal
  assistant-directory ownership guard is qualified and merged as `178fea16`;
  OC-3 capture idempotence merged in PR #306 as `2ac9e2b6`. Installed deployment and
  broader restart/OS qualification remain separate. Remaining wake-anchor,
  lifecycle and latency gaps are tracked in
  [Fix OpenCode plugin reliability](fix-opencode-plugin-reliability.md); the
  happy-path witness does not qualify overall reliability. Owner: `@pal-dev1`; Work Record:
  [OpenCode Relay wake](../../.agent-workflow/tasks/opencode-relay-wake.md).
  Preserve V1 compatibility; the everyday installed integration is V2. Codex/restart ownership remains
  with relaydev.

OpenCode activation remains a dependency of Copilot expansion; its native Windows
2.0.24 V2 wake has a happy-path witness. The assistant-directory guard merged in
PR #297 and OC-3 capture idempotence merged in PR #306. OC-2/OC-5 disposal fixes merged in PR #302;
remaining reliability gaps stay open in [Fix OpenCode plugin reliability](fix-opencode-plugin-reliability.md). These residual gates do
not block activation capabilities, traces, work associations, or future
Claude/Codex workflow examples. A new correctness incident takes priority if one is found.
The milestone and incident history below preserves evidence; it is not a list of
new implementation tasks.

### Current readiness tracks

| Track | Owner | Next action |
|---|---|---|
| `RW-027` hook readiness | `.agent-workflow/tasks/codex-integration-readiness.md` | Keep hook definition stability and review visibility observable; run the real installed Codex task witness after stable reinstall. |
| `RW-028` Codex MCP exposure | host recovery follow-up | Same-host/project tasks expose different tool catalogs, including zero Pallium tools after successful hook delivery. Treat this as a Codex host registry/rehydration blocker; do not infer MCP health from hook/service health or add a speculative Pallium workaround. |
| `RW-029` stranded split identity | guarded Relay operations | Use the offline repair manifest for reviewed per-delivery dispositions. Version 2 can explicitly suppress a finite expired claim; it still refuses adoption, active or ambiguous claims, and automatic cleanup. |
| `RW-030` Claude install drift | installed integration lifecycle | Repoint the user-scoped Claude MCP and hooks from the development checkout to the stable installed checkout in the coordinated post-merge install window. Existing hosts retain old subprocesses until their normal restart. |
| `RW-031` Codex native activation reliability | automatic recovery blocked by upstream Codex contract | Actionable trace guidance and bounded failure/timing diagnostics explain retained uncertain submissions and help classify the next occurrence; they do not repair one. For uncertain Codex submissions, use a normal user prompt directly in the existing task: observed app-message delegation did not invoke UserPromptSubmit. Keep the delivery pending; do not resubmit or launch a second runtime. This is manual recovery, not automatic recovery. Revisit automation only if Codex exposes owner-routed cold activation plus idempotent exact-submission admission/readback. |
| `RW-032` compaction-safe Relay scope | recipient context continuity | A loaded Codex wake delivered and ACKed once with trusted scope in the hook-injected context; same-turn compaction later omitted that scope and blocked a scoped follow-up. Investigate runtime-owned identity/tool context or supported trusted reinjection. Do not recover authority from cwd, historical transcripts, or forwarded metadata. This is not a native wake failure or duplicate delivery. |
| `RW-035` loaded Codex claim correlation | `.agent-workflow/tasks/relay-late-claim-fence.md` | Forward fix shipped and installed: a matching exact claim stores same-generation recovery evidence atomically, and an in-flight old callback cannot correlate a replacement fence. Focused callback-loss through recovered delivery, race, migration/restart, and ACK tests pass. Historical accepted/null-correlation reservations remain fenced; the old incident cause is unproven and no live uncertain-native recovery is claimed. |

The dashboard diagnostic is shipped as read-only evidence, not repair. Do not bulk-repair stranded deliveries. The real installed witness gate remains required for send -> next-turn hook claim/injection/ACK -> reply and work-reference attach/detach qualification.
## Summary

Make immediate activation the default for every resolved Relay recipient while
preserving durable next-turn delivery as the automatic fallback. The sender does
not choose a delivery mode: Pallium persists first, uses the recipient runtime's
native wake mechanism when safe, and otherwise leaves the delivery pending.

## Why

Relay does not remove manual coordination if the user must prompt an idle recipient
merely to discover its mail. Claude Code, Codex, and OpenCode expose different
mechanisms for starting or queuing a turn, so Pallium needs small runtime-specific
adapters behind one observable delivery contract.

## Primary Product Outcome

After one user instruction, a developer session and an architect/reviewer session
can carry a bounded implementation-review-remediation exchange through explicit
Relay messages without the user prompting either recipient to check for mail. Each
send wakes the addressed live session, enters its model-visible context exactly
once, and can receive an explicit delivery-derived reply. The user re-enters only
for a permission, product decision, unresolved failure, or requested final result.

This is the main wake validation journey, not a later demo. It does not make
Pallium a team manager: the user still starts the work, agents explicitly choose
when and whom to message, and Pallium only persists, addresses, activates, and
reports delivery. `fix-relay-claim-before-context-emission` (`RF-005`) is a release
prerequisite because both wake and fallback must be loss-safe.

### Historical milestone order (user priority, 2026-08-31; OpenCode sequence superseded by PR #292)

1. **Codex↔Codex dogfood first — Windows-qualified:** the existing Codex architect and developer
   sessions exchange a bounded task → result → review → remediation/verdict
   sequence through Relay alone. Send and reply activate the exact recipient in
   both directions; neither the user nor either agent sends a separate ping,
   invokes a wake command manually, or uses an app messaging tool to advance the test.
   Qualify the actual sessions used for work, not just disposable TUI substitutes.
2. **Claude↔Codex next — Claude wake qualified on Windows and Linux:** the
   cross-runtime journey is proven without a manual recipient turn. Claude macOS
   and Codex macOS qualification remain S4; neither reopens milestone 1.
3. **OpenCode later (original sequence):** add its adapter after the first two milestones.

Milestone 1 includes the smallest persist-first coordinator needed by Codex,
dedupe, correlated admission, loss-safe active-writer fallback, wake/fallback claim-race protection,
restart/ambiguous-outcome recovery, expiry, bounded bursts/replies, and visible
fallback reasons. Exercise these through caller-surface regression tests plus a
live no-ping round trip; update local Codex integrations before acceptance.
Use the existing Relay developer session for implementation and architect review,
not a substitute subagent. Other runtimes retain next-turn delivery.

This is an independently acceptable dogfood milestone, not completion of the full
wake feature. Enable only qualified runtime/OS combinations; cross-platform
support remains required and unqualified combinations stay passive.

## Delivery Contract

1. Persist the message and immutable per-recipient deliveries before attempting
   activation.
2. For every resolved recipient, use its advertised wake capability by default;
   there is no sender-side `wake` option.
3. If idle, start a new turn. If busy, queue a distinct turn at the runtime's safe
   boundary; never steer Relay text into an active human-owned turn.
4. Mark the delivery complete only when the runtime confirms admission into the
   recipient context. A trigger request or transport acknowledgement is not enough.
5. If activation is unsupported, disabled, unavailable, stale, or fails, leave the
   same delivery pending for the existing next-natural-turn path. The immediate
   S2 contract gate below may add a terminal outcome only from separate,
   proven-terminal delivery evidence. Destination health never terminalizes an
   existing delivery; missing wake capability, ambiguous transport, and temporary
   runtime absence remain durable fallback, not failure.

Track activation separately from the durable delivery lifecycle. Operationally,
Pallium must distinguish `queued` (persisted, not activated), `triggered` (a runtime
turn was requested), and `delivered` (the runtime admitted the message). Never call
a message read, understood, or used. Stable message and delivery IDs must make wake
retries, runtime callbacks, and hook fallback idempotent.

## Runtime Feasibility and Constraints

Deeper source review on 2026-08-26 corrected the initial Phase 0 verdict. The
installed versions recorded then were Claude Code 2.1.250, Codex CLI 0.149.1, and
OpenCode 1.18.19 on native Windows; OpenCode has since moved through the historically
qualified 2.0.22 release to the supported native CLI and desktop 2.0.24.

| Runtime | Current verdict | Proven mechanism | Remaining qualification |
|---|---|---|---|
| Codex | **Windows and Linux exact-session wake proven for runtime-loaded tasks; Windows overtaken-wake suppression proven** | Pallium writes a generic trigger through `codex queue --thread` from a validated neutral Codex home. The cross-process watcher starts a real turn when the target is loaded; for an unloaded target, Pallium keeps the Relay delivery pending until a later supported hook turn. Native unloaded-queue persistence is not claimed. The installed UserPromptSubmit hook claims and injects only after admission, and blocks an exact internal wake without verified rendered delivery before memory or model work. A recognized wake whose payload or block output fails before emission exits 2 without ACK; any existing claim remains recoverable after its lease expires. This failure contract has simulated caller-surface and subprocess coverage, not separate installed-host qualification. An installed Ubuntu 24.04 / WSL2 witness with Codex 0.153.4 proved loaded exact-session automatic wake, hook delivery, and return to idle. | Windows and Linux loaded-task live send → wake are proven. Windows atomic reply, reply-only idle-sender wake, and a no-manual-turn remediation round trip are proven. Do not claim unattended unloaded-task resume without a supported runtime workspace API; qualify macOS and remaining interrupted/restart variants before calling the adapter cross-platform complete. |
| OpenCode | **Native Windows CLI/desktop 2.0.24 happy-path wake witnessed** | OpenCode's native inbox admits exact sessions with stable native IDs; Pallium coordinates pending work through existing endpoint state and one scheduling fence, without a separate plugin pending-delivery ledger. The configured-model live witness verified unattended exact Unicode response and ACK; all 87 sessions and settings were retained. Shipped isolated native lifecycle E2E passed on 2.0.24; this does not qualify overall reliability. | [Fix OpenCode plugin reliability](fix-opencode-plugin-reliability.md) tracks remaining wake-anchor, lifecycle and latency gaps. OC-7's assistant-directory guard is qualified and merged in PR #297; OC-3 capture idempotence merged in PR #306. OC-2/OC-5 merged in PR #302. Installed deployment remains separate; OC-1/4/6/8 remain open. |
| Claude Code | **Windows and Linux S1A+S1B qualified** | Installed Windows and Ubuntu 24.04 / Claude Code 2.1.250 witnesses proved native peer Relay → exact restart-surviving capability → Stop claim/injection/ACK → Claude reply without another human prompt. Linux used the installed UDS path. | Installed UDS qualification on macOS remains S4. |

**Claude registration foundation:** Windows and Linux S1A+S1B are live-witness qualified: trusted-local exact-session persistence, write-ahead intents, fail-closed rehydration, and event-driven idle-pending reconciliation survived the installed witnesses. The Linux witness used Ubuntu 24.04, Claude Code 2.1.250, and the installed UDS path. No DPAPI, silent time expiry, or lifetime redesign was added. Installed UDS qualification on macOS remains S4.
### Admission handshakes to preserve

**Codex:** Write one generic trigger through hidden `codex queue --thread` from a validated resolved local Codex home. The owning runtime watcher starts a loaded task; for an unloaded task, Pallium keeps the Relay delivery pending until a later supported hook turn, without relying on native queue persistence. After admission, the installed UserPromptSubmit hook claims and injects the bounded backlog under the target's pinned scope, then acknowledges hook delivery. If the exact internal wake cannot render a verified delivery because the response is empty, unavailable, malformed, timed out, or invalidly scoped, the hook emits Codex's native structured block decision before memory or model work. Queue launch failure leaves the delivery pending for startup/periodic recovery or ordinary next-turn delivery. No private App Server attachment or Codex state lookup is required.

**OpenCode:** the installed V2 plugin uses OpenCode's native durable inbox and
stable native message IDs. Pallium coordinates delivery with its existing endpoint
state and one scheduling fence; there is no separate plugin pending-delivery ledger.
The earlier Windows 2.0.22 qualification is historical. The supported native CLI
and desktop witness used official unmodified 2.0.24; the configured-model live witness
verified an unattended Unicode response and ACK, and shipped isolated native
lifecycle E2E passed on 2.0.24. The assistant-directory ownership guard is qualified
and merged in PR #297; OC-3 capture idempotence merged in PR #306. Installed
deployment remains separate. Reviewed wake-anchor, lifecycle and latency gaps remain open
in [Fix OpenCode plugin reliability](fix-opencode-plugin-reliability.md); this
happy-path witness does not qualify overall reliability.

**Claude Code:** Native peer frames start text turns but Claude 2.1.250 classifies them as internal `isMeta` events, so S0/S0.5 are misqualified for UserPromptSubmit admission. Claude reproduced S1A Stop continuation: every Stop registers idle; a non-recursive Stop makes one exact-scope `/relay/turn` with authoritative storage `max_chars=2360`, route admission marks busy, and renders the returned claimed set plus any compact backlog notice inside a fixed 2,400-character output budget, emits that exact set to stderr, then ACKs the emitted claims individually before exit 2 requests one continuation. Partial failure leaves unACKed claims lease-recoverable; all failure exits 0 and every non-continuing path re-registers idle after route admission. Storage budgets the exact emitted control template. `has_more` and `remaining_count` remain pending and are qualified under S1B rearm/continuation; the S1A witness historically proved one bounded batch. The `stop_hook_active` continuation Stop re-registers idle, ingests, and exits 0 without re-probing. No MCP/pin change belongs in S1A; durable state/reconciliation is S1B.

Each live session advertises only capabilities its integration actually proves:
passive, idle_wake, and busy_queue. Missing, expired, disabled, or lost capability
selects durable fallback. Runtime names are never global capability claims, and an
exited arbitrary process is not wakeable merely because its conversation can be
resumed by launching another process.

### Remaining production gates (priority updated 2026-09-07)

Gate each runtime independently. Claude Windows and Linux live wake evidence is
complete; only installed UDS qualification on macOS remains for that adapter.

1. **Codex-first product gate:** Windows exact-session wake is proven for tasks
   loaded by the Desktop-owned runtime through the cross-process queue watcher.
   Unloaded tasks retain Pallium's pending delivery until a supported hook turn;
   native queue persistence and unattended cold resume are not claimed. A real `codex:@relaydev` run received
   two outstanding attributed deliveries in one wake batch and atomically replied
   to both without a user ping or approval prompt. On 2026-09-08, live message
   `relay-msg-f07d6ebe0c054e4fa38872ef8a3393d7` reached the real concurrent
   Codex owner; its delivery-derived reply resumed the idle sender solely through
   Relay. The sender then issued remediation
   `relay-reply-5b5235201e41cfa596205f632ffbac301d41bae78c5628a9bec52a6e136a7710`,
   which the recipient admitted without a manual turn and answered `APPROVE`; the
   reply again resumed the idle sender. Sender-side reply admission and the bounded
   no-ping remediation journey are therefore proven. RW-026 closes the concrete
   wake-correlation diagnosis gap without changing delivery behavior. Remaining
   value gates are interrupted/restart reliability and macOS qualification when
   demanded.

2. **Claude Code production gates:** Windows S1A+S1B and installed Linux UDS
   live journeys are proven. Installed UDS qualification on macOS remains S4.
3. **MCP receive lifecycle foundation — shipped and Windows-qualified:**
   PR #99 provides runtime-owned per-call task identity and integration reload;
   the S2 evidence below records the completed recovery gate. It remains a
   separate fail-closed recovery path and must not be mixed with hook delivery.
   Qualification on another runtime/platform requires its own evidence.

### Next execution order (updated 2026-09-22)

RW-017 durable-by-default delivery, RW-016 installed-service metadata repair,
RW-018 taskkill race recovery, RW-019 Relay load resilience, and RW-020
diagnostic/restart readiness are merged and Windows-qualified. RW-026 closes the
concrete wake-correlation diagnosis gap without changing delivery behavior. The
2026-09-08 live gate completed sender-side reply admission and the no-ping
remediation journey.
The closed-recipient lifecycle slice subsequently shipped in PR #148 and
first-run setup qualification completed on 2026-09-08. Retention cleanup is paused
pending operational evidence. Relay reliability remains first: qualify the current hook-definition readiness and exact-recipient diagnostics. Other activation capabilities, traces, work associations, and Claude/Codex validation may proceed independently. Wake-first retains the residual qualification listed at the top of this file; macOS is demand-driven. OpenCode native Windows 2.0.24 wake has a happy-path witness. Its assistant-directory guard merged in PR #297 and capture idempotence merged in PR #306; installed deployment and [remaining reliability gaps](fix-opencode-plugin-reliability.md) remain open before Copilot expansion.

1. **S2 contract gate — complete in PR #98.** Delivery lifecycle
   (`pending`, `claimed`, `delivered`, `expired`; `failed` only on separate
   proven-terminal delivery evidence) remains independent from advisory destination
   health (`active` or `unreachable`). Destination-health transitions never
   change an existing delivery. Missing capability and recoverable or ambiguous
   transport leave it pending and retryable; advisory `unreachable` may reject new
   sends and clears on successful exact-session registration.
2. **S2 wake feedback and destination health — complete in PR #98.** Qualified
   Windows missing-pipe and POSIX missing-socket signals retain the durable
   registration as non-probed `unreachable`; the in-flight delivery remains
   pending. New exact/alias sends fail fast, strict timestamp CAS drops stale
   feedback, and successful exact registration restores both stores. Relay API
   status exposes delivery state and `destination_health` separately.
   Deterministic caller-surface review and installed Claude/Codex automatic-wake
   witnesses passed before merge.
3. **S2 Codex burst coalescing and overtaken-wake suppression complete.**
   PR #95 coalesces scheduling through admission. Because a native prompt already
   accepted by Codex cannot be cancelled, the exact internal trigger emits a native
   structured block decision only when a successful hook-time Relay turn confirms
   the complete canonical no-work state (`deliveries=[]`, `has_more=false`,
   `remaining_count=0`). Caller-surface coverage retains an accepted prompt, lets
   a competing real hook claim and ACK first, then proves the redundant prompt
   stops before memory/model work without losing or duplicating delivery. The
   installed Windows witness queued the exact trigger and recorded hook context then
   `task_complete` with `last_agent_message=null`, no user or assistant transcript
   item, and no requeue.
4. **S2 Codex MCP recovery and integration reload — complete in PR #99.**
   Runtime-owned per-call MCP metadata supplies exact task identity; inherited
   parent IDs and model arguments are ignored. Missing, malformed, or conflicting
   metadata fails closed before Relay HTTP with reload/upgrade guidance. Real
   stdio E2E and an installed fresh-session witness prove exact receive/ACK.
5. **S2 bounded backlog draining — complete in PR #101.** Default-three hook
   turns, continuation, new arrivals, ordering, oversized-first handling,
   duplicate-trigger loop prevention, and installed Codex plus Claude witnesses
   are complete. Keep the current three-message / 2,400-character limits until
   real burst measurement justifies a change.
6. **S3 Codex admission hardening — complete in PR #108; Windows-qualified
   (RW-015).** Exact session+container+actor ownership, launch outcome
   classification, strict-CAS unreachable feedback, deterministic caller-surface
   E2E, and a post-merge no-manual-turn installed witness are complete. Native
   accepted or timed-out queue writes remain coalesced because duplicate
   suppression is false.
7. **RW-017 durable-by-default Relay delivery — complete in PR #113 and
   Windows-qualified.** Omitted/null expiry now stays durable until terminal handling;
   explicit 60-second through 7-day expiry remains opt-in. Fast file-backed restart,
   dormancy, backlog, idempotency, dashboard, MCP, and installed automatic-wake
   evidence pass without wall-clock waits.
8. **RW-016 Windows installed-service metadata — merged and Windows-qualified.**
   Canonical startup carries the exact quoted home in BOM-marked UTF-16 launcher
   metadata; restart PID/log paths follow that home, malformed canonical metadata
   fails before stop, and legacy default-home launchers remain compatible. PR #114,
   deterministic default/custom/space/Unicode/literal-percent coverage, and an
   installed exact-home restart with healthy endpoints are complete.
9. **RW-018 Windows taskkill race recovery — merged in PR #115 and
   Windows-qualified.** A partial child-exit failure no longer skips later exact
   sweeps. The wrapper warns, kills every unique initial listener, verifies
   post-settle port quiescence, blocks a surviving listener before task start, and
   returns explicit success. Deterministic caller-surface coverage, green CI,
   independent review, the installed orphan-respawn replay, and exact-main healthy
   restart are complete.
10. **S3 reply/remediation gate — complete 2026-09-08.** Live request
    `relay-msg-f07d6ebe0c054e4fa38872ef8a3393d7` produced a delivery-derived
    reply that resumed the idle sender solely through Relay. Remediation
    `relay-reply-5b5235201e41cfa596205f632ffbac301d41bae78c5628a9bec52a6e136a7710`
    was admitted without a manual recipient turn, answered `APPROVE`, and again
    resumed the idle sender. No product defect appeared, so no production code or
    speculative correlation telemetry was added.
11. **Codex first-run setup qualification — complete 2026-09-08.** Setup now
    reports configuration installed and requires a Codex restart plus hook review
    if prompted before Relay wake is ready. An isolated Windows Codex 0.149.1 home
    showed all three hooks as new, persisted their trust only through Codex's review
    UI, ran SessionStart, UserPromptSubmit, and Stop, and returned the bounded witness
    response. No trust bypass or Pallium trust write was used; live Pallium hook
    trust entries remained unchanged.
   This setup gate is separate from runtime transport qualification.
12. **S4 additional platforms.** Qualify installed Claude UDS and Codex wake on
   macOS. Windows/Linux Claude and Windows/Linux loaded-task Codex wake remain
   complete and must not be reopened without contrary evidence.
13. **OpenCode V2 active wake — merged; happy-path witnessed, reliability remediation open.**
    PR #292 is merged. The native Windows CLI and desktop witness used official
    unmodified 2.0.24; 2.0.22 is the historical qualification. The configured-model
    live witness verified an unattended exact Unicode response and ACK while
    retaining all 87 sessions and settings. Shipped isolated native lifecycle E2E
    also passed on 2.0.24; earlier isolated Windows validation also
    covers automatic idle/busy delivery, ACK-to-tool continuation across a Pallium
    restart, pre-claim retry, hard restart, and service startup recovery. The V2
    native inbox and one Pallium scheduling fence replace the older proposed
    plugin pending-delivery ledger. PR #297's minimal assistant-directory
    ownership guard is qualified and merged; OC-3 capture idempotence merged in
    PR #306. Installed deployment remains separate.
    [Fix OpenCode plugin reliability](fix-opencode-plugin-reliability.md) tracks
    the remaining wake-anchor, lifecycle and latency gaps.
    Passing existing lifecycle tests or the live happy path does not close them.

### Wake dogfood defect ledger

Every confirmed dogfood failure stays here until a caller-surface regression and,
where the runtime exists locally, an installed witness close it.

| ID | Observed failure | State and owner |
|---|---|---|
| `RW-001` | A busy Codex wake claimed at scheduling time; queued execution after the 60-second lease produced a stale receipt conflict. A related Windows CP1252 write stranded a claimed Unicode delivery. | **Fixed.** Claim now occurs in the admitted UserPromptSubmit hook and subprocess input is UTF-8. Delayed deterministic caller-surface and Unicode regressions cover both paths. |
| `RW-002` | Several close sends queued later generic Codex turns after the first admitted turn had already drained the payload, producing empty conversational acknowledgement turns. Live dogfood later reproduced the remaining race: Codex had already accepted one native queued prompt before a competing admitted turn consumed the delivery. | **Fixed and Windows-qualified; strengthened by RW-019.** PR #95 coalesces Pallium scheduling through admission. The exact internal hook trigger now blocks before memory/model work whenever it cannot render a verified delivery, including canonical empty, failure, timeout, malformed response, or invalid scope; ordinary prompts remain fail-open. Deterministic caller-surface coverage preserves successful delivery and prevents empty conversational turns. |
| `RW-003` | An agent treated one stale/duplicate receipt conflict as a reason to stop the surrounding task, and terminal reports triggered wasteful status-only replies. | **Fixed.** Installed guidance says the stale rule applies only to that delivery, work continues independently, substantive replies wait for completion or blockage, and terminal ACK-only deliveries receive no reply. `test_guidance_budget.py` and hook guidance tests pin the contract. |
| `RW-004` | Pallium restart lost in-memory Claude wake capability, so pending Relay work required a manual Claude turn. | **Fixed and Windows/Linux-qualified.** Durable exact-session capabilities, write-ahead intents, event-driven reconciliation, restart recovery, and installed no-manual-wake evidence are on `main`; macOS UDS remains S4. |
| `RW-005` | Missing Claude endpoints were evicted while deliveries stayed pending; restart feedback was omitted, transient callback failure could diverge the two health stores, and a late-bound recovery callback could update the wrong session. | **Fixed in PR #98.** Retained non-probed `unreachable`, strict stale-feedback CAS, exception-safe retry, bound per-candidate callbacks, self-healing registration, status exposure, deterministic E2E, and installed witnesses are complete. |
| `RW-006` | A Codex MCP child can lack runtime-owned session identity or inherit another Codex task's forwarded identity and claim the wrong inbox. | **Fixed.** Per-request Codex transport metadata is authoritative; inherited `CODEX_*`, configured thread values, and model arguments are ignored. Missing/conflicting/malformed identity fails closed before HTTP. One-child real-stdio E2E covers exact ASCII/Unicode receive+ACK, max-boundary receive validation, and refusal paths; the installed synthetic witness returned the exact new Codex task ID instead of the outer ID. |
| `RW-007` | A bounded turn can report `has_more` and `remaining_count`, but integrations did not prove automatic bounded continuation until the eligible backlog was empty. | **Fixed in PR #101 and Windows-qualified.** Default-three hook turns, fixed character reservation, Codex post-ACK continuation, Claude Stop/recovery continuation, safe candidate selection, caller-surface edge coverage, and installed automatic 3+2 Codex plus Claude wake witnesses are complete. |
| `RW-008` | Crash after claim but before context injection recovers the lease, yet may wait for a natural turn instead of being re-woken automatically. | **Fixed in PR #102 and Windows-qualified.** A read-only exact-session sweep re-wakes eligible expired claims at startup and every 30 seconds through the existing adapters. Deterministic Codex/Claude restart E2E and an installed Codex witness prove automatic reclaim, single ACK, and terminal empty state after the 60-second lease expires. |
| `RW-009` | Wake E2E leaked synthetic memory into the live store; the observed `a043f627-...` object appeared under `other`. | **Fixed; reversible cleanup complete.** The unmocked live request is covered. The exact historical set was tagged `rw009-synthetic-wake-e2e-leak`: 23 source items were forgotten and 89 derived memories soft-deleted. The default dashboard read path now returns zero visible rows for the contaminated container; audit mode retains all 89 memories, including the cited object, for recovery. |
| `RW-010` | The Windows restart wrapper could stop a healthy service while a checkout was mid-edit, reject the canonical task shape, target the wrong configured port, miss a surviving canonical service process, and print success before all required endpoints were ready. | **Fixed and Windows-qualified.** Preflight resolves both observed task shapes, preserves optional/Unicode working directories, validates the installed port before stop, sweeps canonical `service run` while preserving MCP bridges, and gates success on all three endpoints with bounded actionable failure. Fast real-script coverage is in the Windows smoke job. The installed legacy-task witness exited 0 after cold start; `/health` was `ok`, embeddings and ingestion were healthy, and queue health returned HTTP 200. |
| `RW-011` | A delegated agent can end or fail a model turn after hook delivery without the sender knowing whether requested work completed, causing manual polling or a stalled workflow. | **Optional product follow-up.** `idea-agent-relay.md` owns default-off `notify_on_turn_end`; it reports turn end/failure only and never reclassifies context delivery, infers task completion, or supervises work. |
| `RW-012` | A normal hook-injected delivery reached an agent without the trusted container and actor scope needed by `pallium_relay_reply`; reply failed closed and encouraged an out-of-band fallback. | **Fixed in PR #105; Windows-qualified.** Codex and every Claude hook delivery surface now append independently bounded exact scope before ACK; unsafe scope never claims. Real Codex queue and Claude UserPromptSubmit/Stop journeys parse that hook output and complete receiptless atomic replies, with wrong-scope, Unicode, maximum-boundary, backlog, and idempotence coverage. An installed Claude witness auto-woke, parsed the hook scope, and completed the exact receiptless reply without a manual turn or MCP receive. |
| `RW-013` | A Claude session reported its alias handle as `claude-code:claude_arch`, omitting the required `@`; the resulting exact-session selector returned 404 while the UUID worked. | **Fixed in PR #107; Windows-qualified.** Recipient pages now emit canonical `exact_selector` and `alias_selector` values. Existing routing was not rewritten: `codex:@relaydev` dogfood delivered and received `alias-ok`; caller-surface lifecycle coverage pins naming, transfer, close, exact fallback, alias send, filtering, and cross-scope isolation; Codex and Claude configs were reinstalled from clean main. |
| `RW-014` | `pallium_relay_recipients` can exceed the MCP response budget and return only a generic error instead of a usable bounded recipient result. | **Fixed in PR #107; Windows-qualified.** The MCP tool returns stable bounded pages with offset continuation and total count while preserving the HTTP list contract. Deterministic E2E covers all recorded boundaries without wall-clock waits. After reinstall and service restart from exact main, a fresh installed stdio child returned a 1,730-character page with all envelope fields, 5 of 89 recipients, canonical selectors, `has_more=true`, and `next_offset=5`. |
| `RW-015` | Two sends initially appeared stuck behind `destination_health=active`; later durable status and exact-task history proved both hook-delivered, including the vNext target after 57 seconds. The real latent gaps were boolean launch acceptance holding a generation after completed/no-hook exec, session-only admission, and session-only ownership suppressing another scope. | **Fixed in PR #108; Windows-qualified.** Wake ownership is keyed by session+container+actor; blocking exec completion requires the matching hook callback; definite no-hook failure reports strict-CAS `unreachable` without consuming delivery; accepted or timed-out writes stay coalesced. After exact-main reinstall and service restart, `relay-msg-cff1331...` auto-delivered once in 16 seconds and returned `RW015-INSTALLED-PASS` without a manual turn. |
| `RW-016` | Canonical Windows `pallium service install --home <custom>` wrote its task/VBS under the requested home but did not propagate that home to `service run`, so the launched service silently fell back to the default home; the ASCII VBS writer also could not represent non-ASCII interpreter/home paths. | **Fixed in PR #114; Windows-qualified.** Canonical VBS carries the exact quoted home in BOM-marked UTF-16; restart uses that metadata for PID/log paths, missing canonical home fails before stop, and legacy default-home launchers remain compatible. Deterministic CLI plus real-PowerShell coverage passes for default/custom/space/Unicode/literal-percent paths with no Linux code change or wall-clock sleep. The installed task launched the exact-home UTF-16 command and refreshed PID/port with all endpoints healthy. |
| `RW-017` | Relay messages still default to a 24-hour expiry, so unhandled work for a busy or dormant target can become terminal despite durable wake recovery. Dogfood reproduced the default when an omitted MCP expiry returned an `expires_at` exactly one day later. | **Fixed in PR #113; Windows-qualified.** Omitted/null expiry is represented durably without a schema rebuild; explicit 60-second through 7-day expiry remains opt-in. Fast file-backed restart/dormancy/backlog/idempotency/dashboard/MCP regressions pass. Installed dogfood returned `expires_at:null`, auto-delivered once, and produced durable atomic reply `RW017-INSTALLED-PASS` without a manual target turn. |
| `RW-018` | The Windows restart wrapper inherited `$ErrorActionPreference = "Stop"` at native `taskkill /T` calls, so a partial child-exit error aborted before later signature sweeps and task start; an orphan supervisor could then respawn the server while the wrapper failed and PID metadata stayed stale. | **Fixed in PR #115; Windows-qualified.** All tree kills share a best-effort helper with diagnostics, every unique initial listener is handled, later exact sweeps always run, an array-safe post-settle port gate blocks surviving listeners before start, and success exits 0 explicitly. Deterministic thrown/nonzero-kill and initial/persistent multi-listener regressions pass; the original installed orphan-respawn shape restarted cleanly, refreshed PID/port, kept all endpoints healthy, and auto-delivered one Relay wake. |
| `RW-019` | Under concurrent work, sync-route worker starvation made the DB-free health endpoint time out; hook cancellation could leave a late server-side claim; startup recovery ignored never-claimed pending work; pooled SQLite connections repeated lock-taking persistent PRAGMAs; valid raw Relay text could exceed the rendered budget after redaction expansion. | **Fixed in PR #123; Windows-qualified.** Relay has independent capacity and shutdown drain, health stays async, startup recovery covers pending plus expired claims, Codex admission fails closed without a verified delivery, persistent PRAGMAs initialize once, and redaction overflow is bounded safely. Deterministic caller-surface/contention coverage, the opt-in mixed-load witness, full CI, exact-main restart, and installed Relay dogfood passed. Durable cross-process wake reservation remains future scale work. |
| `RW-020` | During an active vector rebuild, the installed restart wrapper exhausted readiness even though the service later became healthy; /status and queue diagnostics previously amplified the delay. | **Fixed in this slice; Windows-qualified.** The wrapper keeps one monotonic deadline and increases only the default from 120 to 180 seconds, placing the documented moments-later recovery class inside one additional bounded minute while explicit budgets remain exact. Existing real-PowerShell lifecycle coverage passes without production-length sleeps. A no-argument installed restart completed in about 68 seconds against the current 11,093-source, 385.62 MB store; `/health` was ok with vectors and embeddings ready, `/status` reported healthy ingestion, and queue health returned HTTP 200. The witness did not naturally trigger a rebuild, so it does not claim a new rebuild-duration measurement. A 2026-09-14 follow-up found queue health taking 2.3–2.9 seconds on the larger live store while each probe was capped at two seconds; queue health now receives up to ten seconds within the same overall deadline. |
| `RW-021` | The filesystem-backed Claude wake reconciler durability test required four retry cycles within one second and flaked under loaded Linux 3.13 xdist even though the Relay delivery remained pending and retryable. | **Fixed in this slice.** The event wait keeps the same four-attempt state contract but uses a five-second failure ceiling and reports observed attempts on failure. It returns immediately on success, adds no sleep, and changes no production wake timing or retry behavior. |
| `RW-022` | A busy Codex target kept one Relay batch pending while periodic recovery blindly resubmitted already accepted native queue prompts. Dogfood recorded at least fourteen successful submissions, followed by thirty empty task starts after the first hook turn delivered the batch. | **Fixed in this slice.** Confirmed and ambiguous non-idempotent native writes now retain one live scheduler generation without blind retry; hook admission still clears ownership and startup still reconstructs pending work. A deterministic HTTP send → real scheduler → six recovery windows → actual UserPromptSubmit hook regression failed 6-to-1 before the fix and now proves one native queue submission, one delivery, empty-wake suppression, and rearm. Exact cross-service-restart deduplication remains part of durable wake reservation. |
| `RW-023` | Claude could discard Pallium UserPromptSubmit output at its eight-second host timeout because the hook's seven-second active-work budget began only after Python startup/imports, leaving just one second for all outer-process overhead. Setup also did not reconcile timeout changes into an existing managed hook entry. | **Fixed in this slice.** UserPromptSubmit now has a 12-second outer host window while active work remains capped at seven seconds. Setup updates only separator-normalized exact managed commands in place, preserves unrelated/malformed fields and existing duplicates, and remains idempotent. Fast deterministic regressions failed on the prior one-second slack and stale installed values, then pass with five seconds of total outer slack and migrated settings. |
| `RW-024` | Codex wake launched `codex exec resume` without an explicit cwd, so the child inherited the Pallium service checkout. A resumed task then adopted that workspace, derived the wrong Relay container scope, and sender lookup correctly failed closed with 404. | **Fixed in this slice.** The adapter no longer cold-resumes or reads private Codex workspace state. It writes one exact-thread native queue item from a validated neutral Codex home; loaded tasks wake through their owner, while unloaded-task correctness relies only on Pallium's pending delivery and a later hook turn. Caller-surface regressions pin explicit cwd, fail-closed unsafe paths, pending-before-hook, exact delivery, and single-flight behavior. |
| `RW-025` | A substantive hook-delivered assignment outlived its claim lease during investigation, so receiptless atomic reply returned the expected 409 even though the work completed. | **Tracked operational fallback.** The Relay error was surfaced and completion was sent as a new direct Relay message. Existing expired-claim recovery protects the original delivery; no automatic completion-message fallback is added unless this recurs as a product failure. |
| `RW-026` | Near-simultaneous Codex sends produced anonymous `failed` and `queued` wake logs. Durable state and task JSONL proved one hook delivery and one pending delivery followed by a direct app-message fallback, but the wake outcomes could not be assigned to a delivery or safely explained. | **Fixed as a diagnosis gap only.** Every attempted Codex wake now logs the canonical delivery ID, bounded SHA-256 fingerprints for session and container scope, a fixed safe reason category, and an optional numeric exit code; recovery candidates use the same correlation values. Hostile-reference and full launch-outcome regressions prove prompts, stderr, exception text, environment values, secrets, and local paths are not logged. Delivery routing, queueing, retry, claim, ACK, and app-message hook behavior are unchanged; this does not claim the observed failed wake was repaired. |
| `RW-031` | A Codex native queue call can persist a fresh queue row before its response is lost, while the public CLI returns nonzero and creates a new client message ID on every retry. Retaining an uncertain reservation prevents duplicate native turns but can leave a pending delivery without actionable recovery guidance. | **Pallium work closed; the remaining automatic-recovery gap is upstream.** PR #209 records exact-delivery hook start, payload emission, ACK, and bounded failure evidence. An installed busy-to-idle witness proved one accepted submission, one later safe turn, one injection, and one ACK; it did not exercise uncertain failure. Trace explanations distinguish queued, delivered, expired-before-claim, needs-intervention, mixed, and incomplete evidence. A later delivery in the same never-moved exact scope (generation 0) blocked by a retained uncertain fence after service restart now reuses only complete durable prepared/completed evidence to expose the same needs-intervention guidance; it never releases the fence or submits another native turn, and moved or ambiguous scope evidence fails closed. Startup and periodic recovery enumerate already-pending coalesced deliveries oldest-first so later items receive that association without weakening the single native-submission fence; default candidate reads and exact-ID rechecks remain unchanged. Review of the public CLI and app-server sources for Codex `0.155.0-alpha.9.2`, `0.156.1`, and `0.157.0-alpha.11` found no composition on those surfaces that wakes an unloaded task in its Desktop-owned app-server and atomically admits one exact queued submission. `codex exec resume` starts a second runtime, `thread/queue/start` is loaded-only, and the public queue path has no caller idempotency key. Therefore Pallium deliberately keeps the delivery pending for an ordinary supported recipient turn. This is not a Pallium release gate; revisit only when Codex provides owner-routed cold activation with server-side idempotency and authoritative admission results. |

| `RW-033` | A temporary service with an isolated Relay database but no Codex wake-dir override opened the installed shared wake registry; startup reconciliation logged seven missing reservations as stale and released their fences. The precise delivery impact was not established. | **Codex fix in this slice.** Registry selection follows the actual Relay database, startup recovery receives the app-owned registry, and process-global schedule keys include registry identity; deterministic two-instance coverage checks the foreign reservation file is unchanged. The distinct Claude hook-intent cross-instance risk from [issue #234](https://github.com/rore/Pallium/issues/234) is addressed by Relay-database-scoped Claude state, setup-pinned hook binding, pre-write marker checks, and two-instance hook/HTTP/outage tests. |

| `RW-034` | An exact Codex wake can commit its `/relay/turn` claim but lose the response at the hook's 0.75-second HTTP limit. The existing correlated lease-expiry recovery then waits at least 60 seconds plus a recovery sweep before another safe wake. | **Bounded prevention in this slice; native uncertainty remains separate.** Only the final HTTP request carrying the validated exact wake delivery ID may wait up to two seconds, with one second of the hook safe-work budget reserved for emission and ACK. Bootstrap, scope replay, ordinary prompts, and malformed wake text retain the 0.75-second cap; responses beyond two seconds still fail closed into existing exact-correlated recovery. Synthetic loopback HTTP plus actual-hook coverage verifies claim, emission, ACK, and the delayed-response boundary. This establishes a general failure class, not the uncorrelated historical incident's precise cause or universal latency immunity. |
| `RW-035` | One accepted loaded Codex wake started its recipient turn, but the hook reported Relay unavailable; a later exact-delivery claim committed with attempts 1 and no correlation in the retained wake reservation. The old server did not retain the request body or callback result. | **Forward fix in this slice; historical fence remains conservative.** An exact /relay/turn request captures the current reservation before claim. The claim transaction stores its generation only when the selected delivery and endpoint match; a post-claim callback also checks that same generation. If the callback is lost, an expired lease can rearm from the durable same-generation claim, while a live lease, ordinary or mismatched claim, legacy NULL, and uncertain native outcome without an exact claim remain fenced. Caller-surface callback-loss through recovered HTTP payload and ACK, generation-race, migration/restart, and ACK regressions pass. This does not establish the historical failure cause, clear its fence, or prove installed recovery from a live uncertain native submission. |

The Windows Claude regression floor remains: idle text and zero-tool turns, empty
Stop rearm, busy delivery, ordered bursts, Unicode, recursive-Stop loop prevention,
duplicate send/trigger, arrivals during continuation, preservation of the original
human-owned turn, exact scope, and no manual prompt after a case begins. Deterministic
tests cover the contract; installed runtime witnesses stay opt-in to protect budget.

The following related work stays separate to keep ownership clear:

- `add-relay-retention-and-lifecycle-hardening` owns bounded cleanup of the final
  session/destination/delivery states defined here; it must not invent liveness or
  terminal-failure semantics independently.
- `idea-agent-relay.md` retains the optional default-off `notify_on_turn_end`
  proposal. Turn end is not task completion and is not a prerequisite for delivery
  correctness.
- `validate-relay-dependency-workflows` is a paused documentation/examples follow-up;
  it does not gate reliability work or runtime expansion.
- `feat/clarify-relay-activation-snapshot` remains separate unmerged API-contract work: its evidence-scope and exact-trace-source fields complement this explanation slice but are not required for actionable failure guidance.
- The local wake-test pollution repair is complete and reversible: the exact 23
  synthetic source items are forgotten and 89 derived memories are soft-deleted
  under one audit reason; the default dashboard read path exposes none of them.
  This was operational data repair, not Relay routing behavior.
- **Next correctness and operations follow-ups (separate from S2):** RW-017 makes
  ordinary Relay work durable by default while preserving explicit expiry. RW-016's
  canonical Windows custom-home/Unicode launcher repair is merged and qualified.
  RW-018's taskkill-race recovery is merged and Windows-qualified; retain RW-010's
  regressions and installed witness as the operations floor. S3 Codex lifecycle gates
  are next.

The remaining S2 qualification is done only with caller-surface E2E for fresh
versus stale MCP hosts, bounded backlog, memory routing, Unicode, scope isolation,
restart, and idempotence. Existing unknown, passive, unreachable, self-healing
registration, retryable/qualified missing-endpoint transport, async status, burst
coalescing, and delivery-before-queued-execution regressions remain mandatory.
Tests must be fast and deterministic; installed-runtime witnesses remain opt-in
release gates.

**Core scope:** Derive the smallest coordinator from the Codex delivery trace.
Do not wait for a second adapter or build speculative multi-runtime machinery.
Choose bounded limits from Codex evidence; revisit only when adding another adapter.

### Historical implementation sequence — Codex first

**Codex (Windows/Linux loaded-task):** `codex queue --thread T` writes one generic trigger from a validated neutral Codex home. The owning Desktop watcher starts the loaded task; for an unloaded task, Pallium keeps the Relay delivery pending until an ordinary supported hook turn and does not rely on native queue persistence. The admitted UserPromptSubmit hook claims and injects the attributed batch under the target scope. Any exact internal trigger that cannot render a verified delivery is blocked before memory/model work, whether the Relay result is empty, unavailable, timed out, malformed, or invalidly scoped. MCP receive remains a separate fail-closed recovery path. Keep the adapter runtime/version-qualified until the remaining OS and lifecycle gates pass.

**Claude Code:** S0/S0.5 are misqualified because Claude 2.1.250 peer frames bypass `UserPromptSubmit` as internal `isMeta` events. Claude reproduced S1A Stop continuation; Codex architect review is clean, exact-scope bounded Stop `/relay/turn`, one emit of the successfully rendered claim set followed by individual ACKs, and one exit-2 continuation—not MCP—provide peer-wake admission. Do not treat generic native notice as delivery.
Keep Channels deferred and macOS passive until installed UDS E2E passes.

**OpenCode:** This was the original deferral. PR #292 superseded it; Windows V2
automatic wake had an installed happy-path witness on native 2.0.24; 2.0.22 was
the historical qualification. PR #297's assistant-directory guard and PR #306's
capture-idempotence correction are qualified and merged; installed deployment and
the [remaining reliability gaps](fix-opencode-plugin-reliability.md) remain open.

## In Scope

- wake every eligible resolved recipient by default, including runtime fan-out
- allow a recipient integration to explicitly disable wake and remain passive
- persist before attempting wake; retain next-natural-turn delivery as fallback
- queue busy recipients for a separate safe turn rather than steering an active
  human-owned turn
- confirm runtime admission before marking delivery complete
- make trigger attempts idempotent so wake and fallback cannot double-deliver
- expose wake attempts, admission, fallback reasons, failures, latency, and fan-out
  in Relay operational telemetry
- implement and validate the smallest supported native adapter for Claude Code,
  Codex, and OpenCode
- cover idle, busy, concurrent user input, unsupported capability, stale or closed
  sessions, runtime and Pallium restarts, duplicate triggers, permissions, fan-out,
  expiry, and reply-loop protection through public-surface E2E tests

## Safety and Cost Boundary

Wake changes Relay from passive information transport into an execution trigger:
the receiving model can consume tokens, invoke tools, and modify files. Therefore:

- Relay input is attributed peer input with lower authority than user instructions;
  it cannot grant consent, approve permissions, change runtime configuration, or
  bypass the recipient's sandbox and approval policy
- runtime-wide fan-out still wakes every resolved recipient by default, but the
  resulting turn count, failures, and observable usage must be visible
- bounded queues, duplicate/rate limits, and a finite reply-hop policy must prevent
  accidental wake storms and autonomous reply loops
- automatic replies are not implied by delivery; a reply remains an explicit Relay
  action derived from a received delivery ID
- an integration can explicitly disable wake, but passive delivery remains enabled
  unless Relay itself is disabled

## Out of Scope

- restarting an exited agent process or resuming a dormant harness automatically
- launching or managing a parallel runtime/session as a substitute for the
  existing session addressed by the sender
- spawning agents, assigning work, or supervising completion
- sender-selected wake syntax or semantic wake decisions
- treating runtime admission as proof that the agent understood or used a message
- automatic agent conversations or unbounded reply chains
- Pallium deciding that another review or implementation pass should happen; the
  participating agent must explicitly send each handoff or reply

## Done When

1. A Relay send is persisted and wakes every eligible resolved recipient without a
   user turn or sender delivery flag.
2. Busy recipients process the message in a separate safe turn, never by accidental
   steering of an active human-owned turn.
3. Unsupported, unavailable, stale, or passive recipients receive the same durable
   message exactly once on their next natural turn.
4. Delivery state and dashboard telemetry distinguish wake attempt, runtime
   admission, fallback, and terminal expiry without claiming downstream use.
5. Full-lifecycle E2E coverage verifies the observable contract through each
   supported runtime's real integration surface.
6. Relay-triggered turns preserve attribution, lower-authority treatment, sandbox
   policy, and ordinary permission prompts.
7. Queue, duplicate, rate, and reply-hop bounds terminate replay or reply storms
   while leaving the original durable delivery diagnosable.

8. A live Claude Code developer → Codex architect → Claude Code remediation →
   Codex verdict journey completes after one initial user instruction and no
   intermediate user prompts. Repeat with the runtime roles reversed where the
   installed integrations support it.
9. That journey remains exact-once and model-visible when either recipient is
   idle or busy, and across a Pallium or recipient-integration restart. If wake
   cannot be admitted, the delivery remains durable and the dashboard/status
   exposes the fallback or actionable failure rather than silently stalling.

## Notes

Implementation plan: [wake-first Relay delivery](../../docs/plans/2026-08-26-wake-first-relay-delivery.md).

Phase 0 decision and installed-runtime evidence:
[Relay wake Phase 0 decision record](../../docs/designs/017-relay-wake-phase0.md).

Historical Codex/Claude implementation result record (OpenCode deferral later superseded by PR #292): Codex exact-session wake writes one hidden `codex queue --thread` trigger from a validated neutral Codex home. A runtime that already loaded the target starts a real turn; for an unloaded target, Pallium retains the pending Relay delivery until its next supported hook turn and claims no native queue persistence. RW-024 removed hidden `codex exec resume` because inheriting the service cwd could mutate task workspace and Relay scope. Queue launch remains best-effort with durable natural-turn fallback on failure. The adapter encodes Relay prompts as UTF-8, and the pre-fix claim-before-queue behavior reproduced a 409 `claim lease has expired` when a delivery was claimed before queueing and the queued turn executed after the lease. The installed UserPromptSubmit hook claims only at admitted-turn execution; delayed busy-target caller-surface E2E proves no stale receipt, loss, or duplicate action. A later live empty turn exposed the native accepted-prompt race: another admitted turn can consume the delivery after Codex accepts the queued trigger. The original guard blocked only the complete canonical no-work response; RW-019 strengthens it so any exact internal trigger without a verified rendered delivery stops before memory/model work. Deterministic caller-surface coverage preserves successful delivery, proves a competing real hook consumes and ACKs exactly once, and stores a safe marker when redaction expansion would otherwise exceed the render budget. An installed exact-session witness queued the trigger and recorded hook context followed by `task_complete` with `last_agent_message=null` and no user or assistant transcript item. Later sustained busy-target dogfood exposed RW-022: periodic recovery resubmitted the accepted non-idempotent prompt until admission. The scheduler now retains one confirmed or ambiguous native write per live generation without blind retry; deterministic caller-surface coverage proves recovery sweeps do not add queued turns. Hook-delivery wake and per-session burst coalescing are proven for the tested Windows paths. A Relay-wide read-only sweep now re-wakes eligible expired claims for active exact Codex and Claude sessions immediately at service startup and every 30 seconds, then the admitted hook reclaims and ACKs normally; controlled-clock real-hook E2E covers both runtimes and both full-app restarts. An installed Windows Codex witness deliberately abandoned a claimed delivery, then observed automatic hook delivery on attempt two after the 60-second lease expired, without a manual wake. Codex MCP receive and bounded automatic backlog drain are Windows-qualified. An installed Ubuntu 24.04 / WSL2 witness with Codex 0.153.4 targeted session `01a0776f-337d-7013-8170-f55b37a32f30`; parent `relay-msg-c55a51edc4a9469e81068a4f5adc4763` / delivery `relay-delivery-0dcd69097ce040d5858a6103956773d7` moved from pending attempts=0 to delivered attempts=1, produced `CODEX_LINUX_WAKE_DELIVERED_TRUSTED_20260906`, and returned idle. Explicit repository and exact-hook hash trust were used, never the trust-bypass flag. Sender-side reply admission and the bounded no-ping remediation journey were re-proven on 2026-09-08 with both original sender resumes caused solely by Relay and no manual recipient turn. Remaining interrupted/restart reliability and macOS qualification remain. Startup recovery now enumerates all eligible coalesced pending/expired candidates in oldest-first order, while default reads remain one-per-endpoint and exact rechecks remain unchanged. RW-026 now correlates each attempted Codex wake and recovery candidate with bounded identifiers and safe launch categories; it improves diagnosis only and does not claim the observed failed wake was repaired. Claude Windows and installed Linux UDS wake are complete; macOS remains S4, OpenCode's native Windows 2.0.24 wake has a happy-path witness; reliability remediation remains open in [Fix OpenCode plugin reliability](fix-opencode-plugin-reliability.md).

## Research References

Primary runtime sources:

- [Claude Code cross-session messaging](https://code.claude.com/docs/en/cross-session-messaging)
- [Claude Code Channels](https://code.claude.com/docs/en/channels)
- [Claude Code v2.1.224 release](https://github.com/anthropics/claude-code/releases/tag/v2.1.224)
- [Claude Code native-Windows delivery issue history](https://github.com/anthropics/claude-code/issues/86603)
- [Codex App Server protocol](https://github.com/openai/codex/blob/main/codex-rs/app-server/README.md)
- [Codex queue integration tests](https://github.com/openai/codex/blob/main/codex-rs/app-server/tests/suite/v2/thread_queue.rs)
- [Codex Windows active-writer/no-attach limitation](https://github.com/openai/codex/issues/37450)
- [Codex atomic idle-only admission request](https://github.com/openai/codex/issues/38289)
- [Codex unloaded queue activation limitation](https://github.com/openai/codex/issues/44491)
- [Codex 0.155 exact-version exec resume implementation](https://github.com/openai/codex/blob/4607249e430dac1c961df4dc615beae88e33cec8/codex-rs/exec/src/lib.rs)
- [Codex 0.155 exact-version queue service](https://github.com/openai/codex/blob/4607249e430dac1c961df4dc615beae88e33cec8/codex-rs/ext/queue/src/service.rs)
- [Codex 0.155 exact-version queued-turn start](https://github.com/openai/codex/blob/4607249e430dac1c961df4dc615beae88e33cec8/codex-rs/app-server/src/request_processors/thread_queue_processor.rs)
- [Codex 0.156.1 exact-version queued-turn start](https://github.com/openai/codex/blob/rust-v0.156.1/codex-rs/app-server/src/request_processors/thread_queue_processor.rs)
- [Codex 0.157.0-alpha.11 exact-version queued-turn start](https://github.com/openai/codex/blob/rust-v0.157.0-alpha.11/codex-rs/app-server/src/request_processors/thread_queue_processor.rs)
- [Codex background app-server daemon](https://github.com/openai/codex/blob/main/codex-rs/app-server-daemon/README.md)
- [OpenCode server API](https://opencode.ai/docs/server/)
- [OpenCode plugin API](https://opencode.ai/docs/plugins/)
- [OpenCode prompt acceptance without wake issue](https://github.com/anomalyco/opencode/issues/21524)
- [Claude Agent SDK session resume](https://code.claude.com/docs/en/agent-sdk/sessions)

Feasibility evidence, not dependencies or adoption evidence:

- [Agent Intercom Claude adapter](https://github.com/dataforxyz/agent-intercom-claude)
- [Agent Intercom Codex adapter](https://github.com/dataforxyz/agent-intercom-codex)
- [Agent Intercom OpenCode adapter](https://github.com/dataforxyz/agent-intercom-opencode)
- [Agent Mail](https://github.com/osteele/agent-mail)

The runtime APIs are evolving. Recheck the primary documentation, installed
versions, preview flags, and open-issue status rather than copying version-specific
adapter behavior from this roadmap item.

### Historical accepted Claude S1B restart-durability plan (Windows-qualified)

The critical outage window is Claude reaching Stop while Pallium is down: loopback registration fails and a restart would otherwise preserve stale busy. Canonical capability remains `~/.pallium/claude-wake/capabilities.json` (Windows `%USERPROFILE%\.pallium\claude-wake\capabilities.json`) with exact scope/socket/token/generation plus `busy`, `idle`, or `wake_inflight(delivery_id, utc_attempt_time)`. The existing registry lock serializes normal register, state changes, and same-session intent take/apply/removal. Add only `~/.pallium/claude-wake/intents/<sha256(session_ref)>.json`: before HTTP registration, the hook atomically writes the exact state with a random `intent_id` and sends that id in the request. Under lock, the request id must equal the currently stored intent before any canonical mutation; mismatch rejects/no-ops. Success writes canonical then consumes only that exact intent. Ambiguous responses retain/retry the same intent, never create/rewrite a later one; crashes and delayed old requests are deterministically idempotent.

Persistence is state-specific: failed idle registration does not publish idle and failed idle→inflight does not transport; ordinary idle/inflight writes precede publication/effect. Failed busy persistence immediately marks memory busy and must make stale durable idle unloadable before continuing. If that cannot be quarantined/deleted, persist one `store-unusable` marker checked before startup loads capabilities; no rehydration occurs until trusted registration/intent repair. If neither quarantine nor marker persists, startup refuses rehydration while stale file exists. POSIX directory/file `0700`/`0600`; Windows inherits user-profile ACL; no DPAPI/custom DACL. Bad data is ignored, but a valid capability is not discarded solely for permission-setting failure. No TTL/age cleanup: online SessionEnd removes its record; offline SessionEnd writes a closed/removal intent. At the 256 cap only, non-admitting endpoint-absence checks may reclaim provably missing endpoints. Never `registry.probe`, auth, write, or open; POSIX socket nodes and busy/timeout Windows pipes are uncertainty, retained, and new registration rejects. Only SessionEnd or a truly missing endpoint is terminal; all uncertain transport is retryable.

Use a minimum read-only exact-scope storage/service pending-candidate query before recovery dispatch; it never claims/ACKs. Claimed/delivered/expired clears inflight retry; pending waits bounded grace then can retry. One event-driven reconciler is signaled by readiness/new-send/registration/intent consumption; its capped Condition/Event wait periodically scans write-ahead intents. Signals coalesce and retries continue indefinitely while exact pending+eligible work remains, with capped backoff and no busy loop or finite retry count. Crash windows prefer an extra empty admission, never lost Relay work.

Required fast E2E includes delayed old intent mismatch, every write-ahead intent crash/response-loss boundary, busy failure→restart with stale file, offline SessionEnd, crash-without-SessionEnd capacity pressure, live endpoint at cap with zero native writes/admissions, post-start intent discovery, corrupt intent/capability, Unicode path, duplicate/concurrency, typed transport, indefinite capped retry, and non-claiming query. Windows no-manual-re-registration restart wake/Stop claim/inject/reply is qualified.
**Review status:** Windows S1B and installed Linux UDS witnesses are accepted. macOS installed UDS qualification remains S4.
