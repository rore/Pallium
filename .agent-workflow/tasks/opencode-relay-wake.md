# OpenCode Relay wake

Owner: `@pal-dev1`, Codex session `01a1156c-e388-7850-9c42-cc2fcb5dbd51`.
Canonical source: `roadmap/features/add-wake-first-relay-delivery.md`, OpenCode automatic-activation slice only. The manager owns canonical roadmap edits; relaydev retains Codex recovery closure.
Task authorization (2026-10-07): user said "so look in the roadmap if we have a wake feature for opencode, and claim it. it's your job now to drive this implementation. is there missing info yet? something we still don't know?"

<!-- agent-workflow:start -->
**Outcome:** A connected OpenCode V2 recipient receives pending Relay work through an automatic exact-session turn, with safe busy deferral and recoverable submission uncertainty.
**Target:** Pallium OpenCode integration.
**Scope:** OpenCode V2 plugin compatibility, history capture and model-bound Relay receipt; exact-session native wake integration with existing Pallium delivery/recovery; caller-surface E2E, installed Windows qualification, integration docs and the owning roadmap slice.
**Constraints:** Preserve V1 passive next-turn support and Claude/Codex behavior; retain Pallium scope, expiry, claim, ACK and reply contracts; no duplicate plugin delivery ledger or exactly-once action claim; no live runtime/config replacement or service restart without coordinated ownership; no protected behavior-test changes; no changes to unrelated work.
**Completion criteria:** When an idle connected V2 session has pending Relay, it starts without another human prompt and sees the exact payload; when busy, delivery waits for a safe boundary; repeated or ambiguous native submission admits one stable native identity; ACK follows model-bound payload attachment; ordinary user and assistant turns remain retrievable; expiry, deletion, wrong scope, lease recovery, backlog, Unicode, service/application restart and disposal preserve the observable lifecycle contract.
**Requirement baseline:**
{"source":"user:2026-10-07; roadmap/features/add-wake-first-relay-delivery.md","outcome":"A connected OpenCode V2 recipient receives pending Relay work through an automatic exact-session turn, with safe busy deferral and recoverable submission uncertainty.","scope":"OpenCode V2 plugin compatibility, history capture and model-bound Relay receipt; exact-session native wake integration with existing Pallium delivery/recovery; caller-surface E2E, installed Windows qualification, integration docs and the owning roadmap slice.","constraints":"Preserve V1 passive next-turn support and Claude/Codex behavior; retain Pallium scope, expiry, claim, ACK and reply contracts; no duplicate plugin delivery ledger or exactly-once action claim; no live runtime/config replacement or service restart without coordinated ownership; no protected behavior-test changes; no changes to unrelated work.","completion_criteria":"When an idle connected V2 session has pending Relay, it starts without another human prompt and sees the exact payload; when busy, delivery waits for a safe boundary; repeated or ambiguous native submission admits one stable native identity; ACK follows model-bound payload attachment; ordinary user and assistant turns remain retrievable; expiry, deletion, wrong scope, lease recovery, backlog, Unicode, service/application restart and disposal preserve the observable lifecycle contract."}
**Risk:** High
**Complexity:** Moderate
**Reason:** Intended wake changes touch persisted Relay lifecycle and public enrollment boundaries; runtime-owned exact-session authority and replay fences are security/contract concerns. V2 hook migration plus native Windows qualification spans multiple components.
**Discovery:** Installed OpenCode is V1 1.18.19; its loader targets the stable clone. Source is at 17f9304b. Existing next-turn Relay has historical resumed live evidence; active OpenCode wake is absent. Exact V2 2.0.22 revision 527f0b931d1f9b3ebd34e106c51b31ce5db5b075 supplies imperative hooks and native durable inbox/idempotent IDs. First admission wins; native IDs require msg_ prefix. Prompt preparation precedes durable admission; context hook precedes provider dispatch. Managed restart is at least once, with an admission-before-execution-claim window. Roadmap's older separate plugin-ledger requirement is stale relative to the selected native V2 capabilities; reconcile in this slice without changing umbrella ownership.
**Material assumptions:** V2 context hooks and history capture operate through the released Windows binary; disprove with isolated capture/receipt probe and return to discovery. Native queue and same-ID retry preserve busy/restart behavior on that binary; disprove with isolated native inbox/readback witness and revisit scope before coding. A supported exact-session/server enrollment can reuse current Pallium authority boundaries without a duplicate queue; source discovery and threat review must establish this before final implementation planning. Global V1 remains installed until a separately coordinated delivery window.
**Plan:** First invoke Agent Workflow, create this Work Record and classify risk before any code edit (done). Continue bounded discovery of native V2 registration/lifecycle and isolated qualification prerequisites. Then write the concrete minimum implementation plan and obtain clean-context technical review plus separate human plan approval before production edits. Reuse native OpenCode queue/IDs and existing Pallium durable delivery/recovery. Stop on unsupported trusted enrollment, failed native qualification, or a material change to scope/authority/ACK semantics.
**Verification plan:** Idle send to exact V2 recipient -> real hook/model payload, ACK, response and idle witness with no human prompt. Busy send -> native queued readback and later payload receipt. Same-ID ambiguous retry -> one native inbox/history identity and no duplicate Relay action. Ordinary turn -> user/assistant retrieval with exact scope. Error/lifecycle matrix -> caller-surface HTTP/MCP/plugin E2E covering empty/max/over-max, missing/invalid/conflict/permission, expiry/lease/backlog, Unicode, restart and create-to-dispose. Whole-change selector -> affected checks, full non-slow suite once, workflow/redline/import checks and independent result review before PR delivery.
**Plan review:** Pending concrete implementation plan and clean-context technical review; discovery only.
**Approvals:** User authorized ownership and driving implementation on 2026-10-07 as quoted above. Separate approval of the concrete High-risk implementation plan is not yet recorded.
**Exceptions:** —
**State:** Blocked or returned to planning
<!-- agent-workflow:end -->

## Implementation

- 2026-10-07: accepted the OpenCode slice; isolated checkout `C:/Users/I347041/.codex/worktrees/opencode-relay-wake/Pallium`, branch `feat/opencode-relay-wake`, base `17f9304b0ee68081d7801075e507d97ac4909fe9`. Whole-change intended scope is non-exempt. Pre-edit Redline classification includes persistence/API/architecture checkpoints. No production code changed.
- Bounded read-only source extraction delegated to `opencode_v2_primitives`; it must report evidence without edits. Canonical roadmap ownership confirmation requested from `@pallium-manager` through Relay.

## Evidence

- Prior assessment and supplied research were checked against pinned V1/V2 upstream source. No released V2 Windows runtime witness yet; upstream CI is not installed qualification.
- Task-local pre-edit path/classification artifacts: `build/opencode-intended.z`, `build/redline-verdict.json`; these are diagnostics, not native mutation-prevention proof.

## Recovery

Next: resolve trusted exact server/session lifecycle, write the concrete implementation plan and verification matrix, perform independent plan review, then obtain required High-risk human plan approval. Preserve V1 installation and relaydev custody. Do not implement while those gates remain unresolved.
