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

**Plan review:** Pending existing non-implementer contract/plan review; no test edits.

**Approvals:** Not required at this risk level; existing user-authorized implementation/review coordination applies. No authority to weaken product requirements is inferred.

**Exceptions:** —

**State:** Blocked or returned to planning
<!-- agent-workflow:end -->

## Source and coordination

Assignment: manager-native-ack-observable-resolved-20261027, delivery relay-delivery-c33b562102bd4d99ab955c4d91ff3add. Single ACK owner @pal-dev1; Relaydev owns #325/#353 composition. #359 stays merged, unchanged. Exact base4b5e5d068ff6d77a66f8f9f5bf4cd57422959204; branch feat/relay-ack-contract in a new managed isolated follow-up checkout. Existing task checkouts/evidence remain retained; no ordinary installation or primary dirty checkout files changed.

Current role freshly confirmed @pal-dev1; mapping has no entry, ordinary opt-out. Existing explicit wake/OpenCode references remain for ongoing broader assignments; no new exact item reference was supplied or invented. Manager owns canonical queue updates. Read Minimap skill for existing roadmap context; no shared server or roadmap mutation needed for this bounded contribution.

Evidence source: Relaydev's retained relay-pool-current checkout, build/pr325-pin-preparation/automatic-linux313-failed.log, read-only. Existing late-response control in tests/test_agent_relay_hooks.py asserts durable delivered state and ack_failed/no confirmation after a deliberately delayed ACK response. Production acknowledge_relay caps its request0.5s and confirms only exact returned delivered state; hook emits before ACK and reports failure truthfully. No source evidence of lost custody or a product fix is inferred.

This corrects the expiry test's assumption that a committed ACK response always arrives; it does not rewrite the accepted product contract. Existing confirmed-response control stays strict. Independent reviewer must assess this classification explicitly before implementation.
