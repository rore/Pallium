<!-- agent-workflow:start -->
**Outcome:**
Relay recipient and status surfaces expose one compact, truthful activation-capability contract and canonical attempt-outcome vocabulary without conflating activation, payload admission, delivery, or destination health.

**Target:**
Pallium.

**Scope:**
Additive normalized activation capability/outcome types and current Claude Code, Codex, and passive/OpenCode mappings; correction of Claude transport/durable-fence transitions, exact-delivery turn-admission correlation, and Codex health/restart recovery at their existing boundaries; existing Relay HTTP, MCP, and dashboard projections; focused E2E/unit fixtures; `docs/designs/017-relay-wake-phase0.md`, `docs/agent-relay.md`, and the feature/board/scope roadmap files.

**Constraints:**
No new activation engine, attempt ledger/history, Relay storage table, dependency, probing by sending text, paid/model turns, optimistic support, task-completion inference, or duplicate native submission. Permit only the minimum trusted-local durability required for current-attempt safety: backward-compatible Claude fence fields (`recipient_endpoint_id`, `expected_claim_attempt`) and one bounded Codex current-reservation file/configured directory; neither stores history. The internal successful `/relay/turn`, ACK, MCP-ACK, and atomic-reply callbacks may receive their already-computed result/request identity so release can match exact admitted/delivered reservations; no public request field is added. Internal pending/wake candidate reads may add the existing `attempts` column needed for fresh CAS; no database schema changes. Elapsed time, a still-pending/absent delivery query, worker completion, restart, clock movement, or an ordinary registration is never evidence that a native submission did not occur. Preserve delivery/ACK authority, exact-session and generation/CAS fences, legacy fields/callers, secret redaction, and current endpoint/history scope behavior. Touch `api/routes.py` only for internal successful turn/ACK/MCP-ACK/atomic-reply callback results, and `storage/sqlite_relay.py` only to add existing `attempts` to internal candidate projections; do not touch architecture-core red paths or database schema unless discovery invalidates the plan and returns it to review.

**Completion criteria:**
Every current qualified runtime/platform maps to bounded supported behavior, availability, fallback, evidence, and canonical `accepted|deferred|uncertain|failed` outcomes; HTTP, MCP, dashboard, docs, and fixtures agree; missing/stale/conflicting inputs fail closed; read-only queries have no delivery/native-write/model side effects; controlled adapter journeys prove accepted or post-frame uncertain Claude attempts survive worker completion, sweeps, restart, clock rollback, and ordinary registration without a second native write, while positively pre-frame failures remain retryable only after the safe reset is durably recorded and exact claim-generation admission or definitive delivery safely releases state; required boundary/lifecycle/Unicode/size/compatibility E2E and the repository full suite pass once before review.

**Risk:**
High

**Complexity:**
Moderate

**Reason:**
Pre-edit redline verdict is API_CHANGE because additive `api/schemas.py` response fields extend a public HTTP contract; semantic misclassification could induce unsafe retries. One repository/service is affected, but shared projections, adapters, and compatibility tests span several components.

**Discovery:**
The documentation-only applicability exemption cannot apply because production code and an HTTP schema must change. Current authority is split: Relay storage owns endpoint lifecycle, health, delivery state, and correlated ACK; `ClaudeWakeRegistry` owns `idle|busy|wake_inflight|unreachable` plus `accepted|retryable|unreachable` transport results; Codex owns `queued|ambiguous|failed` launch results and an in-process admission reservation. Claude `accepted` proves a local frame write without peer receipt; Codex `queued` proves CLI exit 0; neither proves turn start or payload admission. Two existing defects were reported immediately. First, Claude resets every uncertain `retryable` result to idle; independently, `recover_claude_relay_wakes()` calls `rearm_inflight(grace_seconds=1.0)` after worker completion and `rearm_inflight()` treats elapsed time, including clock rollback, as permission to resubmit. Ordinary `register()` can also overwrite `wake_inflight`. These sibling paths can blindly duplicate accepted or partial native writes, so the fix must remove time/status/registration-based release at the shared state authority and distinguish positive pre-frame no-submit from post-frame uncertainty. `clear_inflight()` is currently reached for any non-pending result, which conflates claimed, absent, and terminal state. Review proved the existing `/relay/turn` callback is not correlated: it passes only request scope and `mark_busy()` clears whichever attempt is current. The smallest exact authority is the successful turn result already returned by Relay: extend the internal callback to receive that result and release only when its claimed delivery IDs include the fenced delivery. Definitive ACK/MCP-ACK/atomic reply of that exact delivery is the other release signal; close, absence, and expiration are not. Second, Codex maps every local launch failure to destination `unreachable` although no recipient-absence proof exists. Existing `_relay_recipients_text`, `_relay_status_text`, and `_dashboard_relay_session` are bounded surface seams, while FastAPI response models require an additive schema field. Existing tests already cover Relay pagination, Unicode, lifecycle, conflicts, and MCP size trimming; activation semantics need controlled mapping and no-side-effect coverage. Pre-edit review found no boundary violation if the common type lives below API/app and imports no runtime adapter.

**Material assumptions:**
- A new small `core/relay_activation.py` value/projection module can depend only on plain values and remain independent of app/runtime adapters; if mapping requires importing app code, stop and redesign the dependency direction.
- Current registration, scheduler, platform qualification, and endpoint fields are sufficient for a truthful current snapshot. The existing durable Claude `wake_inflight` record needs stable recipient endpoint identity and expected Relay claim attempt so scope movement cannot bypass the fence and delayed callbacks cannot release a newer attempt for the same delivery. Codex needs a bounded trusted-local current-reservation file because process-local sets cannot distinguish submitted from never-submitted work after restart. Both exclude concurrent reservations by stable Relay endpoint across container moves; container/scope generation is validation context, not the key. These are current fences, not attempt history; if either expands beyond exact endpoint/session/scope validation, delivery, expected claim attempt, and state needed for CAS, stop and return to review. If durable last-attempt readback is required, omit it in this slice and return any persistence expansion to planning.
- `api/routes.py` requires internal callback-signature changes so already-computed successful turn/ACK/MCP-ACK/atomic-reply facts can correlate release; internal candidate reads add the existing attempt counter, while public request/response and database schema remain unchanged. Any broader route/storage orchestration returns to review.
- Legacy sessions with absent, stale, malformed, or conflicting evidence can be represented as unknown/passive fallback without changing send eligibility; if callers require optimistic defaults, stop because that conflicts with the roadmap contract.
- A native retry is safe only when the transport positively reports that the peer-message frame was never started. Once that frame may have started, keep the exact delivery fenced across worker completion, recovery sweeps, process restart, clock rollback, pending/absent status reads, and generic registration. Release only when a successful Relay turn result contains the stable endpoint, exact delivery ID, and an observed claim attempt at least the reserved expected attempt, or when ACK/MCP-ACK/atomic reply definitively delivers that exact delivery. Close/expiration/absence never releases a reservation; if implementation cannot preserve this with the existing durable record and CAS flow, stop and return to design review.

**Plan:**
1. Invoke `agent-workflow`, evaluate whole-change applicability, create this Work Record, and classify redline risk before any code edit (completed on `feat/relay-activation-contract`).
2. Finalize one bounded core contract: topology, supported turn behavior, evidence kinds, availability/provenance, fallback, and canonical attempt outcome. Reuse existing strings where equivalent; do not add speculative dimensions or an attempt ledger.
3. Map adapters inward at their existing result boundaries and reserve before native I/O. Claude transport distinguishes positive pre-frame no-submit (deferred/retry-safe), clean peer-frame write (accepted), partial peer-frame write/timeout/post-start exception (uncertain/not retry-safe), and proven missing endpoint (failed/unreachable). Extend durable `wake_inflight` with stable `recipient_endpoint_id` and `expected_claim_attempt`; accepted/uncertain retain it, pre-frame retry is enabled only after an idle reset durably commits, and failed reset remains fenced. Delete elapsed/status rearm; never evict inflight for capacity or legacy recovery; merge valid newer credentials while preserving the fence and consume that intent. Legacy inflight without endpoint/attempt fields conservatively excludes the same runtime session across scopes and releases only on its exact delivery admission. Add a bounded trusted-local Codex current-reservation store keyed for exclusion by stable endpoint ID, with session/container/scope validation, delivery ID, expected claim attempt, and a reservation generation token; reserve atomically before queue launch, retain on accepted/uncertain/crash, and clear a definitive pre-submit failure only after durable removal. Every direct send/reply, idempotent replay, ACK continuation, periodic recovery, and startup recovery enters one reserve operation that, under the same reservation lock used by callbacks, performs a fresh `pending_candidate(delivery_id)` read, verifies endpoint/scope/state, derives `expected_claim_attempt = current.attempts + 1`, persists, and returns the generation token. A worker launches only if that token is still current. Delayed candidate snapshots are never authoritative. Successful turns release only when stable endpoint and delivery match and observed `attempts >= expected_claim_attempt`; older same-delivery results fail CAS. Definitive ACK/MCP-ACK/atomic reply releases that exact delivery. Close, expiration, absence, elapsed time, and scope movement never release; reactivation remains fenced until exact admission/delivery, so delayed close cannot erase newer state. Codex local launch failures never mark destination unreachable. Passive/unqualified modes use deferred/natural-turn fallback. Keep Relay claim/ACK as separate admission/delivery evidence.
4. Decorate existing session/status records once in the Relay/app composition seam, add one optional Pydantic projection, and preserve it through current MCP compactors and dashboard projection. Change `api/routes.py` only to pass already-computed successful turn/ACK/MCP-ACK/atomic-reply facts to internal callbacks; add `attempts` only to internal candidate read results; make no public request/database-schema/client change.
5. Reconcile Phase 0 design/fixtures with the canonical vocabulary, document developer-visible meaning/fallback, and update roadmap status only after verification.
6. Add focused mapping and caller-surface tests through HTTP/MCP/dashboard, including passive/idle/busy/unsupported/human-required, unknown/stale/conflicting, empty/max/over-max, Unicode, lifecycle/generation/concurrency/recovery, and read-only/no-side-effect assertions. Run focused files, `--lf`, workflow/redline checks, then the required full suite once.
7. Obtain independent result review, resolve every finding/thread, open the PR, and report it without merging or restarting the installed service.
Stop and return to planning if shared projection requires persistence, new activation behavior, adapter-to-core reverse imports, optimistic inference, or a second public interpretation.

**Verification plan:**
When each current runtime/platform is listed, HTTP, MCP, dashboard, docs, and fixtures shall report the same bounded capability/availability/fallback facts -> caller-surface E2E and exact projection assertions.
When native submission returns accepted, deferred, uncertain, or failed evidence, the adapter boundary shall map it canonically without marking delivery or permitting blind retry -> exact native-write-count tests for clean accepted, pre-frame failure plus reset-persistence failure, peer-frame partial write, timeout, completed-worker sweep, restart, clock rollback, late unrelated/older callback, fresh-baseline race and same-delivery out-of-order claim callbacks, exact claim-generation admission, late credential/legacy intent, capacity pressure, accepted-but-delayed admission, close/reactivation with delayed close and old worker completion, cross-container endpoint movement, and Codex accepted/uncertain fresh-process plus idempotent-send/reply/ACK-rearm recovery; preserve read-only Relay delivery state throughout.
When evidence is absent, stale, malformed, conflicting, Unicode-sized, or beyond the response budget, read paths shall fail closed and remain valid/bounded without side effects -> public HTTP/MCP/dashboard E2E with write/claim/model-call counters unchanged.
When legacy callers and session lifecycle transitions operate, existing fields, selection, aliases, scope generation, pending delivery, and ACK semantics shall remain compatible -> existing lifecycle suites plus focused regression cases.
Before PR review, redline/workflow checks and `python -m pytest tests/ -x -q` shall pass once with the exact revision recorded.

**Plan review:**
Clean-context reviews of `587200ae`, `f00888dc`, and `90b11f9d` returned CHANGES_REQUIRED and were incorporated. A fresh clean-context smart review of `427a813f` found no remaining concrete blocker and returned APPROVE. Architect acceptance is still pending; implementation remains blocked.

**Approvals:**
Approved by user 2026-09-12: "Second, the relay to operational tasks. You can advance with that and let's get them completed."

**Exceptions:**
—

**State:** Blocked
<!-- agent-workflow:end -->

## Exact design for acceptance

Public `activation` projection (same object on Relay session/recipient/status records; optional for compatibility):

| Field | Bounded values |
|---|---|
| `contract` | `relay-activation/v1` |
| `runtime` | `codex`, `claude-code`, `opencode`, `unknown` |
| `platform` | `windows`, `linux`, `macos`, `other`, `unknown` |
| `integration` | `codex_queue`, `claude_peer`, `hook_only`, `unknown` |
| `topology` | `existing_session`, `managed_session`, `none`, `unknown` |
| `behavior` | `busy_queue`, `idle_wake`, `passive`, `unknown` |
| `qualification` | `qualified`, `unqualified`, `unknown` |
| `qualification_source` | `installed_witness`, `documented_fallback`, `none` |
| `availability` | `ready`, `busy`, `attempt_inflight`, `unreachable`, `closed`, `unknown` |
| `availability_source` | `runtime_registration`, `durable_reservation`, `endpoint_health`, `lifecycle`, `none` |
| `fallback` | `next_natural_turn`, `human_turn`, `none`, `unknown` |
| `evidence_capabilities` | bounded subset of `submission_attempted`, `transport_accepted`, `turn_started`, `payload_admitted`; these are supported signals, not claims that they happened |

Current mapping:

| Runtime/platform/state | topology / behavior | qualification | availability | fallback | evidence capability |
|---|---|---|---|---|---|
| Codex Windows/Linux, active endpoint | `existing_session` / `busy_queue` | `qualified` / `installed_witness` | `unknown` because loaded state is not observable, or `attempt_inflight` from a durable current reservation | `next_natural_turn` | all four kinds, kept distinct |
| Claude Windows/Linux, registered idle | `existing_session` / `idle_wake` | `qualified` / `installed_witness` | `ready` / `runtime_registration` | `next_natural_turn` | all four kinds, kept distinct |
| Claude Windows/Linux, registered busy/inflight/unreachable | `existing_session` / `idle_wake` | `qualified` / `installed_witness` | matching `busy`, `attempt_inflight`, or `unreachable`; source registration/durable reservation | `next_natural_turn` | all four kinds, kept distinct |
| Claude/Codex macOS | `existing_session` / `passive` | `unqualified` / `documented_fallback` | endpoint lifecycle or `unknown` | `next_natural_turn` | `payload_admitted` only through a natural hook turn |
| OpenCode all current platforms | `existing_session` / `passive` | `unqualified` / `documented_fallback` | endpoint lifecycle or `unknown` | `next_natural_turn` | `payload_admitted` only through a natural hook turn |
| closed, malformed, stale, conflicting, or unknown runtime | proven topology else `unknown`; `passive` or `unknown` | `unknown` / `none` | `closed` only from lifecycle, otherwise `unknown` | `human_turn` or `unknown` | no optimistic evidence |

Attempt results are an internal bounded value with `outcome`, redacted `reason`, bounded observed `evidence`, `native_retry_safe`, and optional `destination_health_update`. They are not last-attempt history. `accepted` and `uncertain` never imply turn start/admission/delivery. `deferred` means no native submission occurred. `failed` is definitive for that attempt; only Claude's proven missing native endpoint may set destination health unreachable. Codex local home, executable, timeout, nonzero exit, and exception reasons never do.

Exact file plan:

- New `core/relay_activation.py`: enums/value validation and pure snapshot projection only.
- `core/claude_wake.py`, `app/claude_wake_transport.py`, `app/claude_wake.py`: canonical transport phase result; backward-compatible stable-endpoint/expected-claim-attempt fence; one locked fresh-candidate reserve operation; preservation across every caller/scope move; no timed/status/close rearm; intent merge; capacity/legacy protection.
- New `core/codex_wake.py` plus `app/codex_wake.py`: bounded atomic stable-endpoint current-reservation store (no history), fresh candidate baseline under callback-shared lock, generation-token launch check, canonical outcomes, claim-generation CAS release, and correct health classification.
- `storage/sqlite_relay.py`, `core/relay.py`: add existing `attempts` to internal `pending_candidate`/`wake_candidates` projections only; no schema/public response change.
- `api/routes.py`, `app/dependencies.py`: keep every existing send/reply/ACK/recovery callback, but route all scheduling through the same durable reserve-if-absent gate; internal callbacks receive successful turn/ACK/MCP-ACK/atomic-reply results and release only matching claim generations or definitive delivery before safe backlog rearm. Close never clears a reservation.
- `api/schemas.py`, `core/relay.py`, `app/mcp/server.py`, `app/dashboard.py`, `app/dashboard.html`: one optional compact projection, preserving current fields and budgets.
- Existing focused test files plus docs/design/roadmap files named in Scope; no new framework, dependency, storage table, public route field, or trace ledger.

Context budget rule: HTTP and dashboard may show the full bounded object. MCP derives from that same object but emits one compact row per recipient: selector, ehavior/availability, qualification, and fallback are mandatory; topology, platform/integration, provenance, then evidence capabilities are elided in that order only when the existing 2,000-character budget requires it. Elision is field-aware and UTF-8-safe; it never emits partial JSON/tokens or hides fallback/unknown state.
## Implementation

- Created isolated worktree `C:\Dev\rore\Pallium\.worktrees\relay-activation-contract` on branch `feat/relay-activation-contract` from `27313e4e53f1baa502fbb3ef6e9331bdf7316ec6`.
- Evaluated applicability: production HTTP/MCP/dashboard and adapter changes require the normal workflow; no documentation-only exemption applies.
- Completed bounded read-only inventory and pre-edit redline classification. No production code has been edited.
- The first follow-up `apply_patch` hit the machine-local Windows process failure; the Work Record-only correction used one deterministic exact-string replacement as the repository-approved fallback.
- Sent the first concrete design and adapter mapping to `astra-reviewer`; three clean-context reviews found and drove corrections for correlation, replay coverage, fresh baselines, and lifecycle/scope races. A fresh smart gate review approved `427a813f`; implementation remains blocked only on architect acceptance.
- Recorded the user's scoped authorization relayed by `astra-reviewer`; no additional permission question is required while implementation stays faithful to the approved roadmap contract.

## Evidence

- Roadmap requirement: `roadmap/features/add-relay-activation-capability-contract.md`.
- Pre-edit redline review: clean-context `/root/activation_redline` returned API_CHANGE, High/Moderate, no boundary violation in the recommended dependency direction, with `api-review` required.
- Read-only inventories: `/root/activation_inventory` and `/root/activation_surfaces` identified existing authority, mappings, public projection seams, and focused tests.
- Relay work association: `work:v1:7b792ebce40247954da55a8ce3d3fab316f28c56713e12feee195560ad8025fc`; participant lookup returned `pall-arc` and `astra-reviewer` only.

## Plan review

APPROVE on `427a813f` from fresh clean-context smart reviewer; no production files changed or tests run.

## Result review

Pending.
