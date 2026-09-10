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

Final evidence: Shared-venv exact command passed with inherited actor: 2 passed in 1.82s.
