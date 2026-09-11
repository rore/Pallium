<!-- agent-workflow:start -->
**Outcome:** Codex Relay wake failures are diagnosable from local logs without inferring which delivery or session failed.

**Target:** Pallium Relay Codex wake adapter.

**Scope:** `app/codex_wake.py`, `app/dependencies.py`, focused Codex wake tests, and the wake-first roadmap incident record.

**Constraints:** Do not change routing, queueing, retry, claim, ACK, or delivery-state behavior. Never log prompts, stderr content, environment values, secrets, or local paths. Add no dependency.

**Completion criteria:** Every attempted Codex wake launch identifies its delivery plus deterministic recipient-session and container fingerprints; failed or ambiguous native launches emit a sanitized reason and numeric exit code when available on that same correlated line; recovery logs identify the exact persisted candidate without exposing free-form refs; focused and full tests remain green.

**Risk:** Elevated

**Complexity:** Moderate

**Reason:** `app/**` is a gray/watch runtime surface and `app/dependencies.py` is shared orchestration. The change is observability-only with no boundary or policy checkpoint, but correlation must not leak untrusted or sensitive content.

**Discovery:** Dogfood messages sent one second apart produced anonymous `failed` and `queued` log entries, so send ordering was the only way to infer ownership. Relay state and recipient JSONL proved one delivery was hook-injected and ACKed while the other stayed pending at attempts=0 and progressed only through a direct app message. `_wake_after_debounce` already owns delivery/session/container identifiers but omits them from its log; `_launch` captures then discards stderr and exposes only a coarse outcome. Recovery logs likewise omit candidate identity. The wake roadmap explicitly deferred correlation telemetry until a concrete failure could not be diagnosed from existing evidence; this incident meets that condition.

**Material assumptions:** Canonical `relay-delivery-<32 lowercase hex>` IDs are Pallium-generated and safe to log exactly; any noncanonical delivery value plus every session/container ref is free-form and must use a bounded SHA-256 fingerprint. If tests or review show logging changes alter scheduler outcomes or expose raw subprocess content, stop and return to planning.

**Plan:** Keep scheduler control flow and the public `_launch` outcome strings unchanged. Add a stdlib SHA-256 helper that renders canonical Pallium delivery IDs exactly and fingerprints every other delivery/session/container value to a fixed length. Have one internal launch-result helper return the unchanged outcome plus a fixed reason (`invalid_codex_home`, `timeout`, `os_error`, `value_error`, `nonzero_exit`) and optional numeric exit code; the existing `_launch` wrapper still returns only the outcome, while the scheduler logs result and correlation together. Add the same safe refs to recovery-candidate logs. Extend existing tests for overlapping same-session/different-container failures and the full success/failure matrix, then add RW-026 and update the roadmap's two statements that correlation telemetry remains deferred. Stop if diagnosis requires parsing or exposing stderr/exception messages.

**Verification plan:** When same-session wakes in different containers overlap, each attempted outcome shall carry the correct delivery reference and distinct fixed-length session/container fingerprints -> interleaved scheduler log-capture test. When native launch sees invalid home, `TimeoutExpired`, `OSError`, `ValueError`, nonzero exit, or success, it shall preserve the prior outcome and spawn count while returning only the fixed reason/optional exit code internally -> parameterized launch-result test with raw stderr, exception messages, CR/LF, Unicode, oversized, path, and secret sentinels absent from logs. Existing reservation retention and unreachable-callback tests shall remain green for queued/ambiguous/failed outcomes. When recovery considers a persisted candidate, its log shall identify the canonical delivery and fingerprints -> recovery log test. Existing behavior remains unchanged -> focused `tests/test_codex_wake.py`, workflow/redline gates, and full repository suite.

**Plan review:** Clean-context review `/root/codex_hook_plan_review`; initial REQUEST_CHANGES addressed in the revised plan and recorded below.

**Approvals:** Not required at this risk level.

**Exceptions:** —

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

- Created isolated branch `fix/codex-wake-log-correlation` from `origin/main` at `d213e079`.
- Pre-edit redline audit: `app/**` watch/gray, tests and roadmap blue, no boundary risk or checkpoint; Elevated/Moderate recommended.
- Added bounded stdlib SHA-256 correlation refs, fixed launch reason categories, and same-line outcome logging without changing the public launch outcome or scheduler state transitions.
- Added the same safe correlation refs to Codex persisted-wake recovery logs; Claude logging remains unchanged.
- Added launch-matrix, hostile-reference, overlapping-wake, and recovery-log regressions. Recorded RW-026 as diagnosis-only and removed stale roadmap deferral claims.
- After one machine-local `apply_patch` failure (`CreateProcessWithLogonW` 1327), used deterministic replacements limited to the named Work Record and roadmap files, per local instructions.

## Evidence

- Incident evidence: dev1 delivery attempts=1 and hook-injected/ACKed; dev2 delivery attempts=0 and remained pending while a direct app turn progressed independently. Service logs exposed only anonymous `failed` and `queued` outcomes.
- `python -m py_compile app/codex_wake.py app/dependencies.py tests/test_codex_wake.py` passed.
- `python -m pytest tests/test_codex_wake.py tests/test_claude_wake_dispatch.py -q -n 0`: 96 passed, 2 skipped.
- `git diff --check` passed.
- Smart result review found and the implementation corrected surrogate-unsafe fingerprint encoding plus a subprocess-to-log secrecy coverage gap; the focused 96-pass suite remained green after both fixes.
- `python -m pytest tests/ -x -q`: 4861 passed, 33 skipped, 2 xfailed in 190.78s.

## Plan review
Clean-context reviewer requested three corrections: correlate the reason on the same delivery/scope outcome; fingerprint free-form identifiers and test hostile values rather than relying on escaped raw text; and make the full launch/state verification matrix explicit while excluding non-attempt exits. The revised plan incorporates all three and limits the roadmap claim to diagnosis, not behavioral wake repair. Re-review returned PASS.

## Result review

Clean-context smart review /root/codex_hook_plan_review initially found two P2 issues: strict UTF-8 fingerprint encoding could raise on an unpaired surrogate and skip cleanup, and secrecy assertions bypassed the real subprocess-to-log path. Both were corrected with surrogate-safe deterministic encoding and an end-to-end scheduler launch matrix. Re-review returned PASS with no remaining findings.
