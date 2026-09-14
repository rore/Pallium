<!-- agent-workflow:start -->
**Outcome:** Pallium's installed `minimap-roadmap` skill matches the current upstream package and runs against Pallium.

**Target:** Pallium integration.

**Scope:** Refresh `.claude/skills/minimap-roadmap/**` verbatim from Minimap's current packaged skill, reconcile the stale Relay trace sentence in `roadmap/scope.md`, and record this Work Record.

**Constraints:** Do not change Pallium runtime, data, other roadmap content, Agent Workflow installation, or Minimap upstream. Use Minimap's packaged lifecycle scripts.

**Completion criteria:** Installed and upstream skill trees have identical file lists and content modulo Windows line endings, the installed package reports Minimap 0.3.1, and its launcher successfully runs Minimap for Pallium.

**Risk:** Routine

**Complexity:** Simple

**Reason:** Redline excludes vendored `.claude/skills/**`; the Work Record is blue. This is a deterministic package copy with no behavior authored in Pallium.

**Approach:** Copy the current 38-file upstream `minimap-roadmap` package over Pallium's installed copy without deleting unrelated paths, reconcile the completed Relay trace note in `roadmap/scope.md`, then verify exact tree parity.

**Verification:** SHA-256 tree comparison, installed `start-server.mjs`, and Pallium's focused Minimap integration checks if present.

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

- Discovery found Agent Workflow already matches upstream exactly. Minimap's 11 raw-file differences reduce to one real Git-normalized change: package version 0.3.0 to 0.3.1; the other differences are Windows line endings.
- Copied all 38 upstream files without deletion; Git normalization retains only the real package-version change.
- Trigger 2 dropped: the user's correction addressed my request misread, not missing product or skill guidance.
- Trigger 3 dropped: pply_patch failed because of the documented machine-local Windows sandbox constraint; the unsupported --version probe was not a documented Minimap command and package status supplied the supported evidence.

## Evidence

- Upstream and installed trees: 38 files each, zero content differences when Windows line endings are ignored.
- Installed metadata and lifecycle status report Minimap 0.3.1; packaged restart succeeded at http://localhost:4312 (PID 7080), and the Pallium board URL was opened.
- Import boundary check, Redline reporter, and Agent Workflow checker passed with no boundary or review checkpoint findings.
- git diff --cached --check passed on the staged two-file diff based on c699719f.
