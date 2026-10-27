<!-- agent-workflow:start -->
**Outcome:** Expiry-recovery E2E verifies durable single delivery and truthful ACK confirmation for confirmed and lost responses.

**Target:** Codex exact-wake expiry/fresh-hook ACK test contract.

**Scope:** tests/test_agent_relay_hooks.py and .agent-workflow/tasks/relay-ack-contract.md.

**Constraints:** Keep expired requests from claiming, emit the exact Unicode payload once, require server ACK 200 and public delivered/attempts=1, and never infer client confirmation from server success. Preserve strict confirmed-response controls, native deadlines, refusal coverage and cleanup joins. No product, timeout, retry, preparation-clock, installed-environment or new diagnostic-program changes. No new PR before Relaydev composition is agreed.

**Completion criteria:** A real ACK response produces delivery_acked. A response deliberately dropped after real HTTP ACK commit produces ack_failed without delivery_acked while public state is delivered/attempts=1. The original expiry/fresh case accepts an unconfirmed result only with independent ACK transport-failure evidence and those same durable-state gates. The original native test identity and strict positive/late-response controls remain. Exact reviewed source and evidence are handed to Relaydev for qualified composition.

**Requirement baseline:**
{"source":"manager-native-ack-observable-resolved-20261027","outcome":"Expiry-recovery E2E verifies durable single delivery and truthful ACK confirmation for confirmed and lost responses.","scope":"tests/test_agent_relay_hooks.py and .agent-workflow/tasks/relay-ack-contract.md.","constraints":"Keep expired requests from claiming, emit the exact Unicode payload once, require server ACK 200 and public delivered/attempts=1, and never infer client confirmation from server success. Preserve strict confirmed-response controls, native deadlines, refusal coverage and cleanup joins. No product, timeout, retry, preparation-clock, installed-environment or new diagnostic-program changes. No new PR before Relaydev composition is agreed.","completion_criteria":"A real ACK response produces delivery_acked. A response deliberately dropped after real HTTP ACK commit produces ack_failed without delivery_acked while public state is delivered/attempts=1. The original expiry/fresh case accepts an unconfirmed result only with independent ACK transport-failure evidence and those same durable-state gates. The original native test identity and strict positive/late-response controls remain. Exact reviewed source and evidence are handed to Relaydev for qualified composition."}

**Relationships:**
{"schema_version":1,"sources":null,"pull_requests":[]}

**Risk:** Elevated

**Complexity:** Moderate

**Reason:** Test-only correction at a durable-custody/confirmation boundary could falsely qualify unsafe behavior if the oracle is loosened. Existing accepted ambiguity behavior must remain distinct from confirmation; no runtime code changes.

**Discovery:** Merged #359 added decisive outcome evidence. #325 head7038eff30fb40716f90b3f0c312e758bbd42af5c CI40426431412/job121933295626 records ACK server200, response BrokenPipeError, public delivered/attempts1 and no hook ACK event, with1967ms operation. The strict unconditional confirmation assertion conflicts with existing late-ACK E2E and acknowledge_relay's confirmed-response-only return contract. Physical latency remains unknown; previous runs stay failed.

**Material assumptions:** The accepted product contract permits committed-but-unconfirmed ACK and requires truthful hook events. Confirm against existing real-HTTP late-response test and helper source; if this instead changes a written product requirement, stop with exact before/after for authority rather than silently weaken it. Public delivered/attempts1 and server200 remain mandatory; a retained claimed/pending state cannot pass.

**Plan:** Record this baseline and classify risk before test edits. Obtain existing reviewer contract/plan decision. Add an opt-in ACK-response-drop fault to the existing expiry/fresh native case and one explicitly named E2E wrapper, keeping the original test identity and native path intact. The existing Handler commits through actual API before closing the client connection without a response; no delay or timeout is added. Prove controlled RED at the original unconditional ACK-event assertion. Then distinguish exactly one truthful ACK terminal event: normal confirmed response requires delivery_acked; unconfirmed outcome requires ack_failed, no delivery_acked, and independent transport-loss evidence (controlled drop, real response write error, or exact ACK request failure diagnostic). Require ACK server200 and delivered/attempts1 in both paths. Preserve exact payload, expired no-claim, joins, budgets and existing strict positive/late-ACK controls. Run focused controls then affected module, selector/governance, and independent actual diff/result review. Hand an exact reviewed commit to Relaydev for agreed composition; required full qualification belongs to composed source before release, never replace it with focused passes.

**Verification plan:** Original false oracle -> controlled lost-response E2E RED with real ACK commit and public state. Corrected caller contract -> original native case plus controlled response-loss case and existing strict positive/late-response controls, all with exact state and event assertions. No safety regression -> full affected hook module and source diff proving product/deadline/cleanup/protected paths untouched. Whole change -> selector and workflow/risk checks; Relaydev's current-head composed full lane required before release. No blind failed-run retry, new latency capture or live acceptance.

**Plan review:** Agent technical review: @astra-reviewer turn01a17ad2-11e7-7c40-83b5-98929398aeef, exact recorded-plan conditional GO; required transport-evidence clarification is adopted below.

**Approvals:** Not required at this risk level; existing user-authorized implementation/review coordination applies. No authority to weaken product requirements is inferred.

**Exceptions:** —

**State:** Ready for review
<!-- agent-workflow:end -->

## Source and coordination

Assignment: manager-native-ack-observable-resolved-20261027, delivery relay-delivery-c33b562102bd4d99ab955c4d91ff3add. Single ACK owner @pal-dev1; Relaydev owns #325/#353 composition. #359 stays merged, unchanged. Exact base4b5e5d068ff6d77a66f8f9f5bf4cd57422959204; branch feat/relay-ack-contract in a new managed isolated follow-up checkout. Existing task checkouts/evidence remain retained; no ordinary installation or primary dirty checkout files changed.

Current role freshly confirmed @pal-dev1; mapping has no entry, ordinary opt-out. Existing explicit wake/OpenCode references remain for ongoing broader assignments; no new exact item reference was supplied or invented. Manager owns canonical queue updates. Read Minimap skill for existing roadmap context; no shared server or roadmap mutation needed for this bounded contribution.

Evidence source: Relaydev's retained relay-pool-current checkout, build/pr325-pin-preparation/automatic-linux313-failed.log, read-only. Existing late-response control in tests/test_agent_relay_hooks.py asserts durable delivered state and ack_failed/no confirmation after a deliberately delayed ACK response. Production acknowledge_relay caps its request0.5s and confirms only exact returned delivered state; hook emits before ACK and reports failure truthfully. No source evidence of lost custody or a product fix is inferred.

This corrects the expiry test's assumption that a committed ACK response always arrives; it does not rewrite the accepted product contract. Existing confirmed-response control stays strict. Independent reviewer must assess this classification explicitly before implementation.


## Plan review and clarification

Astra reviewed exact WR99aa3ec0 on merged4b5e5d0. Conditional PLAN GO requires naturally unconfirmed ACK to pair the correct committed ACK response/public delivered-attempts1 with the exact hook ACK transport exception or equivalent captured transport boundary. Server response-write error, generic ack_failed or missing event alone cannot select success. Adopted implementation: capture the actual ACK response identity/state/flag; derive the unconfirmed branch only from the helper's exact ACK-path diagnostic with a known transport exception class, excluding malformed JSON/wrong-ID/no-error outcomes. The controlled real-HTTP drop also must produce that actual transport exception, after commit and before response transmission. Server200/publicdelivered1 stay strict in both paths; terminal event must be exactly truthful. Keep normal-response confirmation strict, original node identity, native deadlines, late-ACK controls and joins. No duplicate full suite requested; return immutable patch/focused evidence to reviewer, then Relaydev composition.

This is conformance to the already accepted late-response contract; it does not remove durable delivery, single claim, truthful confirmation or positive-response coverage. Controlled RED/GREEN is required before accepting this interpretation. Named deterministic UTF8 write fallback is used because the earlier machine-local apply_patch1385 failure must not be retried; no repository policy or live installation changes.


## Implementation and verification

One existing test/helper gains an opt-in response-drop control after actual HTTP ACK commit, before any response transmission. One new explicit native E2E invokes it; the original required identity remains unchanged. The durable public delivered/attempts1 check remains strict and now precedes terminal-event classification. The actual server ACK response must be200, match exact delivery/state and have a boolean already_delivered. Only an exact hook ACK-path failure diagnostic with a known transport exception can select unconfirmed ack_failed; malformed JSON, wrong-ID or missing-event alone cannot. Exactly one correct terminal event is required; no server success synthesizes confirmation. Existing separate positive/late-ACK controls remain unchanged. No product/deadline/preparation-clock change.

Controlled response-loss RED on original unconditional assertion:1failed5.39s, red.xml/log. Corrected focused native/controlled-loss/strict-positive/late-ACK group:7passed19.76s, focused.xml/log. Complete affected module:161passed64.18s. Readiness observation uses the process profile, so final qualification reran unchanged source once with a fresh child HOME/USERPROFILE/AppData/temp and runtime credentials removed:161passed71.90s, neutral-affected.xml/log and neutral-environment.json. These cohorts overlap and are not summed; the neutral run is the final affected receipt. No package installation or persistent environment change.

Scope proof confirms65 unchanged existing functions, exactly one new controlled-loss test, original native identity retained, unchanged wait/join/sleep calls and unchanged production/shared fixture/protected paths. Only the contradicted unconditional ACK-event assertion is replaced; independent wire-failure evidence, strict server response/durable state and truthful exclusive outcome assertions are added. Evidence in build/relay-ack-contract. Isolated runtime/current-cwd imports and dependency bounds verified; supplied original CI log copied read-only with SHA256802cc6b23fed1b1dea24be2d74f1006b1ccac266f56d2e8cf4000bebc9cfac74. Physical1967ms delay remains unknown, oldCI stays failed; this is no latency cure. Actual reviewer result and source-compatible Relaydev composition/full qualification remain pending.
