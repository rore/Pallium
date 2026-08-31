<!-- agent-workflow:start -->
**Outcome:** Codex Relay can passively claim and publish bounded whole batches through one regular-turn/hook and MCP-recovery ownership path, while wake remains disabled until G2/G3 evidence.

**Target:** Pallium Relay milestone 1, B2 passive batch delivery.

**Scope:** Review-only planning for complete-batch FIFO/budgets, claim generation/publication fencing and uncertain lifecycle, hook/MCP recovery parity, protocol capability/scope/deduplication corrections, and deterministic HTTP/MCP/hook E2E/fault coverage. Intended guarded targets: `api/schemas.py`, `api/routes.py`, `core/relay.py`, `storage/sqlite_schema.py`, `storage/sqlite_relay.py`, `storage/relay_codec.py`, `app/mcp/client.py`, `app/mcp/server.py`, Codex integration guidance/hook path, and their focused tests.

**Constraints:** B1 foundation is accepted at `c3dd006`; do not reopen it. No guarded B2 edit before manager review. No C/Claude/OpenCode wake adapter, public multipart/keyed-MCP activation, startup migration, installer/service/configuration/live-DB action, deployment, app ping as a delivery mechanism, manual hook receive/ACK, raw Relay HTTP, or `uv.lock` change.

**Completion criteria:** A manager-reviewed implementation plan states exact file ownership, activation order, stop conditions, and G2/G3 evidence paths. It preserves one complete-batch claim owner for hook and MCP recovery and leaves automatic wake disabled pending evidence.

**Risk:** High

**Complexity:** Large

**Reason:** The intended scope includes red API contracts and persisted schema plus durable claim/publication lifecycle and runtime identity behavior. It spans storage, core, MCP, hook integration, and independently verifiable fault evidence.

**Discovery:** B1 is an unactivated persistence/codec/request foundation (`c3dd006`). The approved design `docs/designs/relay-batch-codex-wake.md` requires one FIFO whole-batch claim path shared by ordinary and notification turns and MCP recovery; publication starts are generation-fenced, incomplete admission is uncertain rather than replayed, and G2/G3 remain release evidence. The existing hook fixtures are historical and require replacement or explicit historical labelling when B2 changes the contract.

**Material assumptions:** (1) The current hook and explicit MCP recovery can share one storage-owned claim/admission contract; prove by symmetric integration E2E or stop for design review. (2) A claim generation can fence a stale publisher before output; prove by controlled claim replacement/fault tests or retain no automatic replay. (3) Full-envelope runtime admission evidence and actual context headroom are not currently proven; G2/G3 failure keeps wake disabled and capacity/passive status visible. (4) Pre-edit redline review has no boundary violation; any finding stops guarded edits.

**Plan:** (1) Obtain clean-context redline classification and manager review before guarded edits. (2) Define the smallest storage/core/API contract that selects complete FIFO batches up to existing design budgets, records claim generation/lease/final digest and length, and refuses stale publication. (3) Route hook and MCP recovery through that same claim/render/admit operation; natural-prompt dedupe cannot suppress inbox draining and the fast path emits current exact Pallium scope with the full attributed envelope. (4) Add capability/status fields and protocol-compatibility blocking without enabling public multipart/keyed-MCP or C queue dispatch. (5) Add HTTP/MCP/hook E2E for FIFO/budget boundaries, concurrent claim/recovery ordering, publication interruption/replacement, uncertain reconciliation, scope/dedupe, restart/expiry and compatibility failures. Stop if a change needs a second payload path, crosses API/storage boundaries, requires live migration, or lacks G2/G3 evidence.

**Verification plan:** When a turn claims eligible batches, it shall select complete FIFO batches within the published 8-batch/16,384-code-point/65,536-byte budget without skipping the oldest fitting policy → disposable SQLite HTTP/MCP/hook E2E. When a claim is replaced or publication began without admission, stale output shall be rejected and the outcome remain uncertain rather than replayed → generation/fault-injection E2E. When hook and explicit recovery contend, exactly one owner shall render the same whole batch and current scope → paired hook/MCP race E2E. When a recipient is incompatible, over capacity, expired, or has invalid stored data, status shall expose the block without disclosure or partial delivery → HTTP/MCP lifecycle E2E. G2 requires installed full-envelope immutable context-commit plus stale-publisher evidence; G3 requires measured 64-delivery/context headroom. Neither deterministic test substitutes for either gate.

**Plan review:** Clean-context redline review (`/root/b2_redline`, 2026-08-31) classified the intended scope as MIXED → High: red API and schema surfaces require API and persistence review; gray guarded runtime/storage surfaces require architecture/runtime review; security review remains an explicit B gate. No inherent boundary violation was found. Manager review remains pending; no implementation approval is recorded by this planning checkpoint.

**Approvals:** Approved by user 2026-08-31: "i approve everything the architect tells you to do". Architect B1 approval authorizes B2 planning only; manager review is still required before guarded B2 edits.

**Exceptions:** —

**State:** Blocked
<!-- agent-workflow:end -->

## Implementation

- 2026-08-31: Created on `codex/relay-batch-wake-b2` from accepted B1 commit `c3dd006`. This is planning only. Next action is manager review of the clean-context classification and this bounded plan; no guarded B2 source, service, configuration, installer, or live database action has occurred.

## Plan review

- 2026-08-31 clean-context review (`/root/b2_redline`): **MIXED → High**. `api/schemas.py` and `api/routes.py` require API review; `storage/sqlite_schema.py` requires persistence review. `core/relay.py`, `storage/sqlite_relay.py`, `storage/relay_codec.py`, and MCP client/server are guarded gray surfaces. No boundary violation is inherent if API imports only core, storage never imports app/capabilities, and runtime adapter composition remains outside core. Architecture/runtime and security review remain explicit B gates. G2/G3 are qualification evidence, not approval substitutes.