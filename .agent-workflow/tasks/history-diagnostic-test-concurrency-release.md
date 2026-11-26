# Exercise concurrent History diagnostic creates on one event loop

<!-- agent-workflow:start -->
**Outcome:** Test concurrent History creates without racing FastAPI's route cache across event-loop threads.

**Target:** `tests/test_history_diagnostics_e2e.py` on `107712eb3d6fb95040c93700223e45113a7edefb`.

**Scope:** Release the reviewed concurrent History create test change in a standalone PR.

**Constraints:** No change to the shared fixture, app, dependencies, or product behavior. Keep the OpenCode logging change separate. Reuse local validation and run normal hosted checks. No rollout.

**Completion criteria:** Two concurrent HTTP requests on one event loop overlap inside the synchronous create path, return 200 and 201, and share one diagnostic ID.

**Requirement baseline:**
{"source":"work-record-initial","outcome":"Test concurrent History creates without racing FastAPI's route cache across event-loop threads.","scope":"Release the reviewed concurrent History create test change in a standalone PR.","constraints":"No change to the shared fixture, app, dependencies, or product behavior. Keep the OpenCode logging change separate. Reuse local validation and run normal hosted checks. No rollout.","completion_criteria":"Two concurrent HTTP requests on one event loop overlap inside the synchronous create path, return 200 and 201, and share one diagnostic ID."}

**Relationships:**
{"schema_version":1,"sources":null,"pull_requests":[]}

**Risk:** Routine

**Complexity:** Simple

**Reason:** Test-only harness change outside protected behavior contracts; the existing status and ID assertions stay intact.

**Approach:** Carry the exact reviewed test blob onto current main. Use one HTTPX ASGI transport and event loop, with a bounded barrier before the real save so both handlers must reach persistence before either writes.

**Verification:** Check that the touched base blob and candidate diff match the reviewed change. Reuse the focused History diagnostics E2E result and the integrated Windows evidence. Run the normal hosted checks on the standalone PR.

**State:** Ready for review
<!-- agent-workflow:end -->

## Evidence

The deterministic base witness reproduced a routing 404 when two
TestClient portal threads rebuilt FastAPI's shared route cache. The
test harness correction does not establish production exposure or
attribute earlier 404s.

- Test blob `0bdca0a0e33056626538b49ccc08b94796d0106d`; touched base
  blob `f7be77085ea69b4963a7ac8c1c316c14f08108a5` is unchanged from
  the original `e543ccc6` qualification base. The test diff matches
  the reviewed patch exactly on the new base.
- Focused Windows verification passed all 41 History diagnostics E2E
  tests. The earlier integrated Windows full non-slow run passed
  9,305 tests, with 48 skipped and 2 expected failures. That run
  included the exact test blob but was on a different composition;
  it is not hosted validation of this PR.
- The two earlier failed full-run receipts remain separate. No
  additional local full run. No retrieval or accessibility change.
