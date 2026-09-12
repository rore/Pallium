<!-- agent-workflow:start -->
**Outcome:**
Pallium's tracked `minimap-roadmap` skill exactly matches the complete self-contained upstream distribution at merged Minimap commit `9742bd7b7d1fd29757267fce6dde6e9df21bb013`.

**Target:**
Pallium.

**Scope:**
`.claude/skills/minimap-roadmap/**` and this Work Record only.

**Constraints:**
Copy the complete upstream skill distribution without hand-editing runtime internals. Preserve Pallium roadmap data and configuration. Do not touch other worktrees, Pallium runtime/service code, or the stable installed checkout before merge.

**Completion criteria:**
The tracked destination inventory and file hashes equal the upstream skill subtree at the pinned merged commit; its packaged lifecycle/status smoke check passes after activation.

**Risk:** Routine

**Complexity:** Simple

**Reason:**
Redline verdict BLUE: the Work Record is blue and `.claude/skills/**` is explicitly excluded as upstream-tested vendored content; no governed contract or boundary is touched.

**Approach:**
After the source pin and this plan are reviewed, export the full upstream `package/minimap/skills/minimap-roadmap` subtree at the exact commit and replace only the tracked destination copy. Do not selectively port files.

**Verification:**
Compare relative file inventories and SHA-256 hashes source-to-destination; run the bundled status/lifecycle smoke check during activation. Rely on the already-passing upstream suite for runtime behavior rather than duplicating broad tests in Pallium.

**State:** Ready to implement
<!-- agent-workflow:end -->

## Implementation

- Planning complete in isolated branch `chore/update-minimap-roadmap-pallium-participants` at Pallium base `27313e4e53f1baa502fbb3ef6e9331bdf7316ec6`.
- Upstream PR 13 was confirmed merged at `9742bd7b7d1fd29757267fce6dde6e9df21bb013`; verify that exact commit locally before exporting.
- Replacement is intentionally held pending plan/risk review. No vendored Minimap content, Pallium service, or installed checkout has changed.

## Evidence

- Upstream validation supplied at pickup: 249 passing tests, 2 expected skips; independent review approved all three fixes; live List/Columns cross-container and worktree attach/detach acceptance passed.
- Clean-context Redline review: `BLUE`, no checkpoints or boundary/contract impacts.
