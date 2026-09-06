<!-- agent-workflow:start -->
**Outcome:** Codex Relay wake never produces a later generic turn after another admitted turn has already consumed the persisted delivery.

**Target:** Pallium Relay Codex wake delivery.

**Scope:** Codex wake ownership/admission and rearm logic, caller-surface regressions, and the canonical wake roadmap.

**Constraints:** Preserve persist-first delivery, exact session+container+actor isolation, ambiguous native-write safety, automatic backlog continuation, and public Relay contracts; no wall-clock sleeps or new dependencies.

**Completion criteria:** A delivery consumed by a natural or competing admitted turn cancels or suppresses its redundant native wake; close sends and cross-scope sends remain isolated; pending work is never lost; exact caller-surface tests and installed Windows dogfood produce no empty follow-up turn.

**Risk:** Elevated

**Complexity:** Moderate

**Reason:** Agent-redline classified the guarded `app/**` wake surfaces GRAY/watch with no boundary violation. Moderate complexity reflects a runtime race across persistence, native queue admission, hook claim/ACK, and in-memory ownership.

**Discovery:** Live dogfood produced an exact generic wake at 2026-09-06 03:15:49 UTC and a duplicate follow-up although the Relay database had no delivery to this session after 03:09:12. RW-002 currently claims this class is fixed. The current adapter clears exact-scope ownership at `/relay/turn` admission, while native `codex queue` writes cannot be cancelled; the precise scheduling race still requires focused history/test tracing.

**Material assumptions:** The empty turns are caused by redundant native wake submission or retained native queue work, not by an unrenderable current delivery. Disproof: a recent pending/claimed delivery or formatter rejection at the observed turn. Action if disproved: return to planning and fix the claim/render boundary instead.

**Plan:** Pending focused discovery and clean-context review. Trace every scheduling/admission/rearm caller and the PR #95/#108 regressions; reproduce deterministically through the public send, real wake adapter, and real hook surface; apply the smallest shared-state fix that suppresses only redundant admission while preserving exact-scope isolation and ambiguous-write safety; update RW-002 evidence. Target files: `app/codex_wake.py`, `app/dependencies.py` only if the callback contract must change, `tests/test_codex_wake.py`, `tests/test_agent_relay_e2e.py`, and `roadmap/features/add-wake-first-relay-delivery.md`.

**Verification plan:** Redundant native wake after another turn consumes the delivery shall not create an empty follow-up → deterministic caller-surface E2E with injected process/hook ordering; close and cross-scope sends shall remain isolated → focused concurrency/scope regressions; ambiguous native writes shall not duplicate or lose pending work → existing plus targeted wake tests; installed Windows behavior shall show one attributed delivery and no later generic turn → bounded dogfood without manual receive; workflow/redline/CI checks shall pass.

**Plan review:** Pending clean-context review after discovery.

**Approvals:** Not required at this risk level.

**Exceptions:** —

**State:** Blocked

<!-- agent-workflow:end -->

## Implementation

- Established task context and recorded the live mismatch before guarded edits.
- Clean-context pre-edit redline review classified `app/codex_wake.py` and `app/dependencies.py` GRAY/watch, all test/docs paths blue, with no boundary violation or mandatory checkpoint.

## Evidence

- Read-only Relay DB trace: newest delivery to this exact session was `relay-reply-7d7e5fde...`, created 03:09:12 UTC and delivered once at 03:09:25; no delivery exists near the 03:15:49 empty wake.
- Read-only source history: exact generic wake recorded at 03:15:49; the immediately repeated identical prompt was deduplicated by the hook and therefore absent from source storage.

## Plan review

Pending.

## Result review

Pending.
