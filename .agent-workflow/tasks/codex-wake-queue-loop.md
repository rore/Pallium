<!-- agent-workflow:start -->
**Outcome:** A confirmed busy Codex Relay queue submission remains single-flight until hook admission, so one pending batch cannot create repeated empty task cycles.

**Target:** Pallium Relay Codex wake adapter.

**Scope:** `app/codex_wake.py`, caller-surface coverage in `tests/test_codex_wake.py`, and the existing Relay operations/roadmap contract.

**Constraints:** Preserve durable pending delivery, exact session+container+actor ownership, hook-time claim/ACK, natural-turn fallback, startup recovery, cross-platform behavior, and fast deterministic tests; add no dependency, schema, or wall-clock wait. Do not claim exact cross-service-restart wake deduplication without durable reservation.

**Completion criteria:** Repeated recovery sweeps after a confirmed or ambiguous busy Codex wake enqueue no additional internal prompt within the live scheduler generation; the real Codex hook admits and delivers the batch once, admission permits a later delivery to wake normally, and a service restart still reconstructs pending wake work with the documented possibility of one extra native prompt across that restart boundary.

**Risk:** Elevated

**Complexity:** Moderate

**Reason:** Redline classifies `app/codex_wake.py` as gray runtime/process code. The code change is small, but wake-loss versus duplicate-wake behavior requires caller-surface lifecycle verification.

**Discovery:** Live dogfood produced two real pending replies, at least fourteen confirmed queue submissions while the target stayed busy, then thirty empty task starts after the first hook turn delivered both. Current `_wake_after_debounce` assigns the same 30-second retry to `queued` and `ambiguous`, although native queue deduplication is false; existing tests encode that retry. The actual hook blocks overtaken empty prompts before memory/model work, but cannot remove already queued task cycles. `docs/context/operations.md` documents the faulty combined retry behavior, while the Phase 0 design already distinguishes accepted from ambiguous transport.

**Material assumptions:** A zero exit from `codex queue --thread` means that one prompt was accepted and should not be submitted again before admission. A timeout is ambiguous and cannot be retried safely because native queue writes are not idempotent; the delivery remains pending for natural-turn or startup recovery. Exact cross-service-restart deduplication remains unqualified because wake ownership is process-local; if that becomes a completion requirement, return to planning for durable correlated wake state rather than adding blind retries.

**Plan:** First add a deterministic failing caller-surface reproduction to the existing HTTP send → real scheduler → busy native queue → repeated persisted recovery → actual UserPromptSubmit hook journey. Assert one native queue submission across many recovery windows, one delivered batch, no remaining pending delivery, and later rearm. Then delete blind retry scheduling for both confirmed and ambiguous native wake outcomes in `app/codex_wake.py`, update unit expectations, and align operations plus the dogfood defect ledger. Preserve the existing full-app restart regression as the proof that pending work is reconstructed after process loss; explicitly leave exact cross-restart deduplication to the already documented durable-reservation follow-up. Target files: `tests/test_codex_wake.py`, `app/codex_wake.py`, `docs/context/operations.md`, and `roadmap/features/add-wake-first-relay-delivery.md`. Stop if the caller-surface reproduction does not fail on current code or if restart/expired-claim recovery regresses.

**Verification plan:** Repeated recovery while busy shall enqueue one internal prompt per live scheduler generation → new deterministic HTTP/scheduler/recovery/real-hook regression, first run against current code and expected to fail. Hook admission shall deliver once and rearm later work → same caller-surface regression plus existing overtaken-wake test. Process restart shall reconstruct pending/expired work → existing real-app restart and crash-after-claim regressions. Final scope shall satisfy workflow and boundary policy → focused Relay suites, `agent-workflow-check`, redline report, and diff review.

**Plan review:** Clean-context Luna review recorded below; initial blockers were resolved and the revised plan was approved for implementation.

**Approvals:** Not required at this risk level.

**Exceptions:** —

**State:** Ready to implement
<!-- agent-workflow:end -->

## Implementation

- Context, live incident evidence, caller graph, existing tests, and documentation contract inspected. No production code changed. Elevated-risk clean-context plan review and revised-plan re-review completed; implementation is ready to begin.
- Failing caller-surface regression added: six deterministic recovery windows produced six native queue submissions on current code (expected one).
- Implemented the root fix by deleting per-session blind retry timing; confirmed and ambiguous non-idempotent native writes now retain one scheduler generation until hook admission. Updated unit/concurrency expectations, operations, and RW-022.

## Evidence

- Live Relay database: the two deliveries were claimed and delivered once at 2026-09-07 17:45:49Z and no exact-session delivery remains pending.
- Service log: confirmed queue outcomes repeatedly scheduled another retry during the busy interval.
- Canonical Codex transcript: thirty task starts and zero visible user messages during the post-delivery drain window.

## Plan review

Clean-context review found that retrying `ambiguous` contradicts the canonical non-idempotent transport contract and that exact restart deduplication requires durable wake-attempt state. The revised plan removes both confirmed and ambiguous blind retries, preserves natural-turn/startup recovery, and limits its exact-once claim to one live scheduler generation. Cross-service-restart deduplication remains the existing durable-reservation follow-up. Re-review confirmed that both prior blockers are resolved and implementation may proceed; it specifically requires repeated real recovery sweeps plus the actual UserPromptSubmit hook while treating restart tests as reconstruction-only evidence.

## Result review

Pending.
