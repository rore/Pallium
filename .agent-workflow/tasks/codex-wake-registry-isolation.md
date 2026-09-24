<!-- agent-workflow:start -->
**Outcome:** An isolated Pallium instance cannot read or reconcile another instance's Codex Relay wake reservations by default.

**Target:** Pallium service.

**Scope:** Codex wake registry path resolution, app startup and recovery wiring, scheduling isolation, focused regression tests, and task documentation.

**Constraints:** Preserve the installed default Codex wake path and explicit override; do not migrate, copy, or clear existing reservations. Do not alter Claude hook/registry behavior in this PR.

**Completion criteria:** A service started against an isolated Relay database without a Codex wake-dir override uses an isolated Codex registry; default and explicit paths remain stable, and another instance's Codex reservations remain unchanged.

**Requirement baseline:**
{"source":"work-record-initial","outcome":"An isolated Pallium instance cannot read or reconcile another instance's Codex Relay wake reservations by default.","scope":"Codex wake registry path resolution, app startup and recovery wiring, scheduling isolation, focused regression tests, and task documentation.","constraints":"Preserve the installed default Codex wake path and explicit override; do not migrate, copy, or clear existing reservations. Do not alter Claude hook/registry behavior in this PR.","completion_criteria":"A service started against an isolated Relay database without a Codex wake-dir override uses an isolated Codex registry; default and explicit paths remain stable, and another instance's Codex reservations remain unchanged."}

**Risk:** Elevated

**Complexity:** Moderate

**Reason:** Runtime wake path files are gray/watch; multiple startup and registry callers require coordinated correction. No red-zone API/schema/security surface is planned.

**Discovery:** Direct app startup uses the configured Relay database but Codex and Claude wake registries default independently to the fixed ~/.pallium directories. Startup reconciliation can therefore release live Codex reservations after a temporary app starts against an isolated database. The default installed service path must retain its existing registry location.

**Material assumptions:** The resolved file-backed Relay database path is the durable Codex wake registry identity; distinct database paths need distinct paths. In-memory databases need app-local nonpersistent Codex registries. Claude hook intent isolation requires a separate cross-process change and is out of this PR.

**Plan:** Resolve the Codex wake path from the actual Relay database: explicit override first; conventional data/pallium-relay.db uses its parent home (preserving installed default); otherwise choose a sibling directory keyed by database filename. In-memory uses an app-local nonpersistent Codex registry. Pass the app-owned registry to lifespan recovery and scope process-global scheduling keys by registry identity. Add two-instance, default, explicit, Unicode, and in-memory tests. Stop if a Codex caller still opens a cross-instance registry.

**Verification plan:** Isolated app startup leaves the other instance's Codex reservation file unchanged, and default/explicit paths stay stable → `test_codex_wake_instance_isolation.py`, focused wake/startup suites, full repository suite, and CI.

**Plan review:** Clean-context Sol review found lifespan fallback, inherited-home mismatch, in-memory persistence, global schedule keys, and a separate Claude hook-path bug. Re-review confirmed the Codex-only plan has no technical blocker; Claude is a tracked partial-resolution follow-up.

**Approvals:** Not required at this risk level.

**Exceptions:** —

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

Discovery, risk classification, and clean-context review complete. The original baseline also includes Claude; this PR is the Codex slice, and the hook/service contract risk is tracked as [issue #234](https://github.com/rore/Pallium/issues/234).

Codex registry path now follows the resolved Relay DB; conventional installed home and explicit overrides stay stable. In-memory instances use app-local registries. Startup passes its registry to recovery. Scheduler keys include registry identity. An Astra code review found a same-stem/different-extension collision; full database filenames now key custom paths, with a regression.

## Evidence

- `tests/test_codex_wake_instance_isolation.py`: 4 passed.
- `tests/test_codex_wake.py`: 117 passed.
- Affected Claude/service/dashboard run: 196 passed, 20 skipped; one dashboard mock-seam failure fixed and exact node passed.
- Full parallel suite attempts stopped at unrelated hook identity / Claude transition tests after 4,517 and 1,955 passes, respectively; each failing node passed immediately when rerun serially. No claim of a full green local run; CI is required.
- `git diff --check`: clean.
