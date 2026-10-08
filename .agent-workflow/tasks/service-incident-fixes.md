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

**Verification plan:** Component and combined contracts -> migration legacy/complete/missing-table/repair/rollback/crash/concurrency/unknown-version/Relay-isolation tests; vector eligibility boundaries plus deterministic content-read avoidance and caller HTTP behavior; ASGI event-loop responsiveness, existing runner tracking and post-admission order; supervisor cancellation/recovery/timing checks. Test isolation guards and full selector checks cover interactions. Root verifies actual installed health/status/queue/embedding and startup measurements after separately approved rollout.

**Plan review:** Agent technical review: /root/incident_integration_review, clean-context GO on 2026-10-08 for this exact plan at 91232443. Component acceptance remains required; live rollout stays separately scoped.

**Approvals:** Approved by user 2026-10-08: "i might be gone later so you have my approval to drive this fix till merge and done"

**Exceptions:** None

**State:** Ready to implement
<!-- agent-workflow:end -->

## Implementation

2026-10-08: Isolated integration branch created from current origin/main. Integrated accepted startup timing/budget source 9b41eec0 and reviewed test isolation through ae2559c8. Integrated activation offload d72f59a2 after independent /root/incident_integration_review GO: all 12 sites, preserved callback order, deterministic ASGI proof and 148 affected passes. Integrated vector query source 537455d9 and independent result record 5e7d7747: deterministic content-read red/green, 16 focused passes, 69 affected passes and one existing skip. Migration result remains pending. Full validation has not started.

## Checkpoints

Combined full at dba1bb1f: 5457 passed, 36 skipped, 2 xfailed, one failure in 355.15 seconds. Unchanged test_snapshot_failure.py::test_restore_from_snapshot_with_older_schema exposes a real compatibility regression: pre-admission rejects the missing metadata column before the supported legacy upgrade. Root assigned the minimal version-aware correction to Relaydev; existing snapshot regression must remain unchanged. Private Python/Node network guards recorded no attempts; all 81 sampled owned process identities drained. Evidence retained in shared build/service-incident-full-20261008. No release acceptance or live migration follows this failed run.

2026-10-08: Integrated migration candidate a43a9c502f053e3a6f3c28276fe3677fc325ee76 without conflicts, production d5b0cd74. Independent component source review and child-fixture preflight accepted; final storage/isolation 50 passed, unchanged HTTP 43 passed, contract/lifecycle 96 passed, corrected owned-child cases 4 passed. No full run has started. Root source review found no additional issue. Current human through-merge approval above satisfies the source result approval requested in the earlier component record; it does not authorize unspecified live environment changes.

Persistence review covers native main user_version and atomic derived projection migration. API review covers projection execution context only, preserving caller-visible output and admission ordering. Existing independent component review is reused; combined interactions require a final non-implementer review. No architecture imports or behavior-contract changes are planned.
