# Compare Relay dashboard summaries at one observation time

<!-- agent-workflow:start -->
**Outcome:** Test whether dashboard reads preserve delivery state without mistaking elapsed time for a mutation.
**Target:** `test_dashboard_session_projection_avoids_global_collision_summary`.
**Scope:** Test clock only, in `tests/test_runtime_native_config_reconciliation.py`.
**Constraints:** Keep full delivery equality, collision assertions, query checks, and production code unchanged.
**Completion criteria:** Both HTTP summary reads observe the same time, and all existing delivery, collision, and privacy assertions still run across the four existing cases.
**Requirement baseline:**
{"source":"work-record-initial","outcome":"Test whether dashboard reads preserve delivery state without mistaking elapsed time for a mutation.","scope":"Test clock only, in `tests/test_runtime_native_config_reconciliation.py`.","constraints":"Keep full delivery equality, collision assertions, query checks, and production code unchanged.","completion_criteria":"Both HTTP summary reads observe the same time, and all existing delivery, collision, and privacy assertions still run across the four existing cases."}
**Risk:** Routine
**Complexity:** Simple
**Reason:** Test-only change outside protected contract files.
**Approach:** Use the dashboard's existing fixed-datetime test pattern and freeze only its module clock, after fixture creation. Reproduce the failure with a controlled clock crossing one second between the two summary calls.
**Verification:** A controlled second read reproduced the baseline failure (age 0 versus 2 seconds, all 11 other fields equal). All 45 tests in the affected file passed afterward, including the four projection cases. The whole-change selector chose full; ordinary hosted CI is pending.
**State:** Blocked
<!-- agent-workflow:end -->

Hosted CI on #436 recorded 0 versus 1 second for elapsed pending age,
with every other delivery field equal. It did not execute the changed
OpenCode plugin. This correction is separate from that release.

The test fixes only the two HTTP summary observation times, after its
fixtures are set up. It still compares every delivery field, checks
collisions and privacy, and rejects a global aggregate in the projected
reads. No production change or service restart. Hosted qualification
is the only remaining test step.
