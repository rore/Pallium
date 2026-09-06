<!-- agent-workflow:start -->
**Outcome:** Codex Relay wake never produces a later generic turn after another admitted turn has already consumed the persisted delivery.

**Target:** Pallium Relay Codex wake delivery.

**Scope:** Codex wake ownership/admission and rearm logic, caller-surface regressions, and the canonical wake roadmap.

**Constraints:** Preserve persist-first delivery, exact session+container+actor isolation, ambiguous native-write safety, automatic backlog continuation, and public Relay contracts; no wall-clock sleeps or new dependencies.

**Completion criteria:** A delivery consumed by a natural or competing admitted turn cancels or suppresses its redundant native wake; close sends and cross-scope sends remain isolated; pending work is never lost; exact caller-surface tests and installed Windows dogfood produce no empty follow-up turn.

**Risk:** Elevated

**Complexity:** Moderate

**Reason:** Agent-redline classified the guarded `app/**` wake surfaces GRAY/watch with no boundary violation. Moderate complexity reflects a runtime race across persistence, native queue admission, hook claim/ACK, and in-memory ownership.

**Discovery:** Live dogfood produced an exact generic wake at 2026-09-06 03:15:49 UTC and a duplicate follow-up although the Relay database had no delivery to this session after 03:09:12. RW-002 currently claims this class is fixed. Pallium coalesces scheduling until admission, but an already accepted native `codex queue` prompt cannot be cancelled when another turn consumes the delivery first. Codex CLI 0.149.1 explicitly supports UserPromptSubmit exit code 2 with a stderr blocking reason; existing tests do not cover an accepted wake overtaken by another real hook claim.

**Material assumptions:** Codex consumes a queued UserPromptSubmit event whose successful hook output carries the supported JSON block decision, without retrying it or invoking the model. Disproof: an installed exact-session witness shows invalid hook JSON, requeue, model sampling, or another generic turn. Action if disproved: return to planning and retain durable delivery while qualifying another native admission mechanism.

**Plan:** Add one exact internal wake sentinel to the Codex UserPromptSubmit hook. Preserve the raw `/relay/turn` result; only when that request returns the complete canonical no-work state (`deliveries=[]`, `has_more=false`, integer `remaining_count=0`) for the exact sentinel, write exactly one stdout JSON object `{"decision":"block","reason":"Pallium Relay wake superseded: no pending delivery."}` with no `hookSpecificOutput`, exit 0, and stop before dedup or memory work. Preserve current behavior for Relay failure, partial/malformed response, invalid scope, non-wake prompts, redaction-expanded pending work, backlog continuation, and attributed delivery/ACK. Add direct hook boundary regressions plus a caller-surface lifecycle that drives public send → queued native wake → competing real hook claim/ACK → stale queued hook execution and proves it blocks without memory/output. Assert the adapter and hook sentinel stay identical; update RW-002 evidence. Target files: `integrations/codex/hooks/user_prompt_submit.py`, `tests/test_agent_relay_hooks.py`, `tests/test_codex_wake.py`, `roadmap/features/add-wake-first-relay-delivery.md`, and this record. Stop if the structured block behavior cannot be installed-proven or if Relay failure becomes indistinguishable from a confirmed empty turn.

**Verification plan:** Redundant native wake after another turn consumes the delivery shall not create an empty follow-up → deterministic caller-surface E2E with injected process/hook ordering; close and cross-scope sends shall remain isolated → focused concurrency/scope regressions; ambiguous native writes shall not duplicate or lose pending work → existing plus targeted wake tests; installed Windows behavior shall show one attributed delivery and no later generic turn → bounded dogfood without manual receive; workflow/redline/CI checks shall pass.

**Plan review:** Initial and revised clean-context Luna reviews are recorded under `## Plan review`. The revised review approved the structured block after requiring the exact one-object stdout wire shape, bounded non-empty reason, no `hookSpecificOutput`, and exit 0; these are now explicit in the Plan and Verification plan.

**Approvals:** Not required at this risk level.

**Exceptions:** —

**State:** Ready to implement

<!-- agent-workflow:end -->

## Implementation

- Established task context and recorded the live mismatch before guarded edits.
- Clean-context pre-edit redline review classified `app/codex_wake.py` and `app/dependencies.py` GRAY/watch, all test/docs paths blue, with no boundary violation or mandatory checkpoint.
- Added the single Codex UserPromptSubmit boundary guard: only the exact internal wake plus a successful dict response containing exactly `deliveries == []` exits 2 before dedup, memory, or model work. Relay failure, malformed response, invalid scope, non-wake prompts, and attributed delivery retain their prior paths.
- Added direct hook boundaries and a real caller-surface lifecycle that retains an accepted native prompt, lets a competing hook claim and ACK, and then executes the retained prompt.
- Updated RW-002 to distinguish Pallium scheduling coalescing from the uncancellable native accepted-prompt race.

## Evidence

- Read-only Relay DB trace: newest delivery to this exact session was `relay-reply-7d7e5fde...`, created 03:09:12 UTC and delivered once at 03:09:25; no delivery exists near the 03:15:49 empty wake.
- Read-only source history: exact generic wake recorded at 03:15:49; the immediately repeated identical prompt was deduplicated by the hook and therefore absent from source storage.
- Codex CLI 0.149.1 embedded hook contract: `UserPromptSubmit hook exited with code 2 but did not write a blocking reason to stderr`, confirming exit 2 plus stderr is the supported pre-model block path. Official OpenAI documentation search did not expose this contract.
- The new caller-surface regression failed before the guard because the retained wake reached `/item-and-query`; it passes after the guard.
- Committed revision `454eeb6d` verification: focused hook/wake/lifecycle/contract/integration suite passed 143 tests in 15.40 seconds with four existing Pydantic forward-reference warnings; import boundaries and the local workflow gate were clean; no wall-clock wait was added.
- Normal hook-path handling of the relaydev blocker report emitted the attributed payload and exact scope, then left its delivery `delivered` with one attempt. The report arrived during this already-running turn and was not evidence of a second missed injection.

## Plan review

Clean-context Luna review required two clarifications: confirmed-empty means a successful dict response with deliveries present and exactly [], never None or malformed; and the lifecycle regression must retain an independently accepted native prompt before the competing real hook claims and ACKs. Both are incorporated. A focused follow-up approved blocking a valid but changed current scope because the old-scope delivery remains durable and untouched; missing/invalid scope performs no turn call and remains fail-open. No prompt-carried scope or hash is needed.

After the installed exit-2 disproof, a fresh clean-context Luna review found the structured plan protocol-plausible and required one clarification: pin the exact top-level stdout object `{"decision":"block","reason":"..."}`, with a bounded non-empty reason, no `hookSpecificOutput`, and normal exit 0. The Plan now states that wire contract; no other blocker remained.

## Result review

Installed exact-session witness against empty relaydev inbox: native `codex queue --thread` accepted the exact sentinel, the hook skipped memory ingestion, but Codex still sampled a model turn and answered “No Relay delivery was injected this turn.” Direct hook execution confirmed stderr plus native exit code 2, so the installed runtime disproves the exit-2 blocking assumption. The binary exposes `UserPromptSubmitCommandOutputWire` with top-level `decision` and `reason`, motivating the revised structured-block plan.

Clean-context review of `63f3a76a` found two related blockers: a valid bounded turn may return `deliveries=[]` with `has_more=true` for oversized pending work, and a partial dict such as `{"deliveries": []}` is not a confirmed canonical response. The guard now requires `deliveries=[]`, `has_more is false`, and integer `remaining_count == 0`; direct malformed-response and public-route oversized-pending regressions cover both. The reviewer also correctly rejected a completed roadmap claim before the required installed Windows witness, so RW-002 remains provisional until that witness passes.
