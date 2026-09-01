<!-- agent-workflow:start -->
**Outcome:** A persisted exact-session Relay send never fails merely because its resolved Codex session reference cannot be passed to `subprocess.Popen`.

**Target:** Pallium Relay MCP Codex wake adapter.

**Scope:** Add the smallest validation/fallback correction in `app/mcp/server.py` and one focused regression case in `tests/test_mcp_server.py`.

**Constraints:** Preserve persist-first behavior, exact-target-only wake, payload-free notification, ordinary-turn fallback, and current cross-platform launch behavior. No API, storage, schema, roadmap, service, or other runtime changes.

**Completion criteria:** Non-printable session references are skipped, and any `ValueError` raised by process launch leaves the already-persisted send response unchanged.

**Risk:** Elevated

**Complexity:** Simple

**Reason:** `app/mcp/server.py` is a guarded gray runtime path. The correction is one trust-boundary guard plus its focused regression.

**Discovery:** CodeRabbit inline review `discussion_r3901710558` identified that embedded NUL reaches `Popen`, which raises `ValueError` outside the existing `OSError` fallback. Verification against merged main confirms both gaps remain. The other five inline findings target discarded batch-branch files and symbols absent from current main.

**Material assumptions:** Python string `isprintable()` rejects embedded NUL; a focused assertion disproves this if false. `Popen` may raise `ValueError` before starting a process; a mocked regression disproves preservation if the MCP tool does not return the persisted response.

**Plan:** Reject non-printable resolved session references, catch `ValueError` with `OSError`, add one regression covering both paths, run the focused and full MCP server tests, then reply to every PR #82 inline thread with either the fix commit or the verified obsolete-branch rationale.

**Verification plan:** Non-printable input and launch `ValueError` preserve the send result without starting/retrying wake → focused MCP test. Existing wake behavior remains intact → full `tests/test_mcp_server.py`.

**Plan review:** CodeRabbit clean-context inline review `discussion_r3901710558` (2026-09-01), independently verified against merged main.

**Approvals:** Not required at this risk level; user explicitly requested that the missed review comments be investigated and addressed.

**Exceptions:** —

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

- 2026-09-01: Added non-printable session-ref rejection and `ValueError` fallback after persisted send. Focused wake regression: 9 passed. Full MCP server suite: 51 passed with 4 existing Pydantic warnings. `git diff --check` passes. Verified the other five PR #82 inline findings reference discarded batch-branch symbols absent from current main.
