<!-- agent-workflow:start -->
**Outcome:** Windows-full CI installs the dependencies required by every test it runs.

**Target:** `.github/workflows/ci.yml` Windows-full matrix.

**Scope:** Add the existing `mcp` optional extra to the Windows-full install command and update the routine Work Record to reflect the redline classification.

**Constraints:** Keep the workflow stages, test selection, and dependency definitions unchanged; do not change application behavior.

**Completion criteria:** Both Windows-full Python jobs can collect and run `tests/test_mcp_server.py` without `ModuleNotFoundError`, and CI governance passes.

**Risk:** Elevated

**Complexity:** Moderate

**Reason:** Redline classifies the workflow change as Elevated; the implementation itself is one existing dependency extra added to one install command.

**Discovery:** The post-merge push run fails in both Windows-full matrix jobs while collecting `tests/test_mcp_server.py`; `.github/workflows/ci.yml` installs `.[dev,vector]` there, while the main test matrix installs `.[dev,vector,mcp]`. The failure is independent of PR #167 source changes.

**Material assumptions:** The existing `mcp` optional extra is the intended dependency source; disproof would be a subsequent collection failure after the extra is installed, which would return the task to discovery.

**Plan:** Keep the minimal workflow change, validate the focused MCP suite locally, run redline and agent-workflow checks, obtain clean-context plan review, then commit, PR, wait for all checks, merge, and verify the post-merge Windows-full run.

**Verification plan:** When Windows-full installs dependencies, it shall include the `mcp` extra → inspect workflow and CI install step. When the full Windows matrix collects MCP tests, it shall import `mcp` successfully on Python 3.12 and 3.13 → post-merge `windows-full` jobs. When the repository workflow is evaluated, it shall pass Work Record/redline gates → local checker and PR CI.

**Plan review:** Clean-context review accepted the one-line existing-extra change and verification plan; no actionable findings.

**Approvals:** Not required at this risk level.

**Exceptions:** —

**State:** Ready for review
<!-- agent-workflow:end -->
