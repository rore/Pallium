<!-- agent-workflow:start -->
**Outcome:** Uncertain Codex native queue failures retain useful, bounded, non-secret diagnostics, and Relay trace explains the supported manual recovery turn without implying that an app-message continuation invokes the hook.

**Target:** Pallium Relay Codex wake diagnostics.

**Scope:** Existing Codex native launch diagnostic and shared trace guidance slice, plus bounded exact-wake hook client-request and /relay/turn service/route-ready timing in the existing readiness marker/server log. Adding optional timing fields to the marker also adds those fields to its dashboard readiness projection. Files: app/codex_wake.py, storage/sqlite_relay.py, app/codex_readiness.py, integrations/codex/hooks/user_prompt_submit.py, api/routes.py, focused tests, and the canonical roadmap item.

**Constraints:** Keep the existing per-endpoint duplicate fence, native retry classification, claim/ACK, scope, workspace, model, and effort behavior unchanged. Never log or return raw stderr, prompts, payloads, local paths, secrets, or untrusted free text. Do not test against working user sessions or add infrastructure/API/schema changes.

**Completion criteria:** A nonzero Codex queue exit records numeric exit and fixed safe stderr category without leaking text. Exact-single-recipient uncertain Codex trace gives direct-prompt guidance; other runtimes and mixed evidence remain generic. A delayed-after-claim hook request records bounded response/unavailable outcome and elapsed time in the existing marker; the route logs validated exact delivery ID, service duration, and route-ready duration without payload data. Focused launch, HTTP/MCP, hook, and route tests prove those contracts. No timing observation changes delivery, retry, scope, model, or effort behavior.

**Requirement baseline:**
{"source":"work-record-initial","outcome":"Uncertain Codex native queue failures retain useful, bounded, non-secret diagnostics, and Relay trace explains the supported manual recovery turn without implying that an app-message continuation invokes the hook.","scope":"`app/codex_wake.py` launch-completion logging, the existing Relay trace explanation in `storage/sqlite_relay.py`, focused launch and trace caller-surface tests, and the canonical wake-first roadmap item.","constraints":"Keep the existing per-endpoint duplicate fence, native retry classification, claim/ACK, scope, workspace, model, and effort behavior unchanged. Never log or return raw stderr, prompts, payloads, local paths, secrets, or untrusted free text. Do not test against working user sessions or add infrastructure/API/schema changes.","completion_criteria":"A nonzero Codex queue exit records its numeric exit code and a fixed safe stderr category even when stderr is hostile, empty, or malformed; no stderr content leaks. A pending uncertain Codex delivery tells the caller that a genuine user prompt in the existing recipient task is required on the observed app-message surface, without treating the message as lost or retry-safe; other runtimes' guidance remains accurate. Focused launch and HTTP/MCP trace tests prove those contracts."}

**Risk:** High

**Complexity:** Moderate

**Reason:** Redline marks api/routes.py API_CHANGE / red contract surface with api-review checkpoint; hook/readiness files are gray/watch-only. High for the API checkpoint even though only logs change; moderate because exact-hook marker compatibility and server/client timing need cross-surface proof.

**Discovery:** Main already logs a correlated numeric exit code and deliberately omits raw stderr (`app/codex_wake.py`, `tests/test_codex_wake.py`); the prior native-queue-proof branch implemented that slice. `_finish_launch` captures but discards stderr, while the scheduler retains the uncertain per-endpoint fence. A later delivery associates with that fence without submitting another native turn. The shared trace explanation lives in `storage/sqlite_relay.py` and reaches HTTP/dashboard/MCP; its current "ordinary turn" wording was insufficient for the observed Codex app-message continuation, which entered as a tool result rather than UserPromptSubmit. Existing focused launch, service-trace, and MCP caller-surface tests cover these seams. No schema or API contract change is needed.

**Material assumptions:** CLI stderr is untrusted and version-dependent; only fixed allowlisted categories are diagnostic, and unknown output stays `other` (never retry-safe). If exact source/output review disproves a category, remove it rather than emit free text. The app-message distinction is an observed Codex Desktop path, not a universal host guarantee; phrase guidance accordingly, and keep non-Codex wording unchanged.

**Plan:** 1. Preserve the existing native launch result, numeric correlated log, and retry fence; decode malformed UTF-8 as replacement and log only fixed stderr categories. 2. Add direct-prompt guidance only for exact single Codex delivery/completion match; preserve generic mixed/shared guidance and state precedence. 3. On an exact internal Codex wake, wrap the injected relay_request seam and record client request duration through response/unavailable in the existing readiness marker. Use one fixed outcome enum and optional integer elapsed_ms in 0..30000; omit an invalid/over-cap timing field while preserving the fixed-outcome event and all valid legacy events/readiness; preserve old four-key events, ignore invalid optional timing without dropping a valid legacy event or changing readiness/trust. The optional fields are additive in existing dashboard readiness output. 4. For a validated wake_delivery_id, log service-call duration (existing _relay_call boundary) and route-ready duration after callback/activation projection in api/routes.py. Explicitly exclude response-model serialization/network completion. No response/status/claim change. 5. Add a delayed-after-claim actual-hook diagnostic regression before instrumentation, demonstrate red/green, and HTTP route timing projection test; reuse existing crash-after-claim recovery E2E. 6. Update existing roadmap, run focused/affected/full pre-review checks, workflow/redline and independent review, then installed witness. Stop if raw data, retry/fence, scope, model, effort, or breaking API change becomes necessary. Files: app/codex_wake.py, storage/sqlite_relay.py, app/codex_readiness.py, integrations/codex/hooks/user_prompt_submit.py, api/routes.py, tests/test_codex_wake.py, tests/test_relay_delivery_trace.py, tests/test_relay_mcp_tools.py, tests/test_agent_relay_hooks.py, tests/test_agent_relay_e2e.py, roadmap/features/add-wake-first-relay-delivery.md, this record.

**Verification plan:** Existing native/trace focused nodes prove fixed categories, malformed decode, no stderr leakage, exact Codex versus generic guidance and pending/fence state through HTTP/MCP. New delayed-after-claim hook test proves first committed claim can yield unavailable client-request evidence without emission/ACK; fixed outcome and valid 0/30000ms boundary timings appear in marker/dashboard readiness, while invalid/over-cap timings omit only the timing field, while legacy and invalid optional timing preserve valid events/readiness. HTTP route test proves distinct service-call and route-ready timing with canonical ID correlation, and response/status unchanged. Reuse existing crash-after-claim E2E, then affected subsystem files, git diff --check, workflow/redline checks, one full suite before PR, reviewed installed loaded-idle/busy-to-idle witness.

**Plan review:** Initial diagnostic/trace slice approved. Timing reviews WITHHOLD for additive readiness shape, marker validation/timing labels, then unspecified elapsed cap; revised 0..30000ms omit-invalid plan is independently approved, with explicit High-risk human approval pending; see ## Plan review below.

**Approvals:** Approved by user 2026-09-24T12:13:35Z: "Approve this timing change"

**Exceptions:** —

**State:** Ready to implement
<!-- agent-workflow:end -->

## Implementation

- Established the task context and baseline before code edits. Worktree: `feat/codex-native-failure-diagnostics` from `a29bb260`; no production edits yet.
- Discovery and risk checkpoint: reused existing numeric exit logging and caller-surface tests. Redline pre-edit verdict is gray/watch-only (app/storage), blue tests/roadmap/record, no checkpoint or boundary risk. Implementation remains blocked on clean-context plan review.

## Plan review

Initial review: WITHHOLD. Replacement UTF-8 decoding is required so malformed native stderr cannot turn a numeric nonzero exit into an unclassified post-start error; test the numeric exit/category and no leak. Add an actual HTTP trace caller test alongside service/MCP. The existing three-field launch result remains unchanged; the fixed category is a separate delivery-correlated diagnostic log. Both findings were incorporated. Second clean-context review: WITHHOLD because message-level traces can span multiple recipients, and a completion must not lend Codex-specific guidance to another recipient. The revised plan requires exactly one Codex snapshot whose delivery ID matches the latest completion; mixed/shared/unassociated evidence stays generic, with fan-out regression. Final clean-context review: APPROVE after verifying the existing HTTP route test in `tests/test_relay_delivery_trace.py` exercises `/dashboard/api/relay/messages/{id}/trace`. No remaining blocker for the initial slice. The timing extension above awaits clean-context review before those files are edited.

## Incident timing extension (2026-09-24)

- Case A, native exit 1: retained uncertain fence, no claim, stderr discarded; historical native reason unknown. Bounded experiment is fixed-category stderr capture on the actual launch-completion path. Result and decision remain pending installed observation; never release or retry from category alone.
- Case B, delayed twice-claimed receipt: native accepted 11:18:28Z while task busy; first hook at 11:19:14.752Z failed relay_unavailable at 11:19:15.835Z without emission/ACK; second hook at 11:20:49Z emitted/ACKed by 11:20:50Z. Durable attempts=2 supports an earlier committed claim, but the first request's exact delay/error is not retained. Service/API process did not restart. Existing crash-after-claim E2E proves lease recovery; next bounded experiment is delayed-after-claim actual-hook diagnostic evidence plus stage timing. A forced delay tests the mechanism, not historical causation. No timeout increase or duplicate-fence change without measured cause.
- The hook currently has a 0.75s request cap; existing stderr includes failure type/elapsed but was not retained. Server _relay_call slow timing ends before callback, activation projection, and serialization. Proposed route log stops at route-ready return, not final network response; hook elapsed covers the full client request. Compare both on the next occurrence before a behavioral fix.

## Checkpoint: api-review

Change shape: additive optional timing fields in dashboard readiness evidence; route logs are internal-only and do not change /relay/turn request/response schema or status. What is changing: exact-delivery service-call and route-ready timing logs around the existing /relay/turn route.
Why: distinguish service work from post-service response construction after a committed claim and lost hook response.
Affected contract / model / boundary: dashboard readiness event projection gains optional timing fields; /relay/turn wire contract remains unchanged. Hook elapsed covers client request through response/unavailable. Server service-call timing excludes callback/projection; route-ready includes both but excludes response-model serialization and network completion.
Compatibility / migration risk: low/additive optional fields; old events and consumers remain valid, no caller migration.
Verification plan: actual route HTTP test with callback/projection delay, hook delayed-response test, existing claim/recovery E2E, and unchanged response projection.


Timing plan review 1: WITHHOLD. Corrected additive dashboard evidence shape, independent bounded optional elapsed validation preserving legacy events/trust, distinct client/service/route-ready labels, and API checkpoint note. High-risk human approval remains pending after re-review.

Timing plan review 2: WITHHOLD for unspecified elapsed cap/over-limit behavior. Set 0..30000ms inclusive; omit invalid/over-cap timing only, retaining fixed-outcome event, valid legacy events, and readiness state. Independent re-review: APPROVE PLAN; separate human approval still required before timing code edits.

Human approval recorded from the exact in-task reply to the timing-change question; the separate api-review PR checkpoint remains required.
