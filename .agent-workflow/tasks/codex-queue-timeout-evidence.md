<!-- agent-workflow:start -->
**Outcome:** Timeout diagnostics for Codex queue launches distinguish a live child from an exited child and preserve only a bounded stderr category.

**Target:** Pallium.

**Scope:** `app/codex_wake.py`, `tests/test_codex_wake.py`, the unresolved incident entry in `roadmap/features/add-wake-first-relay-delivery.md`, and only the background-worker setup wait in `tests/test_relay_capacity_isolation.py` (0.5s to 5s).

**Behavior changes:** [{"target":"task-context.scope","classification":"coverage-only","before":"`app/codex_wake.py`, `tests/test_codex_wake.py`, and the unresolved incident entry in `roadmap/features/add-wake-first-relay-delivery.md`.","after":"`app/codex_wake.py`, `tests/test_codex_wake.py`, the unresolved incident entry in `roadmap/features/add-wake-first-relay-delivery.md`, and only the background-worker setup wait in `tests/test_relay_capacity_isolation.py` (0.5s to 5s).","reason":"Give the test's background memory worker bounded CI scheduling time to reach the existing readiness barrier before caller assertions."},{"target":"task-context.constraints","classification":"coverage-only","before":"Do not change wake behavior, retries, timeouts, transport, or the ambiguous timeout result. Do not log raw stderr, commands, payloads, paths, or unvalidated delivery IDs. Cleanup remains best effort and must still run.","after":"Do not change application behavior, caller request deadlines, native wake timeouts, retries, or transport. The only timeout edit in this follow-up is the test's worker-start readiness wait; keep the caller's 5.0s request deadline, 10s worker release wait, and all post-start assertions unchanged. Preserve the ambiguous native timeout result, bounded cleanup, and diagnostic privacy.","reason":"Clarify the accepted test-only startup wait adjustment without changing runtime deadline or native wake behavior."}]

**Constraints:** Do not change application behavior, caller request deadlines, native wake timeouts, retries, or transport. The only timeout edit in this follow-up is the test's worker-start readiness wait; keep the caller's 5.0s request deadline, 10s worker release wait, and all post-start assertions unchanged. Preserve the ambiguous native timeout result, bounded cleanup, and diagnostic privacy.

**Completion criteria:** When a Codex queue wait times out, diagnostics include a validated delivery reference, the pre-cleanup child return code or `none`, and a bounded stderr category, while launch result, cleanup, and reservation fences remain unchanged.

**Requirement baseline:**
{"source":"user request and incident evidence supplied by task owner","outcome":"Timeout diagnostics for Codex queue launches distinguish a live child from an exited child and preserve only a bounded stderr category.","scope":"`app/codex_wake.py`, `tests/test_codex_wake.py`, and the unresolved incident entry in `roadmap/features/add-wake-first-relay-delivery.md`.","constraints":"Do not change wake behavior, retries, timeouts, transport, or the ambiguous timeout result. Do not log raw stderr, commands, payloads, paths, or unvalidated delivery IDs. Cleanup remains best effort and must still run.","completion_criteria":"When a Codex queue wait times out, diagnostics include a validated delivery reference, the pre-cleanup child return code or `none`, and a bounded stderr category, while launch result, cleanup, and reservation fences remain unchanged."}

**Risk:** Elevated

**Complexity:** Simple

**Reason:** `app/codex_wake.py` is gray under the current policy, so Redline sets an Elevated floor; the narrow diagnostic correction is one coherent change.

**Discovery:** `_finish_launch` returns `("ambiguous", "timeout", None)` on `TimeoutExpired`, performs bounded kill/reap cleanup, and currently drops the exception's partial stderr and the child's return code. Existing nonzero-exit logs already validate/correlate `delivery_ref` and use `_stderr_category`. `TimeoutExpired.stderr` can be bytes despite `text=True`; current helper assumes `str`. The incident cause remains unproved: one live queue timeout expired with attempts 0, while subsequent same-target cold→idle and other idle probes passed. A separate PR CI failure in `tests/test_relay_capacity_isolation.py` elapsed its first 0.5s worker-start readiness wait before the background handler set its event; caller requests still have a distinct 5.0s deadline and the test handler waits up to 10s for release. This failure occurred before the Relay/diagnostics assertions. The exact capacity test had not yet been run locally; the earlier local pass was for a Claude registration test. Evidence details are in the task-owner handoff; no delivery was resent and no service/config change was made.

**Material assumptions:** The `TimeoutExpired` exception exposes only child-produced partial stderr (possibly bytes); the already existing bounded categorizer is sufficient once it safely accepts that shape. The CI readiness failure reflects scheduling variance before the worker starts, so increasing only the test setup wait to 5s should admit the observed delay; if the exact test still fails after that point, stop and return to planning. Do not change the actual 5.0s caller deadline or any native wake behavior.

**Plan:** Preserve the reviewed diagnostics implementation unchanged. For the accepted CI setup correction, change only `started.wait` in `tests/test_relay_capacity_isolation.py` from 0.5s to 5s. Keep the 5.0s caller request deadline, 10s release wait, and all post-start assertions unchanged. Run the exact capacity test and use CI's observed pre-assertion timeout as red evidence; skip a temporary delay harness per task-owner direction. Reuse unchanged diagnostics evidence; root owns any further selector/CI validation. Do not change app code or rerun the local full suite.

**Verification plan:** When CI delays the background handler past the former 0.5s setup wait, the failure shall remain isolated to readiness before caller assertions → captured PR CI failure trace and exact capacity test after correction. The actual 5.0s caller request deadline and 10s worker release wait shall remain unchanged → inspect diff and execute `python -m pytest tests/test_relay_capacity_isolation.py -q -n 0`. Existing diagnostics behavior/evidence remains unchanged → reuse reviewed blobs, prior focused/full suite results, and import-linter evidence as authorized by root; root directs updated whole-diff CI validation.

**Plan review:** Agent technical review: `/root/idle_queue_diagnosis`, review of HEAD `08fca03771c026d302811dd2bc544fd0dda3e3a7` on 2026-10-04. Reviewer accepted scope and core plan with the recorded addition of poll/log failure guards, cleanup ordering, byte truncation, and corresponding regressions; GO after that correction.

Second plan review: `/root/idle_queue_diagnosis` reviewed base HEAD `92d3bbfac5bac4116463b9b41df56eff568bf21f` and approved only the test setup readiness wait change from 0.5s to 5s, before caller assertions; no application response or native wake timeout changes.

**Approvals:** Not required at this risk level.

**Exceptions:** —

<!-- Ready to implement | Blocked | Ready for review -->
**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

Pre-edit review accepted the plan after explicit timeout cleanup and diagnostic failure coverage was added. `_finish_launch` now records a pre-cleanup scalar poll result, classifies bounded timeout stderr including bytes, cleans up before guarded correlated logging, and preserves the timeout result and fence behavior. The canonical roadmap records the incident evidence and leaves the cause unresolved. The CI follow-up changes only the test readiness wait; caller deadlines, production behavior, and post-start assertions are untouched.

## Evidence

Incident evidence supplied by task owner. Failing delivery `relay-delivery-005fb2cc989246d1a2a6311cd22dda81` timed out at 2026-10-04 05:59:36.502049 UTC, expired at 06:09:05 with attempts 0. A subsequent same-target cold→idle probe and another idle target passed with attempts 1 and target markers. These probes do not establish the original cause. No payload, marker, or raw session identifiers are copied into roadmap prose.

Baseline red: with only `app/codex_wake.py` temporarily loaded from HEAD and restored byte-for-byte in `finally`, `test_timeout_fingerprints_unvalidated_delivery_reference` failed because timeout emitted no correlated diagnostic. Focused green: 11 passed. `tests/test_codex_wake.py`: 162 passed. Whole-change selector chose full suite; `python -m pytest tests/ -x -q`: 5,965 passed, 34 skipped, 2 xfailed in 386.35s. A later CI run failed the capacity test's 0.5s setup readiness barrier before caller assertions; it was a distinct setup timing failure from a Claude registration assertion. The exact capacity file now passes: 2 passed in 0.96s. No temporary delay harness was added. Root authorized reuse of the prior diagnostics/full-suite evidence; updated whole-diff CI will validate this test-only correction. Fresh Redline result is `build/redline-verdict.json` (new capacity test path blue; diagnostics app path gray; no checkpoint/boundary finding); import-linter result is `build/import-linter-report.json` (zero violations, reused because no imports changed). Workflow check passes all blocking predicates; it reports only the nonblocking `workrecord.commit_order` advisory because the original Work Record and implementation share commit `92d3bbfa`. Reviewed source blob: `app/codex_wake.py` `2a553f1216feb63c4d5de0799f89f52f2d7ca2f6`; original diagnostics test blob: `tests/test_codex_wake.py` `0e3e7f1c27c9e58521653de5d47df3e92e08e670`.

## Result review

Agent technical review: `/root/idle_queue_diagnosis`.

Reviewed revision: Base HEAD `08fca03771c026d302811dd2bc544fd0dda3e3a7`; source blob `2a553f1216feb63c4d5de0799f89f52f2d7ca2f6`; test blob `0e3e7f1c27c9e58521653de5d47df3e92e08e670`.

Verification adequacy: Accepted for the diagnostics-only scope. The affected test file and selector-chosen full suite passed; regressions cover pre-cleanup scalar poll state, bytes/string partial stderr privacy, diagnostic failures, cleanup, and unchanged ambiguous result. No code findings.

Follow-up result review: `/root/idle_queue_diagnosis` accepted the final one-line capacity test diff at base HEAD `92d3bbfac5bac4116463b9b41df56eff568bf21f`; no findings. The corrected capacity file passed 2 tests. Review confirmed only the setup wait changed; caller request deadline and assertions are unchanged.

Verification adequacy: The captured CI trace plus the exact capacity-file pass are sufficient for this isolated test setup correction. The previous full suite remains evidence for the unchanged diagnostics production/test code; root will run updated whole-diff CI. The Work Record check has no blocking predicates.
