# Distinguish OpenCode enroll settlement stages

<!-- agent-workflow:start -->
**Outcome:** Existing contended-writer diagnostics distinguish OpenCode enroll flush, COMMIT, and rollback without changing transaction behavior.
**Target:** Relay writer settlement at baseline `24fe8d64d778156eba320de3d25a9adb8efafe0e`.
**Scope:** `storage/sqlite_queue.py`, `core/errors.py`, and existing writer diagnostic tests. Reuse the busy-waiter observation and writer completion records for OpenCode enroll only.
**Constraints:** No extra log records, raw SQL or request data, route admission timing, timeout or retry tuning, readiness changes, live instrumentation or rollout, further local full runs, or protected-contract edits. Publish only the exact reviewed candidate for first hosted validation; no merge before hosted disposition.
**Completion criteria:** Real HTTP enroll contention distinguishes a held flush from a held COMMIT, captures rollback and available completed timings, and preserves the original error, commit or rollback result, and gate release behavior. Other verbs retain their existing observations.
**Requirement baseline:**
{"source":"work-record-initial","outcome":"Existing contended-writer diagnostics distinguish OpenCode enroll flush, COMMIT, and rollback without changing transaction behavior.","scope":"`storage/sqlite_queue.py`, `core/errors.py`, and existing writer diagnostic tests. Reuse the busy-waiter observation and writer completion records for OpenCode enroll only.","constraints":"No extra log records, raw SQL or request data, route admission timing, timeout or retry tuning, readiness changes, live instrumentation or rollout, broad local diagnosis run, publication, or protected-contract edits.","completion_criteria":"Real HTTP enroll contention distinguishes a held flush from a held COMMIT, captures rollback and available completed timings, and preserves the original error, commit or rollback result, and gate release behavior. Other verbs retain their existing observations."}
**Behavior changes:**
[{"target":"task-context.constraints","classification":"requirement-change","before":"No extra log records, raw SQL or request data, route admission timing, timeout or retry tuning, readiness changes, live instrumentation or rollout, broad local diagnosis run, publication, or protected-contract edits.","after":"No extra log records, raw SQL or request data, route admission timing, timeout or retry tuning, readiness changes, live instrumentation or rollout, further local full runs, or protected-contract edits. Publish only the exact reviewed candidate for first hosted validation; no merge before hosted disposition.","reason":"Both isolated full attempts stopped on import prerequisites; independent review accepted the exact candidate and focused evidence.","impact":"First hosted validation only; neither local attempt counts as a pass.","alternatives":"Run another local full suite or leave the reviewed diagnostic unpublished.","authority":{"scope":"task","name":"task-owner"},"approval":{"by":"user","reference":"Standing task-owner approval for routine Pallium reliability releases; exact evidence retained privately.","verbatim":"you got a blanket approval"}}]
**Relationships:**
{"schema_version":1,"sources":[{"provider":"minimap","scope_ref":"roadmap:v1:git:github.com/rore/pallium#roadmap","local_ref":"item:v1:add-wake-first-relay-delivery"}],"pull_requests":[]}
**Risk:** Elevated
**Complexity:** Moderate
**Reason:** Provisional Redline classification: watched `storage/**` and `core/**` implementation paths and blue tests. Observability spans the native transaction boundary and shared diagnostic projection; no red paths or persistence/transaction contract change proposed.
**Discovery:** Retained evidence bounds a long OpenCode enroll writer to settlement, not to a specific SQLite call. The current settlement starts at body exit and ends after successful transaction settlement, before busy-timeout reset or session close. A source-extracted synthetic control distinguished those boundaries without identifying the incident cause.
**Material assumptions:** Existing owner context is available before enroll settlement and is shared with both contention projections. If it cannot carry a bounded phase observation without changing ownership, errors, or transaction order, stop rather than add a parallel recorder.
**Plan:** Invoke the `/agent-workflow` skill to create the Work Record and classify risk, before any code edit. Obtain independent technical plan review. Pass the existing owner to settlement observation without enabling turn-only SQL hooks for enroll. At the existing flush, explicit COMMIT, and rollback calls, record fixed phase names and monotonic start/return observations for OpenCode enroll only. Publish a bounded snapshot to the existing settlement projection; an active phase carries a lower bound, a returned phase retains its duration, a raised phase is not reported as successful, and an unreached phase does not get a fabricated duration. Keep the old total/state and validator bounds. Keep diagnostics best effort and isolated from all transaction, cleanup, and primary-error paths. No new logs or admission timing.
**Verification plan:**
- Held flush, COMMIT, or rollback is attributed to the same writer; completion preserves the primary result, durable state, and successor progress → `test_http_enroll_settlement_distinguishes_held_calls`.
- Other verbs, projection privacy and bounds, and gate/cleanup behavior stay intact → poll/turn HTTP controls, `test_enroll_settlement_projection_bounds_fields`, and `test_terminal_settlement_releases_before_cleanup_only_when_confirmed`.
- Whole-change qualification → local selector and Workflow checks, then the first hosted full run. Preserve both incomplete local runs.
**Plan review:** Independent non-designer GO on exact plan blob `babab60b4eb071e168baa457792dd6cbd77f6c86`. See Plan review below.
**Approvals:** Not required at this risk level.
**State:** Ready for review
<!-- agent-workflow:end -->

## Plan review

Agent technical review: Independent architect GO on plan blob `babab60b4eb071e168baa457792dd6cbd77f6c86` (review summarized here; original private Relay decision retained).

The independent architect verified the exact plan and approved the
enroll-only observation. Preserve the original error and the unconfirmed
fallback on failed rollback. Do not move gate release, timeout reset, or
session close. Verify the same writer while each call is held, then verify
completion, the durable result, and successor progress.

## Implementation

On `fix/opencode-enroll-settlement` at `24fe8d64`, edit only
`storage/sqlite_queue.py`, `core/errors.py`, and
`tests/test_relay_writer_diagnostics_e2e.py`. Keep the existing turn-only
SQL binding and settlement total independent of the enroll observations.

The existing busy and completion records now carry `enroll_settlement` for
OpenCode enroll only. An unreached call has no entry; a raised call is
not reported as returned. A failed rollback keeps the legacy settlement
unconfirmed, and the gate still releases after fallback cleanup.

## Evidence

Candidate is uncommitted on `24fe8d64d778156eba320de3d25a9adb8efafe0e`.
Exact Git blobs, in path order:

- `core/errors.py`: `0d7b2bf35f37884f597f810580244589bde39c4e`
- `storage/sqlite_queue.py`: `a434ec974f6dd89fafa8adbd6375928abe3dfc4b`
- `tests/test_relay_writer_diagnostics_e2e.py`: `471d01d8c3f94425e08178efd0bc0e4f3f107442`

Focused isolated Windows run: **26 passed**. Five OpenCode HTTP cases
held flush, COMMIT, or rollback in the real SQLite path. Two existing
turn HTTP cases checked the unchanged observation, ten projection cases
checked bounds and privacy, and nine existing settlement checks covered
cleanup and release. The OpenCode cases use the repository's ASGI HTTP
fixture, not an installed listener. `git diff --check` passed.

Whole-change validation of the same blobs: the selector chose `full` against
`origin/main` at `0aa8f0e9d8579f79eede6e69bfca839086bd086e`. One isolated
Windows CPython 3.13 attempt ran the selected `pytest tests/ -x -q`
command with cache disabled and JUnit output. It stopped at collection
(exit 2) in `test_codex_relay_fault_harness.py`: as the MCP import failed,
the desktop bridge fixture did not define `_serve_protocol`. A direct
import identified missing `pywintypes` on `PYTHONPATH`. The installed
test dependencies already contain it; a separate import-only check passed
with the existing pywin32 directories added to the process environment.
No dependency, cache, or persistent environment changes were needed.

The local import boundary check found zero violations. Redline reported
GRAY (watched implementation paths) with no blocking findings or
protected-contract changes. Agent Workflow passed after recording the
existing independent review in the checker's required format.

The single released attempt with corrected process-local paths cleared
the MCP prerequisite and stopped at collection (exit 2) in
`tests/test_hermes_terminal_screen.py`: the local target lacks `pyte`,
required by the dev extra. The 26 focused passes still stand; neither
local attempt supplied a full result. No more local attempts or dependency
changes in this slice. Both results are under ignored
`build/enroll-settlement-validation-20261125/`.

## Result review

Agent technical review: independent non-implementer GO on the three blobs
listed above; exact review receipt retained privately.
Reviewed revision: the frozen candidate on `24fe8d64`; the three affected
paths have the same preimages on `5110d239`.
Verification adequacy: 26 focused cases cover the same writer across
flush, commit, and rollback, preserve the primary exception and unconfirmed
settlement when rollback fails, and check privacy, scope, and gate release.
This accepts focused evidence only. Release for one hosted run; no merge
before its disposition.

## Handoff

The readiness worktree and its review remain separate and unchanged. This task
uses `fix/opencode-enroll-settlement`. The incident establishes the settlement
boundary, not the physical cause. The focused controls verify the new
observations, not the live incident. No live changes.
