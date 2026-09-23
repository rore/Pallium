<!-- agent-workflow:start -->
**Outcome:** Relay senders describe a successful send as stored but delivery-unconfirmed, never as recipient activity, and give a safe conditional manual action when a response is needed now.

**Target:** Pallium.

**Scope:** Update the Relay send tool description, the canonical relevant Pallium skill/generation guidance, focused caller-visible guidance tests, this Work Record, and reconcile the owning Relay roadmap only if current status becomes inaccurate.

**Constraints:** No API, schema, state, polling, retry, wake, claim, ACK, scope, model, or effort behavior changes. `busy_queue` remains a capability, not observed busyness. Guidance must not promise that opening alone guarantees delivery, encourage interruption, or advise resend.

**Completion criteria:** A registered Relay sender sees concise guidance that send success means saved rather than started; pending delivery remains unconfirmed; urgent coordination may open the recipient task, wait for current work, and start an ordinary turn if needed without resending. Generated installed guidance matches its canonical source, existing transport behavior remains unchanged, and the roadmap remains accurate.

**Requirement baseline:**
{"source":"Pallium Relay delivery relay-delivery-4e115d774f534ccdbd200d5c93cbfa21","outcome":"Relay senders describe a successful send as stored but delivery-unconfirmed, never as recipient activity, and give a safe conditional manual action when a response is needed now.","scope":"Update the Relay send tool description, the canonical relevant Pallium skill/generation guidance, focused caller-visible guidance tests, this Work Record, and reconcile the owning Relay roadmap only if current status becomes inaccurate.","constraints":"No API, schema, state, polling, retry, wake, claim, ACK, scope, model, or effort behavior changes. `busy_queue` remains a capability, not observed busyness. Guidance must not promise that opening alone guarantees delivery, encourage interruption, or advise resend.","completion_criteria":"A registered Relay sender sees concise guidance that send success means saved rather than started; pending delivery remains unconfirmed; urgent coordination may open the recipient task, wait for current work, and start an ordinary turn if needed without resending. Generated installed guidance matches its canonical source, existing transport behavior remains unchanged, and the roadmap remains accurate."}

**Risk:** Elevated

**Complexity:** Simple

**Reason:** Clean-context Redline classification found gray runtime/integration guidance paths plus blue tests and workflow metadata, with no boundary, API, schema, security, configuration, or checkpoint finding. Simple because this is one concise guidance-only slice.

**Discovery:** The three runtime skill copies are the byte-identical source-of-truth convention used by their installers; there is no shared generator. The registered tool description is in `app/mcp/server.py`, with focused coverage in `tests/test_mcp_server.py`; copy alignment and the 2,800-byte skill budget are covered in `tests/test_guidance_budget.py`. The wake roadmap already states the unloaded-task and ordinary-turn limit, so no roadmap edit is needed.

**Material assumptions:** The existing tool-description and generated-skill test seams can prove the guidance without changing runtime contracts; if not, return to planning before widening scope. The owning roadmap already separates unloaded-task limitations and remains accurate unless implementation changes feature status.

**Plan:** Add one concise saved-versus-started/unconfirmed/manual-option rule to `pallium_relay_send`'s registered description and the three byte-identical runtime `pallium-memory` skill files. Keep the skill ceiling byte-neutral by condensing existing wording without dropping any tested requirement, safety constraint, or reference link. Extend the existing registered-tool and guidance-budget tests to pin wording, non-interruption, no-resend, copy equality, and budget. Do not touch setup generators or roadmap; stop and return to planning if wording requires runtime behavior, contract changes, a budget increase, or test weakening.

**Verification plan:** Registered send guidance states saved rather than started, delivery-unconfirmed, and the conditional ordinary-turn/no-resend action → `tests/test_mcp_server.py::test_relay_tools_are_registered`. Canonical runtime guidance remains identical and within budget while preserving transport behavior → focused `tests/test_guidance_budget.py` guidance test plus affected MCP/Relay tests. Repository workflow and boundary requirements remain clean → Agent Workflow local check and required pre-PR suite.

**Plan review:** Clean-context review: see `## Plan review`.

**Approvals:** Not required at this risk level.

**Exceptions:** —

**State:** Ready for review
<!-- agent-workflow:end -->

## Plan review

APPROVED by clean-context agent `review_sender_guidance_plan`. The tool description plus three byte-identical skill sources and focused tests are the minimum caller-visible set; the roadmap already remains accurate. Follow-up approval covers byte-neutral condensation only when every tested requirement, safety constraint, and reference link remains, the 2,800-byte ceiling is not raised, and tests are not weakened.
## Implementation

Pre-edit Redline classification: GRAY / Elevated, Simple. Focused discovery identified the registered tool and three byte-identical skill sources; plan review approved the minimal byte-neutral guidance change. `apply_patch` hit documented Windows error 1385, and the Git-native patch attempt was malformed, so subsequent edits used assertion-checked deterministic PowerShell replacement.

Updated the registered `pallium_relay_send` description and all three byte-identical runtime skills. Added focused assertions for saved-versus-started, `busy_queue` capability semantics, unconfirmed pending state, non-interruption, ordinary-turn recovery, and no-resend. Kept behavior unchanged and the skill at the existing 2,800-byte ceiling. Review found a dropped Minimap continuity condition; it was restored and pinned. Broad testing found exact private/global visibility wording had been compressed away; both contracts were restored.

## Evidence

- Focused guidance/registration set: 5 passed.
- Affected guidance/MCP files: 89 passed.
- Restored-contract set: 7 passed; last-failed set: 10 passed.
- Final consuming files: 157 passed.
- Required full suite: 5,259 passed, 34 skipped, 2 xfailed in 240.09s.
- Three runtime skills are byte-identical and exactly 2,800 UTF-8 bytes.
- Roadmap inspection: current unloaded-task and ordinary-turn limitation remains accurate; no edit required.

## Result review

APPROVED by clean-context agent `review_relay_sender_guidance`. Two review/testing findings were addressed before approval: restore the Minimap `when continuity helps` criterion and the imperative to revalidate completed sources by content revision; exact private/global visibility wording was also restored after broad testing exposed it.
