<!-- agent-workflow:start -->
**Outcome:** Shared Claude hook tests keep wake intent writes inside their temporary wake directory even when a profile binding pins another directory.

**Target:** Claude hook test helper and its caller regression coverage.

**Scope:** Change tests/test_claude_code_integration.py's shared _load_claude_hook helper and add anonymized caller regressions there; update this Work Record. No production files or PR268 edits.

**Constraints:** Preserve runtime binding/HTTP/timing/claim/ACK/retry behavior and existing tests. Never write to or clean live state, contact real wake transports, change recipient settings, or claim production timing improvement. Reuse established contamination diagnosis. Manager owns disposition, roadmap and rollout.

**Completion criteria:** A disposable pinned-binding regression fails before the helper fix and passes afterward across common and hook entry points; writes stay in the temporary test wake directory, pinned-state sentinel bytes stay unchanged, register/close lifecycle remains intact, existing lost-HTTP caller and affected tests pass, and selector-required validation and independent review are reported.

**Requirement baseline:**
{"source":"relay-reply-278dc7cb8778bc7335d7d6489c8f0c0767d8434f967f4beb47c48b88ac96ea1c","outcome":"Shared Claude hook tests keep wake intent writes inside their temporary wake directory even when a profile binding pins another directory.","scope":"Change tests/test_claude_code_integration.py's shared _load_claude_hook helper and add anonymized caller regressions there; update this Work Record. No production files or PR268 edits.","constraints":"Preserve runtime binding/HTTP/timing/claim/ACK/retry behavior and existing tests. Never write to or clean live state, contact real wake transports, change recipient settings, or claim production timing improvement. Reuse established contamination diagnosis. Manager owns disposition, roadmap and rollout.","completion_criteria":"A disposable pinned-binding regression fails before the helper fix and passes afterward across common and hook entry points; writes stay in the temporary test wake directory, pinned-state sentinel bytes stay unchanged, register/close lifecycle remains intact, existing lost-HTTP caller and affected tests pass, and selector-required validation and independent review are reported."}

**Risk:** Routine

**Complexity:** Simple

**Reason:** Only blue-zone tests and Work Record bookkeeping; no protected-contract, runtime, security, or policy mutation.

**Approach:** Invoke Agent Workflow before any code edit and retain this isolated branch and source-backed diagnosis. Rebind both shared helper wake directories to its existing temporary environment directory. Fence default urlopen/build_opener on a helper-local copy of urllib.request, preserving explicit mocks before/after loading and process-global urllib; leave production binding logic untouched. Add caller red first using a disposable profile with a valid conflicting pinned binding and mocked HTTP, then the shared-helper fix, focused/subsystem/selector validation and result review. Stop for broader scope or non-test writes.

**Verification:** Disposable binding register/close lifecycle through _load_claude_hook common/session_start/user_prompt_submit/stop/session_end callers and intent readback; existing lost-HTTP TestClient caller; affected Claude hook files; scripts/test-plan.py selected lane; fresh Redline/workflow and diff checks; bounded independent plan/result review.

**State:** Blocked
<!-- agent-workflow:end -->

## Implementation

2026-09-30: Agent Workflow invoked first; new isolated branch feat/claude-test-wake-isolation in C:/Dev/rore/Pallium/.worktrees/claude-test-wake-isolation at de29df94. Intended paths are only tests/test_claude_code_integration.py and this record. Whole-change applicability selects normal workflow: neither tests nor Work Records are doc-only exempt. Pre-edit Redline rules classify both paths blue; Routine/Simple. Independent bounded plan review requested before code edits. PR268 remains frozen at 86e243e0 except its completed attribution correction.

Established diagnosis reused: conftest provides a temporary PALLIUM_CLAUDE_WAKE_DIR, but common.py imports the profile-pinned binding first; the shared helper overrides binding-match without rebinding wake directories. The prior failed fixture wrote into the installed namespace. An isolated USERPROFILE validation workaround did not repair this helper. No new live inspection or cleanup is needed for implementation.

Canonical roadmap: roadmap/features/add-wake-first-relay-delivery.md remains queued and manager-owned. This test-only fix neither proves unloaded activation nor changes production wake reliability.

## Plan review

Agent technical review: native clean-context /root/fixture_plan_review, gpt-6.1-sol low, 2026-09-30, reviewed a2da9ecd and the bounded refinement. Approved two-directory rebinding for all shared-loader callers. Pre-existing P2: a session_start caller can contact the imported local service, and USERPROFILE isolation does not fence HTTP. Resolved in the plan with a common-local urllib/request SimpleNamespace copy; capture original urlopen/build_opener at test-module import and fence only copied defaults with OSError, preserving explicit mocks and unrelated global urllib. Cover default fail-closed calls, before/after mocks, repeated imports and five pinned-binding register/close variants with full pinned-tree preservation. No P1/P2 blocker with this test-only design; classification remains Routine/Simple.

## Evidence

Pre-edit check initially lacked the new checkout's required import-boundary report and blocked correctly. Running the existing scripts/run-import-linter.py generated real backend evidence; fresh Redline then BLUE/exit 0 and Agent Workflow clean/exit 0. No fabricated report or enforcement bypass.

2026-09-30: The new pinned-binding regression failed before the helper fix for all five entrypoints. It reached each valid profile binding and then found added `intents/`, `.lock`, and intent JSON entries under the pinned wake tree; mocked opener prevented network I/O. After the fix, the five lifecycle cases pass and the complete pinned tree remains byte-for-byte and path-for-path unchanged.

2026-09-30: Eight new loader regression cases pass, including both default HTTP fences, `pallium_request`/`relay_request`/register/close fail-safe behavior, and explicit `urlopen`/`build_opener` mocks before and after repeated imports. Global `urllib.request` remains unchanged outside explicit monkeypatches.

2026-09-30: Existing `tests/test_claude_wake_dispatch.py::test_post_start_lost_http_intent_reconciles_without_claiming_relay` passes (1 passed). Four affected Claude files pass: `tests/test_claude_code_integration.py`, `tests/test_claude_wake_dispatch.py`, `tests/test_claude_wake_registration.py`, and `tests/test_claude_wake_instance_isolation.py` (149 passed, 2 skipped). Every run used a fresh disposable `USERPROFILE`; no real-profile wake state was touched.

2026-09-30: Whole-change selector `C:\Dev\rore\Pallium\.venv\Scripts\python.exe scripts/test-plan.py --base origin/main` selected `full` and `python -m pytest tests/ -x -q`. That run used a fresh disposable `USERPROFILE` and stopped with `1 failed, 2120 passed, 2 skipped, 1 xfailed in 183.64s`: `tests/test_agent_relay_hooks.py::test_confirmed_switch_does_not_attach_old_identity_to_new_pin[claude-code-integrations/claude-code/hooks/common.py]` failed at line 1086 (`result is None`). The exact two-parameter node passed serially (2 passed). A serial run of `tests/test_agent_relay_hooks.py` then exposed a different existing Claude case, `test_legacy_pin_bootstraps_endpoint_alias_and_queued_delivery[claude-code]`, failing at line 1131 with `result is None` (89 passed). No assertions were weakened and no changes were made to that unrelated file; stop before any broader fix or full-suite rerun pending owner review.

Independent result review (parent-reported, base `4fb43677`): approved current diff with no P1/P2 findings, conditional on required validation. Validation remains incomplete because the selected full suite failed.

2026-09-30 bounded baseline diagnosis: exact detached base `de29df94bcd32d10ec5c81d03557ba683e89dc6b` used the same `tests/test_agent_relay_hooks.py` blob (`a2a27eb2a01358904f535a9f8a0ceacf33222be8`) and Claude `common.py` blob (`4b7971b53bbcad2c634e2ce70c85ef523237124d`) as this feature checkout. The one authorized serial run `python -m pytest tests/test_agent_relay_hooks.py -q -n 0`, under a fresh disposable `USERPROFILE`, passed (90 passed in 20.73s). This does not identify the feature-checkout failure cause or waive the failed selector evidence.

`git diff --check` passed. Reviewed test-file blob: `4f1e52cba1c6b95a9fe24e44a08462a2072cd723`. Only this test file and this Work Record are modified. All `apply_patch` calls succeeded; no fallback was used. State is Blocked pending task-owner direction on the unresolved full-suite failure in an unchanged caller test; causality is not established. Prior PR268 validation is not validation of this new test-fixture change.

## Result review

Agent technical review: native clean-context /root/fixture_plan_review, gpt-6.1-sol low, 2026-09-30.

Reviewed revision: 4fb43677 plus the test-file diff with blob 4f1e52cba1c6b95a9fe24e44a08462a2072cd723; reviewed content remains unchanged.

Verification adequacy: no P1/P2 in the shared-helper fix or disposable caller regressions. Focused lifecycle, mock isolation and existing lost-HTTP/subsystem checks are green. Completion remains blocked by the failed selected full suite; the standalone and baseline passes do not resolve or waive it. Preserve this evidence in a draft PR for platform CI and manager disposition; do not merge, claim release, repeat full tests blindly, or change runtime behavior/thresholds here. The roadmap umbrella remains queued and manager-owned.
