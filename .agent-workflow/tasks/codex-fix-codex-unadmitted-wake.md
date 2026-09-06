<!-- agent-workflow:start -->
**Outcome:**
Codex Relay wake reports destination health honestly after a completed launch that never reaches the installed hook, keeps the delivery durable, and recovers on the next proven exact-session admission without issuing unsafe duplicate queue writes.

**Target:**
Native exact-session Codex Relay wake coordination and failure feedback.

**Scope:**
`app/codex_wake.py`; `app/dependencies.py`; focused Codex wake caller-surface tests; RW-015 state in `roadmap/features/add-wake-first-relay-delivery.md`; this Work Record.

**Constraints:**
Keep the native `codex exec resume` plus `codex queue --thread` path; never substitute App Server or a replacement session. Queue acceptance is not admission, and native queue idempotency is proven false, so no timer or service-restart path may blindly enqueue a second trigger. Delivery remains pending until the existing UserPromptSubmit hook claims and ACKs it. Preserve exact scope, Unicode, non-steering busy behavior, portability, and fast deterministic tests.

**Completion criteria:**
(1) A blocking `exec resume` exit is successful only if the exact session and exact scope's existing Relay-turn callback cleared the matching scheduled generation before the child returned. (2) A completed/no-hook launch, terminal exec failure, or definite queue rejection releases in-memory ownership, marks only the still-current destination unreachable through the existing strict timestamp CAS, and never consumes the delivery. (3) A successful asynchronous queue write or any exec/queue timeout remains coalesced until actual hook admission, with no timeout-based duplicate. (4) A later exact-session, exact-scope turn claims the preserved delivery once and clears scheduling state; wrong-scope turns cannot clear it. (5) Caller-surface E2E covers callback-before-exit ordering, interrupted/no-hook, terminal failure, active-writer queue success/rejection/timeout, stale feedback CAS, duplicate triggers, exact scope, Unicode, and eventual single ACK. (6) Roadmap/docs state the upstream ambiguity honestly; close RW-015 only if an installed no-manual-turn witness passes.

**Risk:**
Elevated

**Complexity:**
Moderate

**Reason:**
This changes wake success classification and durable destination-health feedback on an asynchronous cross-process boundary. The delivery lifecycle and storage schema remain unchanged, but false success, stale callback, duplicate queue, and exact-session admission cases must stay coherent.

**Discovery:**
The initial dogfood observation was premature: status evidence later showed both supposedly stuck sends were hook-delivered, including the vNext target after 57 seconds, and its exact task history shows the attributed Relay payload was processed and replied to. A fresh `codex:@relaydev` probe was hook-ACKed automatically after 16 seconds. The real latent bugs remain in `_launch`: blocking `exec resume` completion and asynchronous `queue --thread` acceptance share one boolean, so a completed child with no matching hook admission can hold the per-session generation forever; admission is also cleared by session only rather than exact scope. Existing Phase-0 evidence proves queue return is only transport acceptance and native duplicate suppression fails.

**Material assumptions:**
For blocking `codex exec resume`, a real UserPromptSubmit hook call completes its synchronous `/relay/turn` before the child exits, so the existing generation callback is authoritative after process completion. Disproof: a caller-surface or installed witness shows a valid hook admission can arrive only after the exec child exits; stop and re-plan rather than add a timeout. For accepted `codex queue` or a timed-out exec/queue subprocess, absence of admission is ambiguous and must remain coalesced.

**Plan:**
Return a minimal launch outcome that distinguishes blocking exec completion, accepted queue or timed-out subprocess ambiguity, and terminal failure. In the existing worker, compare that outcome with the exact scheduled generation and scope: keep accepted queue or timed-out subprocess ownership; if matching hook admission already cleared ownership before blocking exec returns, do nothing; otherwise release ownership and report unreachable through the same strict-CAS callback pattern used by Claude. Add focused caller-surface lifecycle coverage through HTTP and the real Codex hook, then align RW-015 without claiming that Pallium can safely retry an ambiguously accepted native queue.

Key conventions: reuse existing generation ownership, hook admission callback, and `RelayService.mark_unreachable`; add no persistence schema, event parser, watchdog, dependency, or wall-clock wait.

Target files or classes: `app/codex_wake.py`; `app/dependencies.py`; `tests/test_codex_wake.py`; `roadmap/features/add-wake-first-relay-delivery.md`.

**Verification plan:**
Outcome classification and stale-generation protection → focused coordinator tests. Persistence, health, exact scope, Unicode, and eventual ACK → real `/relay/messages` → wake callback → installed-hook function → `/relay/turn`/ACK caller-surface E2E with injected subprocess outcomes and deterministic clocks. Regression floor → focused Relay/Codex integration suites, workflow/redline gates, clean-context review, and one installed Relay dogfood witness.

**Plan review:**
2026-09-06 clean-context Luna plan review approved the ownership/CAS direction after requiring exact-scope correlation, callback-before-exec-exit proof, and indefinite coalescing for transport ambiguity. Final clean-context review required exec timeout to be treated as ambiguous and actual caller-surface proof for both callback-before-return and queue timeout; after those corrections it returned APPROVE with no blocking correctness, race, scope/CAS, coverage, documentation, or complexity findings.

**Approvals:**
Standing user approval to carry managed PRs through merge.

**Exceptions:**
—

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

- 2026-09-06: Traced native CLI launch, HTTP callbacks, hook admission, storage health, historical Phase-0 evidence, and RW-015 dogfood. Rejected App Server substitution and timeout retry because they target the wrong runtime or duplicate native queued turns.
- 2026-09-06: Corrected the incident after durable status and exact-task history proved both earlier sends eventually admitted. Implemented only the remaining root hardening: blocking-exec/no-hook detection, exact-scope admission, strict-CAS health feedback, and indefinite coalescing for accepted queue writes or timed-out exec/queue subprocesses.

## Evidence

- `.venv\Scripts\python.exe -m pytest tests\test_codex_wake.py tests\test_agent_relay_e2e.py tests\test_relay_wake_contract.py tests\test_codex_integration.py -q` → 107 passed in 13.14s; four pre-existing Pydantic forward-reference warnings.
- Caller-surface E2E drives HTTP persistence and dispatch through actual `_launch`; proves exact hook admission before exec return, completed/no-hook pending recovery, queue-timeout coalescing without duplicate launch, wrong-scope refusal, Unicode, and single ACK without wall-clock sleeps.
- `scripts/agent-workflow-check.py --repo-root . --slug codex-fix-codex-unadmitted-wake` → clean. Redline → GRAY/watch-only for `app/codex_wake.py` and `app/dependencies.py`; no boundary, API, schema, security, runtime-config, or checkpoint findings. `git diff --check` → clean.

## Result review

- 2026-09-06 final clean-context Luna review: APPROVE; no blocking findings and no unnecessary abstraction or unsafe live-service test behavior.
