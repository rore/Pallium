# Ignore Relay pair-initialization lock

<!-- agent-workflow:start -->
**Outcome:** SQLite pair-initialization lock sidecars no longer dirty repository checkouts.

**Target:** Pallium `.gitignore`.

**Scope:** Ignore the persistent `*.relay-pair-init.lock` sidecar created beside file-backed SQLite databases.

**Constraints:** No runtime behavior change and no broader database-file pattern.

**Completion criteria:** `git check-ignore` recognizes `pallium.db.relay-pair-init.lock`; existing ignore behavior remains intact.

**Risk:** Routine

**Complexity:** Simple

**Reason:** One additive ignore rule for an intentional generated lock sidecar; no runtime or guarded-path change.

**Approach:** Add the narrow suffix pattern already used by `SQLiteStorageProvider` and verify it with Git.

**Verification:** `git check-ignore -v pallium.db.relay-pair-init.lock`; agent-workflow/redline; CI.

**State:** Ready to implement
<!-- agent-workflow:end -->