<!-- agent-workflow:start -->
**Outcome:** Uncertain Codex native queue failures retain useful, bounded, non-secret diagnostics, and Relay trace explains the supported manual recovery turn without implying that an app-message continuation invokes the hook.

**Target:** Pallium Relay Codex wake diagnostics.

**Scope:** `app/codex_wake.py` launch-completion logging, the existing Relay trace explanation in `storage/sqlite_relay.py`, focused launch and trace caller-surface tests, and the canonical wake-first roadmap item.

**Constraints:** Keep the existing per-endpoint duplicate fence, native retry classification, claim/ACK, scope, workspace, model, and effort behavior unchanged. Never log or return raw stderr, prompts, payloads, local paths, secrets, or untrusted free text. Do not test against working user sessions or add infrastructure/API/schema changes.

**Completion criteria:** A nonzero Codex queue exit records its numeric exit code and a fixed safe stderr category even when stderr is hostile, empty, or malformed; no stderr content leaks. A pending uncertain Codex delivery tells the caller that a genuine user prompt in the existing recipient task is required on the observed app-message surface, without treating the message as lost or retry-safe; other runtimes' guidance remains accurate. Focused launch and HTTP/MCP trace tests prove those contracts.

**Requirement baseline:**
{"source":"work-record-initial","outcome":"Uncertain Codex native queue failures retain useful, bounded, non-secret diagnostics, and Relay trace explains the supported manual recovery turn without implying that an app-message continuation invokes the hook.","scope":"`app/codex_wake.py` launch-completion logging, the existing Relay trace explanation in `storage/sqlite_relay.py`, focused launch and trace caller-surface tests, and the canonical wake-first roadmap item.","constraints":"Keep the existing per-endpoint duplicate fence, native retry classification, claim/ACK, scope, workspace, model, and effort behavior unchanged. Never log or return raw stderr, prompts, payloads, local paths, secrets, or untrusted free text. Do not test against working user sessions or add infrastructure/API/schema changes.","completion_criteria":"A nonzero Codex queue exit records its numeric exit code and a fixed safe stderr category even when stderr is hostile, empty, or malformed; no stderr content leaks. A pending uncertain Codex delivery tells the caller that a genuine user prompt in the existing recipient task is required on the observed app-message surface, without treating the message as lost or retry-safe; other runtimes' guidance remains accurate. Focused launch and HTTP/MCP trace tests prove those contracts."}

**Risk:** Elevated

**Complexity:** Moderate

**Reason:** Redline classifies the runtime and trace files as gray/watch-only, with tests and roadmap blue; no checkpoint or boundary rule applies. Moderate because subprocess diagnostics and shared caller guidance must preserve privacy and cross-runtime behavior.

**Discovery:** Main already logs a correlated numeric exit code and deliberately omits raw stderr (`app/codex_wake.py`, `tests/test_codex_wake.py`); the prior native-queue-proof branch implemented that slice. `_finish_launch` captures but discards stderr, while the scheduler retains the uncertain per-endpoint fence. A later delivery associates with that fence without submitting another native turn. The shared trace explanation lives in `storage/sqlite_relay.py` and reaches HTTP/dashboard/MCP; its current "ordinary turn" wording was insufficient for the observed Codex app-message continuation, which entered as a tool result rather than UserPromptSubmit. Existing focused launch, service-trace, and MCP caller-surface tests cover these seams. No schema or API contract change is needed.

**Material assumptions:** CLI stderr is untrusted and version-dependent; only fixed allowlisted categories are diagnostic, and unknown output stays `other` (never retry-safe). If exact source/output review disproves a category, remove it rather than emit free text. The app-message distinction is an observed Codex Desktop path, not a universal host guarantee; phrase guidance accordingly, and keep non-Codex wording unchanged.

**Plan:** 1. Preserve the existing three-field launch result and numeric correlated log. At the actual `_wake_after_debounce` launch-completion call, pass the canonical delivery ID into `_finish_launch`; on nonzero exit, classify only a bounded prefix of captured stderr into fixed categories (`empty`, CLI usage, thread unavailable, transport, other) and log that category with delivery ID and numeric code. Never log stderr text or let the category affect retry/fence decisions. 2. In the existing uncertain-pending trace explanation, add Codex-specific guidance to enter a normal user prompt directly in the existing recipient task; app-message delegation may not invoke UserPromptSubmit. Preserve generic guidance for other runtimes and all delivery-state precedence. 3. Extend the existing launch-completion test for hostile/empty/known stderr categories and the existing service/MCP trace tests for Codex versus Claude wording and unchanged pending state. 4. Update only the existing wake-first roadmap item; run focused, affected, full pre-review, workflow, redline, and independent result review. Stop on any need for raw stderr, retry/fence change, schema/API change, or working-session experiment. Target files: `app/codex_wake.py`, `storage/sqlite_relay.py`, `tests/test_codex_wake.py`, `tests/test_relay_delivery_trace.py`, `tests/test_relay_mcp_tools.py`, `roadmap/features/add-wake-first-relay-delivery.md`, this Work Record.

**Verification plan:** Nonzero exit emits only fixed category plus existing numeric code and correlation, including empty/hostile/long stderr, while uncertain fence remains -> focused `tests/test_codex_wake.py` launch-completion and coalescing nodes. Pending uncertain Codex trace gives genuine-prompt guidance, other runtimes retain ordinary-turn guidance, and delivered/expired/accepted precedence remains -> focused `tests/test_relay_delivery_trace.py` and actual MCP trace caller test in `tests/test_relay_mcp_tools.py`. No unrelated behavior or scope drift -> affected subsystem tests, `git diff --check`, workflow/redline checks, and one repository full suite before PR.

**Plan review:** Pending clean-context review; see `## Plan review` below.

**Approvals:** Not required at this risk level.

**Exceptions:** —

**State:** Blocked
<!-- agent-workflow:end -->

## Implementation

- Established the task context and baseline before code edits. Worktree: `feat/codex-native-failure-diagnostics` from `a29bb260`; no production edits yet.
- Discovery and risk checkpoint: reused existing numeric exit logging and caller-surface tests. Redline pre-edit verdict is gray/watch-only (app/storage), blue tests/roadmap/record, no checkpoint or boundary risk. Implementation remains blocked on clean-context plan review.

## Plan review

Pending clean-context review.
