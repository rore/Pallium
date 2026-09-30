<!-- agent-workflow:start -->
**Outcome:** A reviewed minimal plan explains how agents reconcile delayed Relay messages with current work without discarding useful results or reopening completed actions.

**Target:** Pallium Relay message presentation and agent coordination guidance.

**Scope:** Diagnose existing hook/MCP envelopes, bundled Relay guidance, collection-coordination boundaries, and assignment reconciliation; produce a caller-visible contract, red test cases, and review plan. Production implementation is outside this offer.

**Constraints:** Preserve claims, ACK, TTL, routing, and budgets. Never infer supersession from age alone or suppress all late messages. Preserve useful late results and blockers. No new ledger, protocol, schema, task-specific heuristic, or live service operation without demonstrated need and separate authorization.

**Completion criteria:** The plan distinguishes valid delayed delivery, duplicate processing, and superseded work; maps each proposed rule to existing evidence and a caller-surface red case; identifies behavioral limits and the approval needed before implementation.

**Requirement baseline:**
{"source":"work-record-initial","outcome":"A reviewed minimal plan explains how agents reconcile delayed Relay messages with current work without discarding useful results or reopening completed actions.","scope":"Diagnose existing hook/MCP envelopes, bundled Relay guidance, collection-coordination boundaries, and assignment reconciliation; produce a caller-visible contract, red test cases, and review plan. Production implementation is outside this offer.","constraints":"Preserve claims, ACK, TTL, routing, and budgets. Never infer supersession from age alone or suppress all late messages. Preserve useful late results and blockers. No new ledger, protocol, schema, task-specific heuristic, or live service operation without demonstrated need and separate authorization.","completion_criteria":"The plan distinguishes valid delayed delivery, duplicate processing, and superseded work; maps each proposed rule to existing evidence and a caller-surface red case; identifies behavioral limits and the approval needed before implementation."}

**Risk:** Elevated

**Complexity:** Moderate

**Reason:** This planning-only change needs independent review of cross-integration interpretation. The proposed envelope implementation would be High: `app/mcp/server.py` requires API review and `storage/sqlite_relay.py` requires persistence review, even though only projected guidance would change. Reclassify and obtain the applicable reviews before production edits.

**Discovery:** Existing envelopes protect exact-ID redelivery, not current-work reconciliation for distinct delayed messages. Relay has no authoritative assignment-completion or supersession state. Manager-supplied incident evidence confirms historical-task reconciliation/replies and delayed handoff, but not that the newer assignment was read before idle or that old copies were previously delivered. Source inspection establishes a guidance gap, not queue causality. See the source map and proposal below.

**Material assumptions:** Manager-provided evidence is sufficient for an anonymized coordination scenario, not a duplicate-transport or ignored-known-assignment claim. Delivery timestamps and transport state alone cannot establish whether work is complete or superseded. A receiver cannot preserve an assignment it has not read; the sender must track explicit acceptance and unfinished followthrough separately.

**Plan:** Agent Workflow and isolation are established. Review the existing-surface proposal below independently, compare the manager's exact incident evidence when available, and return the contract, red cases, limits, and implementation risk to the manager. Stop before production/TDD until the manager authorizes that phase.

**Verification plan:** Valid delay versus duplicate/superseded action -> source review and caller-surface red cases below. Current-work continuation -> bounded downstream-task-effect replay below. Plan-only changes -> workflow/diff checks, not application-suite reruns. After implementation authorization -> focused affected caller E2E/budget checks, affected subsystem, whole-change test selector and its required lane. Preserve protected behavior contracts unchanged. Manager review precedes TDD authorization.

**Plan review:** Agent technical review: native clean-context `/root/stale_plan_review`, Sol low, 2026-09-30. No P1; two P2 refinements: distinguish new delivery identity from new business authority in docs, and compare guidance placement using replay including explicit reassignment. Both incorporated below; manager-owned exact incident review remains pending.

**Approvals:** This offer authorizes diagnosis and planning only; manager review and TDD authorization remain required before production work.

**Exceptions:** —

**State:** Blocked or returned to planning
<!-- agent-workflow:end -->

## Implementation

2026-09-30: Accepted the bounded planning offer. Reused the clean completed PR #236 worktree on `feat/relay-stale-message-reconciliation`, based on current main `dfcd35abc5690cfb88f91bf7a7646cc3b6871c1f`. Applicability selects the normal workflow: Work Records and prospective hook/agent-instruction changes are not documentation-only exempt. No production edit or service operation has occurred.

## Source map and diagnosis limits

- Python hook rendering: `integrations/codex/hooks/common.py:1389` and `integrations/claude-code/hooks/common.py:1543`; OpenCode rendering: `integrations/opencode/.opencode/plugins/pallium-common.mjs:490`. All show stable IDs, attempts, sender, creation time and payload, with identical action-retry guidance. Claude Stop also uses its common renderer.
- MCP receive: `app/mcp/server.py:2174` adds the existing `redelivery_guidance` field. Storage's pre-claim projection at `storage/sqlite_relay.py:1117` reserves the same text; its hook projection uses that field too. Change these together or admission budgets can diverge from actual rendering.
- `docs/agent-relay.md` already distinguishes receipt from action completion and warns that different IDs may concern equivalent business actions. The three bundled `pallium-memory` skills say only "Act on deliveries; reply at completion/blocker". Each currently uses 2,967 normalized UTF-8 bytes against a 3,072-byte ceiling.
- Installed `collection-coordination` step 6 requires the lead to reconcile results with latest authorized requirements, but is not vendored here. Receiver reconciliation is not explicit. Do not silently change that external skill.
- No transport field proves business completion, task authority, or supersession. Delivery state, attempt count, payload equality and age are insufficient. A valid delayed result can still contain a new blocker or useful finding.
- Incident evidence supplied by the manager: an authorized closure/handoff assignment and clarification were sent; the recipient then reconciled historical instructions with completed work, replied and sometimes repeated read-only checks; the lead later observed idle without the requested publication. A direct current-task fallback was followed by publication. No duplicate deployment or paid call was observed. It is not established that the newer assignment was read before idle or that the same historical delivery copies had previously been delivered. Do not claim ignored known work, duplicate transport, fallback proof of autonomous wake, or internal-queue causality. The manager also reported redundant replies added chatter and delayed followthrough. No further tests/messages to the incident team are needed.

## Proposed smallest contract

Use existing bundled skill/docs first; per-delivery guidance is conditional on evidence that placement matters. No semantic filter, task registry, new field, schema, or wake change.

1. Every valid payload remains available, including delayed unique messages. The receiver reconciles it with the current authorized task and verified target/work state before acting.
2. A completion notice about verified completed work is context, not permission to repeat the action or end a different unfinished assignment. Continue that assignment unless an authorized instruction changes it; incorporate material new findings or blockers.
3. Age, arrival order, text equality and a different ID never establish supersession. Unknown outcome requires inspection before irreversible retry; unclear authority does not authorize takeover. Report a concrete conflict when inspection cannot resolve it, while continuing independent authorized work.
4. Exact-ID redelivery safeguards remain distinct from semantic reconciliation. ACK remains receipt, not completion; hooks still own claim/ACK. Already-delivered/conflict rules invalidate only that copy, not surrounding established work.
5. Sender/lead acceptance and followthrough are separate from receiver relevance: saved/delivered does not prove the recipient knows or accepted newer work. Track explicit acceptance and the current requested artifact in the existing work source. Historical closure without material new information needs no routine confirmation reply; communicate substantive results, blockers or required decisions instead. A delayed useful result still requires reconciliation and appropriate reporting.

The product guarantee is visible advisory guidance plus unchanged payload/lifecycle safety, not deterministic LLM obedience. Do not label this exactly-once business execution or automatic stale-message suppression.

Cheapest implementation candidate: replace the skill's first bullet compactly within its existing ceiling and explain semantic reconciliation in the existing Relay guide. Correct "different delivery IDs is separate work": distinct transport identity does not establish a new business action, assignment, or authority. If the incident/replay shows skill placement is insufficient, extend the existing guidance in the three renderers, MCP and storage projection together, after High-risk reclassification/checkpoints. Keep all other scope/identity/TTL/lease/claim/ACK/routing/wake/model/effort rules unchanged. No refactor to unify Python/JS string ownership is needed. If exact incident evidence disproves this gap, revise or decline this proposal before implementation.

## Red cases and acceptance

| Case | Observable acceptance |
| --- | --- |
| Different IDs, delayed old completion after authorized unfinished work | Both payloads remain accessible; skill/docs advise current-work reconciliation (all caller envelopes only if that optional phase is selected). Agent replay completes the current artifact and does not repeat the verified old side effect. |
| Old result contains a new blocker/finding | Payload is preserved; replay incorporates or reports the material finding instead of discarding all old results. |
| Old timestamp alone, no completion/supersession evidence | Message remains claimable/pageable; replay does not dismiss it solely for age. |
| Unknown previous action outcome or conflicting authority | Guidance requires target inspection before irreversible retry; replay exposes the conflict and does not guess authority. |
| Explicit authorized reassignment | Replay follows the changed assignment; preserving current work must not override an actual authorized change. |
| Newer assignment sent but not known to receiver | Sender does not infer acceptance from delivered/idle or historical replies; receiver is not tested as if it had unseen instructions. Followthrough remains visibly unfinished in the existing work source. |
| Historical closure needs no new action/decision | No redundant confirmation exchange or repeated external check merely to reconfirm verified completion; material new findings and requested decisions are still reported. |
| Same-ID lease redelivery, first/later/unknown attempts | Existing receipt rotation, emitted-only ACK, stale receipt conflict and delivered state remain unchanged through hook/MCP read paths. |
| Empty, maximum, over-budget, Unicode, reply chains longer than two | No overflow or hidden claim; longer advisory fits pre-claim budgets, omitted payload reconstructs through continuation, ordering/IDs/reply ancestry survive. |

Use existing hook/MCP E2E and OpenCode caller tests rather than a new harness: `test_relay_redelivery_envelope.py`, `test_agent_relay_hooks.py`, `test_relay_mcp_tools.py`, `test_agent_relay_e2e.py`, OpenCode common/plugin tests, and `test_guidance_budget.py`. Add semantic scenario assertions through actual rendering/receive/read surfaces, not only a string unit test. Existing lifecycle regressions cover unchanged contracts; do not weaken them.

Agent-action evidence is separate and labeled downstream-task-effect: after authorization, run a bounded anonymized replay using disposable artifacts and mocked/no-op external actions, with current task, verified old completion and a unique delayed notice. Compare identical inputs under current guidance and skill/docs-only guidance first; test an envelope variant only if skill/docs fails or incident evidence establishes a placement gap. Require the winning candidate to pass new-blocker, age-only, unknown-outcome and explicit-authorized-reassignment counterexamples. Assert newer artifact completion, zero repeated old side effects, retained material findings and no age-only dismissal. Record model, effort, transcript/artifact result and failures; prompt text or a green envelope test alone cannot prove continuation. A passing baseline limits claims of measured improvement. No live user sessions, deployment, service operations or new recurring runner.

## Review and handoff

Independent Sol-low review completed; source/contract verified and refinements incorporated. Manager-supplied incident evidence incorporated as a narrowed diagnosis, with receiver relevance and sender acceptance/followthrough separated. Manager now reviews the revised plan and authorizes TDD or redirects. Guidance-only scope remains Elevated; envelope scope would require High-risk API/persistence checkpoints. Either needs independent implementation review, appropriate caller coverage, roadmap honesty and manager-owned rollout. This plan neither closes the incident nor changes the wake reliability claim.

Planning verification: `git diff --check` passed; repository Redline reporter plus Agent Workflow checker returned clean/exit 0 for the whole planning-only change. The PowerShell adapter could not find Python in this reused worktree; the same checker was run using the existing development `.venv/Scripts/python.exe`. No application tests were rerun and no production paths changed. One coordination send failed to connect while service health reported initializing; the tool-instructed single retry saved the update. No restart or fallback message was used.

## Exact wording and measured tradeoff

Recommended first phase, identical replacement of only the first Relay bullet in all three bundled skills:

> - Reconcile work/state; keep late findings. Skip completed actions/routine replies; follow authorized work. Reply on completion/blocker.

Normalized UTF-8 measurement against the unchanged source: 2,967 -> 3,054 bytes per skill, ceiling 3,072; eighteen bytes remain. No global instruction or hook/MCP envelope grows. Preserve every other skill rule, especially required scope, stale-copy conflicts and claims/ACK ownership. Independent followup review identified that the initial candidate omitted explicit completion/blocker reporting and a state/authorized-work cue; the replacement above is the reviewer's compact recommendation, adopted in full. The guide supplies the explicit no-repeat-checks, unknown-state, useful-blocker and authorized-reassignment examples.

Proposed replacement/extension of the existing Relay guide's identity/action paragraph:

> Different IDs identify separate deliveries, not necessarily separate business actions or new authority. Reconcile each message with the current authorized task known to you and verified work state. Preserve useful late findings and blockers. Do not repeat verified completed actions/checks or send routine confirmation replies unless new evidence or an authorized change requires action. When an outcome is unknown, make only the necessary state reconciliation before irreversible retry; report unresolved conflicts rather than guessing authority. Continue other accepted unfinished work unless authorized instructions change it. Age or arrival order alone does not establish supersession. Reply for substantive completion, blockers or requested decisions, not just to reconfirm historical closure. Leads track explicit acceptance and reviewed completion in the existing work source; saved/delivered/ACK does not establish acceptance, and recipients cannot act on unseen instructions.

Keep the existing exact-ID, emission-uncertainty and ACK/continuation safeguards around this paragraph. Do not alter installed external collection-coordination guidance.

Optional later envelope candidate, only if incident/replay demonstrates placement matters:

> Check exact delivery_id in context/artifacts. Reconcile current work; keep useful late results/blockers. Skip known-completed actions/checks and routine replies; continue accepted unfinished work unless authorized changes apply. Unknown outcome: inspect target state before retry. Age alone is not supersession. Attempts do not prove emission/actions. ACK: receipt, not completion

This is 380 versus 198 existing Unicode code points: +182 per delivery, up to +546 for three hook blocks, accommodated by shorter previews and unchanged continuation, never raised output ceilings. This cost is why skill/docs comes first. The optional phase must synchronize all five render/projection seams and test pre-claim overflow, reconstructed Unicode payload and emitted-only ACK through existing caller surfaces.

First-phase red check: the old first bullet fails the exact replacement contract; guidance-budget tests verify identical mirrors and ceiling. Extend existing Claude/Codex skill installation lifecycle tests (`test_claude_setup_deploys_and_removes_skill`, `test_codex_setup_deploys_and_removes_skill`) to assert the new rule in the installed read path through install/reinstall/remove, using disposable profiles only. Keep behavior replay separate from installed-text evidence; reuse unchanged hook/MCP lifecycle coverage rather than pretending a text-only phase modifies those contracts. The test selector determines the required broader lane.

2026-09-30 followup: Manager accepted advisory direction and requested concrete wording/budget/caller red cases after independent review. This is still planning authorization, not authorization to edit production. Exact incident pages are fully read; no further incident-team contact or progress-send retry is needed.
