<!-- agent-workflow:start -->
**Outcome:**
Tests do not inherit the live hook actor or live user-profile hook state.

**Target:**
Test harness and dynamically loaded Claude hook tests.

**Scope:**
`tests/conftest.py` and `tests/test_claude_code_integration.py` only.

**Constraints:**
Test-only change; do not modify production code or live state.

**Completion criteria:**
The two failing nodes pass with inherited `PALLIUM_HOOK_ACTOR_REF` present, and the changes are committed.

**Risk:** Routine

**Complexity:** Simple

**Reason:** —

**Approach:**
Ignore inherited actor state in pytest and point dynamically loaded hook common state at the isolated wake directory.

**Verification:**
Run the two specified failing pytest nodes with inherited actor present; inspect exact diff.

**State:** Ready for review
<!-- agent-workflow:end -->


Implementation: Added the autouse fixture cleanup for inherited PALLIUM_HOOK_ACTOR_REF and redirected dynamically loaded hook common state to a sibling of the isolated wake directory.

Evidence: Parent verification found the hook loader used os without importing it; added the missing stdlib import. The original focused invocation was blocked before collection because the bundled Python lacked fastapi. Rerun with the shared repository venv: one node passed; the second exposed that `_load_claude_hook("common")` needs to use the loaded module itself, which is now corrected.

Final evidence: `C:\Dev\rore\Pallium\.venv\Scripts\python.exe -m pytest tests/test_claude_code_hooks/test_session_pin.py::TestIdentityCache::test_same_repo_reuses_container_and_actor_without_git tests/test_claude_wake_dispatch.py::test_crash_after_claim_idle_stop_rewakes_actual_claude_hook_once -q -n 0` passed with the inherited actor: 2 passed in 1.18s. Normal inherited-environment full suite: 4786 passed, 33 skipped, 2 xfailed in 215.46s. Smart result review approved `259d110f` with no blocking findings; its P3 reproducibility nit is addressed by this exact command.
