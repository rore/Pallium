# Service incident fixes

<!-- agent-workflow:start -->
**Outcome:** Remove evidenced startup waste and event-loop blocking, preserve recovery diagnostics, and validate one combined release for the service incident.

**Target:** Pallium local service.

**Scope:** Integrate reviewed component changes to storage/sqlite.py, storage/sqlite_schema.py, api/routes.py, app/supervisor.py, app/runtime_logging.py, app/main.py, app/dependencies.py, their focused existing tests, test transport isolation, operations documentation and component Work Records. Base is origin/main 1042385ea78e4a372dbd1aac311b1ea9410273ba including PR307 recovery correction.

**Constraints:** Preserve storage data, Relay fencing and payload contracts, post-admission callback order and existing capacity limits. No new framework, dependency, configuration, test weakening, unrelated feature work or live operations from this checkout. Root alone handles separately scoped installed rollout and rollback; 120 seconds is mitigation, not a performance fix.

**Completion criteria:** Component regressions and failure lifecycles pass; combined isolated full validation and import/workflow checks pass; independent result review and CI findings are addressed before merge. Installed verification remains explicit and is not inferred from unit tests or merge.

**Requirement baseline:**
{"source":"human root task 01a0d7ce-83c6-77e2-90f7-d413894059e1 2026-10-08","outcome":"Remove evidenced startup waste and event-loop blocking, preserve recovery diagnostics, and validate one combined release for the service incident.","scope":"Integrate reviewed component changes to storage/sqlite.py, storage/sqlite_schema.py, api/routes.py, app/supervisor.py, app/runtime_logging.py, app/main.py, app/dependencies.py, their focused existing tests, test transport isolation, operations documentation and component Work Records. Base is origin/main 1042385ea78e4a372dbd1aac311b1ea9410273ba including PR307 recovery correction.","constraints":"Preserve storage data, Relay fencing and payload contracts, post-admission callback order and existing capacity limits. No new framework, dependency, configuration, test weakening, unrelated feature work or live operations from this checkout. Root alone handles separately scoped installed rollout and rollback; 120 seconds is mitigation, not a performance fix.","completion_criteria":"Component regressions and failure lifecycles pass; combined isolated full validation and import/workflow checks pass; independent result review and CI findings are addressed before merge. Installed verification remains explicit and is not inferred from unit tests or merge."}

**Risk:** High

**Complexity:** Moderate

**Reason:** Persistence and HTTP routing are red checkpoint surfaces; combined startup, failure recovery and callback execution require review across components.

**Discovery:** Root observed successful API startup at 57.167 seconds after a 120.990-second failed attempt. Successful storage setup 13.478 seconds, raw-vector backfill query 15.642 seconds, embedding 19.066 seconds. Existing source rebuilds work-reference rows on every provider open. A read-only candidate vector existence query returned false in 0.608 seconds while the original query hit a two-second progress deadline. Activation response projection still performs SQLite reads on the event loop. Installed PR307 launcher/recovery deployment is not yet complete. Evidence: shared build/emergency-startup-observation-20261008.json and build/startup-backfill-query-observation-20261008.md.

**Material assumptions:** Reuse only independently accepted component commits; failed review or changed semantics stops integration for correction. Test isolation must prevent requests to the installed service; any observed leak stops that run. Stage timings identify costs, not the complete historical outage cause; do not claim otherwise.

**Plan:** Keep the current installed mitigation untouched. Integrate accepted component revisions without unrelated branch history; resolve only concrete overlapping edits. Reuse component focused evidence, run combined affected checks for interactions and one selector-required full run with private home/transport isolation. Obtain independent combined result review, address findings, publish and merge through normal CI. Prepare exact backup and rollout impact separately before installed changes.

**Verification plan:** Migration legacy/complete/missing-table/repair/rollback/crash/concurrency/unknown-version/Relay-isolation tests; vector eligibility boundaries plus deterministic content-read avoidance and caller HTTP behavior; ASGI event-loop responsiveness, existing runner tracking and post-admission order; supervisor cancellation/recovery/timing checks. Test isolation guards and full selector checks cover interactions. Root verifies actual installed health/status/queue/embedding and startup measurements after separately approved rollout.

**Plan review:** Agent technical review: /root/incident_integration_review, clean-context GO on 2026-10-08 for this exact plan at 91232443. Component acceptance remains required; live rollout stays separately scoped.

**Approvals:** Approved by user 2026-10-08: "i might be gone later so you have my approval to drive this fix till merge and done"

**Exceptions:** No additional exception. Existing user incident directive favors short isolated iterations; final meaningful validation remains required.

**State:** Ready to implement
<!-- agent-workflow:end -->

## Implementation

2026-10-08: Isolated integration branch created from current origin/main. No production changes integrated yet. Worker-owned migration, vector query and activation projection changes are in progress; full validation has not started.

## Checkpoints

Persistence review covers native main user_version and atomic derived projection migration. API review covers projection execution context only, preserving caller-visible output and admission ordering. Existing independent component review is reused; combined interactions require a final non-implementer review. No architecture imports or behavior-contract changes are planned.
