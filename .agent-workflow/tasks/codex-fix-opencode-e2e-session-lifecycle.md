<!-- agent-workflow:start -->
**Outcome:**
Windows full CI reliably completes the OpenCode structural-work-reference caller E2E.

**Target:**
Pallium test suite.

**Scope:**
tests/test_structural_work_refs_e2e.py only.

**Constraints:**
Production behavior and public contracts unchanged. Do not add sleeps, lengthen subprocess timeouts, or broaden CI serialization.

**Completion criteria:**
The caller E2E models one real OpenCode session from user prompt through assistant idle, preserves exact work-reference assertions, passes locally, and the hosted Windows-full matrix passes.

**Risk:** Routine

**Complexity:** Simple

**Reason:**
—

**Approach:**
Use the user session ID for the assistant idle event in the existing caller-surface E2E. Keep all assertions and the 20-second fail-fast bound unchanged.

**Verification:**
Run the full structural-work-reference E2E module serially, repository workflow/redline/diff gates, and both hosted Windows-full jobs. Inspect newer Actions runs for any additional failure.

**State:** Ready for review
<!-- agent-workflow:end -->

## Discovery

Main run 34028583850 failed only Windows-full Python 3.12 when the Node helper exceeded its 20-second outer timeout; the identical Python 3.13 job passed. The helper used unrelated user and idle session IDs, preventing the plugin's normal session scope pin from being reused and forcing six bounded Git subprocess probes. The isolated case passed in 1.88 seconds, supporting contention rather than a deterministic product failure.

## Implementation

- 2026-09-06: Reused the chat.message session ID for session.idle, matching the real OpenCode lifecycle and its scope-pin reuse.
- Machine-local fallback: apply_patch is unavailable with CreateProcessWithLogonW 1327, so the one scoped line was changed using an exact guarded replacement.

## Evidence

- Pre-fix exact isolated case: 1 passed in 1.88s; hosted Windows-full Python 3.12 timed out at 20s while Python 3.13 passed.
- Full affected module serial: 11 passed, 1 skipped in 5.26s; xdist: 11 passed, 1 skipped in 11.04s; existing Pydantic warning unchanged.
- Newer run 34028928907 reproduced the same test timeout on Python 3.13 while Python 3.12 passed; no different failure appeared.

## Result review

Self-review found one blue-zone test line changed; assertions, outer timeout, and production code remain unchanged. The test now drives user-to-assistant events through one session, as OpenCode does.