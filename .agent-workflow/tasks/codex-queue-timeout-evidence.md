<!-- agent-workflow:start -->
**Outcome:** Timeout diagnostics for Codex queue launches distinguish a live child from an exited child and preserve only a bounded stderr category.

**Target:** Pallium.

**Scope:** `app/codex_wake.py`, `tests/test_codex_wake.py`, and the unresolved incident entry in `roadmap/features/add-wake-first-relay-delivery.md`.

**Constraints:** Do not change wake behavior, retries, timeouts, transport, or the ambiguous timeout result. Do not log raw stderr, commands, payloads, paths, or unvalidated delivery IDs. Cleanup remains best effort and must still run.

**Completion criteria:** When a Codex queue wait times out, diagnostics include a validated delivery reference, the pre-cleanup child return code or `none`, and a bounded stderr category, while launch result, cleanup, and reservation fences remain unchanged.

**Requirement baseline:**
{"source":"user request and incident evidence supplied by task owner","outcome":"Timeout diagnostics for Codex queue launches distinguish a live child from an exited child and preserve only a bounded stderr category.","scope":"`app/codex_wake.py`, `tests/test_codex_wake.py`, and the unresolved incident entry in `roadmap/features/add-wake-first-relay-delivery.md`.","constraints":"Do not change wake behavior, retries, timeouts, transport, or the ambiguous timeout result. Do not log raw stderr, commands, payloads, paths, or unvalidated delivery IDs. Cleanup remains best effort and must still run.","completion_criteria":"When a Codex queue wait times out, diagnostics include a validated delivery reference, the pre-cleanup child return code or `none`, and a bounded stderr category, while launch result, cleanup, and reservation fences remain unchanged."}

**Risk:** Elevated

**Complexity:** Simple

**Reason:** `app/codex_wake.py` is gray under the current policy, so Redline sets an Elevated floor; the narrow diagnostic correction is one coherent change.

**Discovery:** `_finish_launch` returns `("ambiguous", "timeout", None)` on `TimeoutExpired`, performs bounded kill/reap cleanup, and currently drops the exception's partial stderr and the child's return code. Existing nonzero-exit logs already validate/correlate `delivery_ref` and use `_stderr_category`. `TimeoutExpired.stderr` can be bytes despite `text=True`; current helper assumes `str`. The incident cause remains unproved: one live queue timeout expired with attempts 0, while subsequent same-target cold→idle and other idle probes passed. Evidence details are in the task-owner handoff and summarized in the roadmap entry; no delivery was resent and no service/config change was made.

**Material assumptions:** The `TimeoutExpired` exception exposes only child-produced partial stderr (possibly bytes); the already existing bounded categorizer is sufficient once it safely accepts that shape. If tests or runtime behavior disprove this, stop and return to planning without changing wake behavior.

**Plan:** Capture `process.poll()` before cleanup; poll failures map to `none`. Bound `TimeoutExpired.stderr` to `str`, `bytes`, or `None`, truncating bytes before UTF-8 replacement decode, then use the existing safe categorizer. Always perform existing bounded cleanup before best-effort correlated logging; guard category/logging failures so neither can skip cleanup or replace `("ambiguous", "timeout", None)`. Extend the existing stderr log with pre-cleanup exit code or `none`, validating `delivery_id` as existing logs do. Add focused regressions for poll `None`/0/nonzero/raising, logger failure, cleanup ordering/result retention, and bytes/non-ASCII/hostile stderr redaction; reuse existing HTTP caller coverage. Update the roadmap with unresolved incident evidence and make no reliability claim. Stop if scope requires changing behavior or new infrastructure.

**Verification plan:** When timeout occurs, `_finish_launch` shall retain `("ambiguous", "timeout", None)` and always attempt bounded cleanup despite poll/category/logger failures → `python -m pytest tests/test_codex_wake.py -q -n 0`, including ordering and failure edge cases plus existing HTTP caller coverage. When partial stderr is bytes or contains hostile/non-ASCII text, logs shall expose only the bounded category and validated delivery reference → focused logging tests. The unresolved incident status shall remain explicit → inspect roadmap diff.

**Plan review:** Agent technical review: `/root/idle_queue_diagnosis`, review of HEAD `08fca03771c026d302811dd2bc544fd0dda3e3a7` on 2026-10-04. Reviewer accepted scope and core plan with the recorded addition of poll/log failure guards, cleanup ordering, byte truncation, and corresponding regressions; GO after that correction.

**Approvals:** Not required at this risk level.

**Exceptions:** —

<!-- Ready to implement | Blocked | Ready for review -->
**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

Pre-edit review accepted the plan after explicit timeout cleanup and diagnostic failure coverage was added. `_finish_launch` now records a pre-cleanup scalar poll result, classifies bounded timeout stderr including bytes, cleans up before guarded correlated logging, and preserves the timeout result and fence behavior. The canonical roadmap records the incident evidence and leaves the cause unresolved.

## Evidence

Incident evidence supplied by task owner. Failing delivery `relay-delivery-005fb2cc989246d1a2a6311cd22dda81` timed out at 2026-10-04 05:59:36.502049 UTC, expired at 06:09:05 with attempts 0. A subsequent same-target cold→idle probe and another idle target passed with attempts 1 and target markers. These probes do not establish the original cause. No payload, marker, or raw session identifiers are copied into roadmap prose.

Baseline red: with only `app/codex_wake.py` temporarily loaded from HEAD and restored byte-for-byte in `finally`, `test_timeout_fingerprints_unvalidated_delivery_reference` failed because timeout emitted no correlated diagnostic. Focused green: 11 passed. `tests/test_codex_wake.py`: 162 passed. Whole-change selector chose full suite; `python -m pytest tests/ -x -q`: 5,965 passed, 34 skipped, 2 xfailed in 386.35s. Agent Workflow check clean. Fresh Redline result is `build/redline-verdict.json` (GRAY, no checkpoints or boundary violations); import-linter result is `build/import-linter-report.json` (zero violations). Final reviewed source blob: `app/codex_wake.py` `2a553f1216feb63c4d5de0799f89f52f2d7ca2f6`; test blob: `tests/test_codex_wake.py` `0e3e7f1c27c9e58521653de5d47df3e92e08e670`.

## Result review

Agent technical review: `/root/idle_queue_diagnosis`.

Reviewed revision: Base HEAD `08fca03771c026d302811dd2bc544fd0dda3e3a7`; source blob `2a553f1216feb63c4d5de0799f89f52f2d7ca2f6`; test blob `0e3e7f1c27c9e58521653de5d47df3e92e08e670`.

Verification adequacy: Accepted for the diagnostics-only scope. The affected test file and selector-chosen full suite passed; regressions cover pre-cleanup scalar poll state, bytes/string partial stderr privacy, diagnostic failures, cleanup, and unchanged ambiguous result. No code findings.
