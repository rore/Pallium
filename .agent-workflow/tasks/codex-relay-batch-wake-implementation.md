<!-- agent-workflow:start -->
**Outcome:** Codex-to-Codex Relay exchanges can submit and deliver bounded whole batches through the regular-turn path, with notification-only wake only after G1-G3 evidence proves it safe.
**Target:** Pallium Relay milestone 1.
**Scope:** Slice A runtime qualification; then, only after its gates pass, slices B-D in `core/relay.py`, `storage/sqlite_relay.py`, `storage/sqlite_schema.py`, `api/schemas.py`, `api/routes.py`, `app/mcp/server.py`, client/context, Codex hook/common/installer, service lifecycle/dashboard summary, Relay docs/skill guidance, and parameterized E2E coverage.
**Constraints:** Preserve unrelated `uv.lock`. No live trigger, production edit, service/config change, managed runtime, Claude/OpenCode wake adapter, second injection path, or redesign before this checkpoint is reviewed. Runtime adapters stay out of core; no raw claim token/HTTP guidance.
**Completion criteria:** Each applicable E01-E18 case drives its HTTP, MCP, or hook surface and observes status plus integration output; G1-G3 qualify the installed Codex runtime before wake is enabled; the no-ping exchange and wake-disabled regular-turn control have recorded evidence.
**Risk:** High
**Complexity:** Large
**Reason:** Intended changes include red API contracts (`api/schemas.py`, `api/routes.py`) and red persisted schema (`storage/sqlite_schema.py`), with durable ownership, expiry, and runtime-admission behavior. The work spans independently verifiable evidence, data, API, runtime, and release slices.
**Discovery:** The approved design is `docs/designs/relay-batch-codex-wake.md`; it supersedes earlier timeout/dual-path rules and leaves G1-G3 deliberately unproven. Current R1 sends one bounded payload, emits/ACKs individual deliveries, and `tests/test_relay_mcp_lifecycle.py` plus `tests/test_relay_mcp_tools.py` cover receipt-bound claim/ACK/reply and lease races. Existing wake fixtures are deterministic protocol fixtures only, not Codex queued-turn or full-admission evidence. The existing design Work Record is closed on branch base `4560f6b`; its `uv.lock` modification is unrelated.
**Material assumptions:** (1) A queued turn on the installed Codex runtime reaches the same pre-model claim/render hook as a normal/busy-boundary turn; G1 disproves this and keeps wake passive. (2) The runtime can witness full-envelope context admission and fence stale publishers; G2 disproves this and retains visible uncertainty without automatic replay. (3) The bounded batch envelope fits the real model context while draining a 64-delivery backlog; G3 disproves this and lowers/rejects limits before acceptance. (4) Pre-edit redline classification has no boundary violation; any such result stops implementation rather than being worked around.
**Plan:** (1) Review this preflight and run the smallest coordinated G1/G2/G3 qualification with no production mutation. (2) If a gate fails, record the evidence and return the adapter/admission design to review; do not implement a workaround channel. (3) If all gates pass, obtain API, persistence, architecture/runtime, and security review checkpoints before guarded edits. (4) Implement B's batch/passive path and its parameterized E01-E08/E10-E16 E2E coverage before C's notification coordinator; keep both wake and ordinary turns on one claim/render/admit path. (5) Implement C only after B passes; run D's installed-runtime, no-ping qualification and release/rollback checks. Reclassify on scope change.
**Verification plan:** G1 queued-turn hook and busy-boundary execution → captured installed-Codex hook transcript and status. G2 whole-envelope admission plus stale-publication fencing → full-envelope/digest witness with controlled interruption. G3 bounded 64-delivery drain headroom → installed-runtime size/context measurement. E01-E16 → parameterized HTTP/MCP/hook E2E cases on a fresh SQLite database with controlled clock/transport. E17-E18 → one bounded installed two-Codex run plus a wake-disabled regular-turn control, recording runtime/version/OS, captured full envelope, status, and cleanup. No test treats queue success, sender markers, model acknowledgement, or missing history as context-admission proof.
**Plan review:** Clean-context review `/root/preflight_review` found a blocking G2/G3 pass-criterion gap: queue/hook/Relay evidence could self-certify admission, and empirical headroom alone is insufficient. The corrected protocol below requires independent runtime-owned commit evidence and a documented hard/derived context bound. Manager review remains pending. This checkpoint authorizes neither guarded edits nor live probes.
**Approvals:** Approved by user 2026-08-31: "yes"
**Exceptions:** —
**State:** Blocked
<!-- agent-workflow:end -->

## Implementation

- 2026-08-31: Created `codex/relay-batch-wake-implementation` from `4560f6b` in the existing checkout. No production, service, configuration, or test changes were made. Awaiting review of this preflight and the G1-G3 protocol.

## Evidence

### Required checkpoints

Pre-edit classification is HIGH: `storage/sqlite_schema.py` requires persistence review; `api/schemas.py` and `api/routes.py` require API review; guarded runtime/core/storage paths require architecture/runtime review. `core/visibility.py`, if changed for capability scoping, adds security review. Boundary rules prohibit `api` importing storage/runtime layers and storage importing `app`/`capabilities`; adapters compose outside core. No boundary exception is permitted.

### Smallest coordinated G1-G3 probe protocol

1. Use two existing installed Codex sessions and an isolated test container/database. Send one known batch through the normal MCP/Relay path, queue one bounded notification, and capture the recipient's queued pre-model hook at both idle and busy boundaries (G1). Do not use an app ping, manual receive, or payload-bearing queue item.
2. G2 passes only when the installed runtime exposes an independently readable, runtime-owned immutable context-commit artifact for the exact queued turn/recipient containing a fresh attempt nonce and the full-envelope digest. Interrupt before/after publication, reclaim, and attempt a stale publisher: it must produce no matching commit; any ambiguous outcome remains `uncertain`. Hook output, Relay DB writes, CLI queue success, model output, partial transcript, and absent history are non-evidence.
3. G3 passes only with a documented native hard input/context bound, or a conservative derivation, covering the maximal permitted normal-turn context plus eight max envelopes. Run exact-bound and over-bound envelopes across 64 pending deliveries and capture the wake-disabled ordinary-turn control. If only empirical headroom is available, disable wake and cap/passively block acceptance. Clean every test session, test database, queued notification, and temporary evidence fixture; retain only redacted evidence.

### E2E matrix

| ID | Observable result | Fault injection / boundary | Surface | Reset / evidence |
| --- | --- | --- | --- | --- |
| E01 | Valid whole batch only; rejected input creates no rows/wake | empty/one/max/over-max, whitespace, malformed, both/neither forms | HTTP + MCP | fresh DB; deterministic |
| E02 | Every accepted part/envelope is complete and bounded | exact/over bytes and code points, Unicode/RTL/emoji/surrogates, redaction growth | HTTP + hook | fresh DB; deterministic + G3 real runtime |
| E03 | Cross-part secrets redact; forged markers remain data | split secret, forged envelope | MCP + hook | redacted capture; deterministic |
| E04 | One committed snapshot/retry result; no expiry extension | crash/disk-full/contention, lost response, concurrent retry, alias transfer, cleanup | HTTP + SQLite | fresh DB/clock; deterministic |
| E05 | Scope/recipient/receipt misuse reveals no data or retargets | cross scope/actor/session, replay, close/reopen/project change | HTTP + MCP | isolated scopes; deterministic |
| E06 | Reply is atomic and bounded; failed reply never ACKs | expired parent, bad receipt, siblings, depth boundary | HTTP + MCP | fresh DB/clock; deterministic |
| E07 | Exactly one whole-batch owner, ordered on both paths | concurrent regular/wake/recovery claims in both orders | hook + MCP + HTTP | barriers/fresh DB; deterministic |
| E08 | Uncertain publication remains visible; stale publisher fenced | interrupt pre/post claim/publication/admission/ACK | hook + HTTP | controlled transport; G2 real admission witness |
| E09 | Wake uncertainty never duplicates delivery or strands regular turn | lost/duplicate/empty queue notice; regular turn wins | queue adapter + hook | clear queued notice; deterministic |
| E10 | FIFO makes bounded progress without starvation | over-turn backlog, oversized oldest, send at idle transition, equal/backward clocks | HTTP + hook | fresh DB/restart; deterministic + G3 backlog run |
| E11 | Restart/clock changes reconcile durably without blind retry | restart in every outstanding state; forward/backward clock | HTTP + hook | restart fixture/fresh DB; deterministic |
| E12 | Expiry and late evidence report truthfully | expiry before/during claim/publication/ACK/reply; sweep race | HTTP + MCP + hook | controlled clock; deterministic |
| E13 | Fan-out admission is atomic and recipients complete independently | mixed protocol/capacity/recipient failure | HTTP + MCP | isolated recipients; deterministic |
| E14 | Unsupported/disabled/stale/refused wake falls back only on a regular turn | absent/busy/permission/stale capability/unsupported hook | adapter + hook | clear capability state; G1 real queued hook |
| E15 | Limits/blocks/retry window are visible; no silent loss/loop | burst/rate/depth, compatibility shrink, invalid row, cleanup boundary | HTTP + status | controlled clock/DB; deterministic |
| E16 | Legacy traffic remains safe through upgrade/rollback | installer upgrade/downgrade, singleton/reply compatibility | installer + MCP + hook | disposable install/test DB; deterministic |
| E17 | Agent receives whole six-part batch and handles retry/status/reply | ordinary task with no coaching/external artifact | installed MCP + skill | isolated session/transcript; one bounded real-agent run |
| E18 | Automatic exchange has no surrogate prompt/ping; control uses ordinary turn | task→result→review→remediation; wake disabled control | two installed Codex sessions | clean sessions/queue; real-agent G1/G2 evidence |

## Recovery

Current branch: `codex/relay-batch-wake-implementation`; baseline: `4560f6befe87deba2e17be5e0bd9cd9b6d69cd2f`; unrelated `uv.lock` remains modified and unstaged. Next action after review: run only the three isolated G1-G3 probes, record their exact outcome here, and stop on the first unsupported hook/admission/headroom result.
