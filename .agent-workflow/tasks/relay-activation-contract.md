<!-- agent-workflow:start -->
**Outcome:**
Relay recipient and status surfaces expose one compact, truthful activation-capability contract and canonical attempt-outcome vocabulary without conflating activation, payload admission, delivery, or destination health.

**Target:**
Pallium.

**Scope:**
Additive normalized activation capability/outcome types and current Claude Code, Codex, and passive/OpenCode mappings; correction of Claude transport, durable inflight, registration, and recovery transitions plus Codex health classification at their existing boundaries; existing Relay HTTP, MCP, and dashboard projections; focused E2E/unit fixtures; `docs/designs/017-relay-wake-phase0.md`, `docs/agent-relay.md`, and the feature/board/scope roadmap files.

**Constraints:**
No new activation engine, attempt ledger, persistence-format/storage/config/dependency change, probing by sending text, paid/model turns, optimistic support, task-completion inference, or duplicate native submission. Elapsed time, a still-pending/absent delivery query, worker completion, restart, clock movement, or an ordinary registration is never evidence that a native submission did not occur. Preserve delivery/ACK authority, exact-session and generation/CAS fences, legacy fields/callers, secret redaction, and current endpoint/history scope behavior. Do not touch `api/routes.py`, architecture-core red paths, or storage unless discovery invalidates the plan and returns it to review.

**Completion criteria:**
Every current qualified runtime/platform maps to bounded supported behavior, availability, fallback, evidence, and canonical `accepted|deferred|uncertain|failed` outcomes; HTTP, MCP, dashboard, docs, and fixtures agree; missing/stale/conflicting inputs fail closed; read-only queries have no delivery/native-write/model side effects; controlled adapter journeys prove accepted or post-frame uncertain Claude attempts survive worker completion, sweeps, restart, clock rollback, and ordinary registration without a second native write, while positively pre-frame failures remain retryable and correlated turn admission/close safely releases state; required boundary/lifecycle/Unicode/size/compatibility E2E and the repository full suite pass once before review.

**Risk:**
High

**Complexity:**
Moderate

**Reason:**
Pre-edit redline verdict is API_CHANGE because additive `api/schemas.py` response fields extend a public HTTP contract; semantic misclassification could induce unsafe retries. One repository/service is affected, but shared projections, adapters, and compatibility tests span several components.

**Discovery:**
The documentation-only applicability exemption cannot apply because production code and an HTTP schema must change. Current authority is split: Relay storage owns endpoint lifecycle, health, delivery state, and correlated ACK; `ClaudeWakeRegistry` owns `idle|busy|wake_inflight|unreachable` plus `accepted|retryable|unreachable` transport results; Codex owns `queued|ambiguous|failed` launch results and an in-process admission reservation. Claude `accepted` proves a local frame write without peer receipt; Codex `queued` proves CLI exit 0; neither proves turn start or payload admission. Two existing defects were reported immediately. First, Claude resets every uncertain `retryable` result to idle; independently, `recover_claude_relay_wakes()` calls `rearm_inflight(grace_seconds=1.0)` after worker completion and `rearm_inflight()` treats elapsed time, including clock rollback, as permission to resubmit. Ordinary `register()` can also overwrite `wake_inflight`. These sibling paths can blindly duplicate accepted or partial native writes, so the fix must remove time/status/registration-based release at the shared state authority and distinguish positive pre-frame no-submit from post-frame uncertainty. `clear_inflight()` is currently reached for any non-pending result, which conflates claimed, absent, and terminal state; correlated `/relay/turn` `mark_busy()` and exact close are the existing authoritative release signals. Second, Codex maps every local launch failure to destination `unreachable` although no recipient-absence proof exists. Existing `_relay_recipients_text`, `_relay_status_text`, and `_dashboard_relay_session` are bounded surface seams, while FastAPI response models require an additive schema field. Existing tests already cover Relay pagination, Unicode, lifecycle, conflicts, and MCP size trimming; activation semantics need controlled mapping and no-side-effect coverage. Pre-edit review found no boundary violation if the common type lives below API/app and imports no runtime adapter.

**Material assumptions:**
- A new small `core/relay_activation.py` value/projection module can depend only on plain values and remain independent of app/runtime adapters; if mapping requires importing app code, stop and redesign the dependency direction.
- Current registration, scheduler, platform qualification, and endpoint fields are sufficient for a truthful current snapshot. The existing durable `wake_inflight` delivery fence is sufficient for safe recovery if its release rules are corrected; no new attempt ledger or persistence-format field is required. If durable last-attempt readback is required, omit it in this slice and return any persistence expansion to planning.
- `api/routes.py` can remain unchanged because the existing Relay service result is decorated before Pydantic response filtering; if route orchestration is unavoidable, return to review with the exact reason.
- Legacy sessions with absent, stale, malformed, or conflicting evidence can be represented as unknown/passive fallback without changing send eligibility; if callers require optimistic defaults, stop because that conflicts with the roadmap contract.
- A native retry is safe only when the transport positively reports that the peer-message frame was never started. Once that frame may have started, keep the exact delivery fenced across worker completion, recovery sweeps, process restart, clock rollback, pending/absent status reads, and generic registration. Release only on the existing correlated Relay turn admission (`mark_busy`) or exact capability close; if implementation cannot preserve this with the existing durable record and CAS flow, stop and return to design review.

**Plan:**
1. Invoke `agent-workflow`, evaluate whole-change applicability, create this Work Record, and classify redline risk before any code edit (completed on `feat/relay-activation-contract`).
2. Finalize one bounded core contract: topology, supported turn behavior, evidence kinds, availability/provenance, fallback, and canonical attempt outcome. Reuse existing strings where equivalent; do not add speculative dimensions or an attempt ledger.
3. Map adapters inward at their existing result boundaries. Have Claude's transport identify whether the peer-message frame was never started or may have started: positive pre-frame no-submit becomes deferred/retry-safe; clean frame write becomes accepted; partial peer-frame write, timeout, or post-start exception becomes uncertain/not retry-safe; proven missing endpoint becomes failed/unreachable. At the registry authority, retain `wake_inflight` for accepted and uncertain attempts; remove elapsed-time rearm and recovery-status clearing; reject ordinary registration while inflight; release only through correlated Relay turn admission (`mark_busy`) or exact close. Preserve bounded retry for deferred pre-frame outcomes and natural-turn fallback for fenced outcomes. Map Codex `queued` to accepted queue-submission evidence, timeout/nonzero or post-submit ambiguity to uncertain, pre-submit local unavailability to deferred/failed without destination-health mutation, and only proven recipient absence to unreachable; passive/unqualified modes to deferred/natural-turn fallback. Keep correlated Relay turn/ACK as separate admission evidence.
4. Decorate existing session/status records once in the Relay/app composition seam, add one optional Pydantic projection, and preserve it through current MCP compactors and dashboard projection. Avoid route, storage, and client changes.
5. Reconcile Phase 0 design/fixtures with the canonical vocabulary, document developer-visible meaning/fallback, and update roadmap status only after verification.
6. Add focused mapping and caller-surface tests through HTTP/MCP/dashboard, including passive/idle/busy/unsupported/human-required, unknown/stale/conflicting, empty/max/over-max, Unicode, lifecycle/generation/concurrency/recovery, and read-only/no-side-effect assertions. Run focused files, `--lf`, workflow/redline checks, then the required full suite once.
7. Obtain independent result review, resolve every finding/thread, open the PR, and report it without merging or restarting the installed service.
Stop and return to planning if shared projection requires persistence, new activation behavior, adapter-to-core reverse imports, optimistic inference, or a second public interpretation.

**Verification plan:**
When each current runtime/platform is listed, HTTP, MCP, dashboard, docs, and fixtures shall report the same bounded capability/availability/fallback facts -> caller-surface E2E and exact projection assertions.
When native submission returns accepted, deferred, uncertain, or failed evidence, the adapter boundary shall map it canonically without marking delivery or permitting blind retry -> exact native-write-count tests for clean accepted, pre-frame failure, peer-frame partial write, timeout, completed-worker sweep, restart, clock rollback, late correlated admission, late ordinary registration, accepted-but-delayed admission, and exact close; preserve read-only Relay delivery state throughout.
When evidence is absent, stale, malformed, conflicting, Unicode-sized, or beyond the response budget, read paths shall fail closed and remain valid/bounded without side effects -> public HTTP/MCP/dashboard E2E with write/claim/model-call counters unchanged.
When legacy callers and session lifecycle transitions operate, existing fields, selection, aliases, scope generation, pending delivery, and ACK semantics shall remain compatible -> existing lifecycle suites plus focused regression cases.
Before PR review, redline/workflow checks and `python -m pytest tests/ -x -q` shall pass once with the exact revision recorded.

**Plan review:**
Pending clean-context reviewer and architect review; implementation is blocked until findings are resolved.

**Approvals:**
Approved by user 2026-09-12: "Second, the relay to operational tasks. You can advance with that and let's get them completed."

**Exceptions:**
—

**State:** Blocked
<!-- agent-workflow:end -->

## Implementation

- Created isolated worktree `C:\Dev\rore\Pallium\.worktrees\relay-activation-contract` on branch `feat/relay-activation-contract` from `27313e4e53f1baa502fbb3ef6e9331bdf7316ec6`.
- Evaluated applicability: production HTTP/MCP/dashboard and adapter changes require the normal workflow; no documentation-only exemption applies.
- Completed bounded read-only inventory and pre-edit redline classification. No production code has been edited.
- The first follow-up `apply_patch` hit the machine-local Windows process failure; the Work Record-only correction used one deterministic exact-string replacement as the repository-approved fallback.
- Sent the concrete design and adapter mapping to `astra-reviewer`; implementation remains blocked pending its verdict and clean-context plan review.
- Recorded the user's scoped authorization relayed by `astra-reviewer`; no additional permission question is required while implementation stays faithful to the approved roadmap contract.

## Evidence

- Roadmap requirement: `roadmap/features/add-relay-activation-capability-contract.md`.
- Pre-edit redline review: clean-context `/root/activation_redline` returned API_CHANGE, High/Moderate, no boundary violation in the recommended dependency direction, with `api-review` required.
- Read-only inventories: `/root/activation_inventory` and `/root/activation_surfaces` identified existing authority, mappings, public projection seams, and focused tests.
- Relay work association: `work:v1:7b792ebce40247954da55a8ce3d3fab316f28c56713e12feee195560ad8025fc`; participant lookup returned `pall-arc` and `astra-reviewer` only.

## Plan review

Pending.

## Result review

Pending.
