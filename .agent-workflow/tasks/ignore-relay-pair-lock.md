# Ignore Relay pair-initialization lock

<!-- agent-workflow:start -->
**Outcome:** SQLite pair-initialization lock sidecars no longer dirty repository checkouts.

**Target:** Pallium `.gitignore`.

**Scope:** Ignore the persistent `*.relay-pair-init.lock` sidecar created beside file-backed SQLite databases.

**Constraints:** No runtime behavior change and no broader database-file pattern.

**Completion criteria:** `git check-ignore` recognizes `pallium.db.relay-pair-init.lock`; existing ignore behavior remains intact; workflow and CI pass.

**Risk:** Elevated

**Complexity:** Simple

**Reason:** Redline classifies `.gitignore` as a gray-zone file even though this is one additive generated-sidecar rule.

**Discovery:** `SQLiteStorageProvider._relay_pair_initialization_lock` intentionally persists `<database>.relay-pair-init.lock`. Existing rules ignore the database and `*.schema.lock`, but not this pair lock, leaving the installed checkout dirty.

**Material assumptions:** The suffix is specific to generated Pallium lock sidecars. Disproved if a tracked source file legitimately uses the same suffix.

**Plan:** Add only `*.relay-pair-init.lock` beside the existing schema-lock rule; do not change runtime code or delete active lock files.

**Verification plan:** Generated pair-lock sidecar is ignored -> run `git check-ignore -v --no-index pallium.db.relay-pair-init.lock`; workflow compliance -> run redline/workflow and CI.

**Plan review:** Clean-context gpt-5.6-sol high review approved the exact suffix pattern and verification; no blocking findings.

**Approvals:** Not required for Elevated risk; clean-context plan review required.

**Exceptions:** —

**State:** Ready for review
<!-- agent-workflow:end -->

## Evidence

- `git check-ignore -v --no-index pallium.db.relay-pair-init.lock` resolves to the new narrow rule.
- Clean-context review confirmed .gitignore:49 exactly matches the generated suffix, hides no tracked file, and needs no runtime or test change.
