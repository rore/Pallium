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

**State:** Ready to implement
<!-- agent-workflow:end -->

## Implementation

2026-09-30: Agent Workflow invoked first; new isolated branch feat/claude-test-wake-isolation in C:/Dev/rore/Pallium/.worktrees/claude-test-wake-isolation at de29df94. Intended paths are only tests/test_claude_code_integration.py and this record. Whole-change applicability selects normal workflow: neither tests nor Work Records are doc-only exempt. Pre-edit Redline rules classify both paths blue; Routine/Simple. Independent bounded plan review requested before code edits. PR268 remains frozen at 86e243e0 except its completed attribution correction.

Established diagnosis reused: conftest provides a temporary PALLIUM_CLAUDE_WAKE_DIR, but common.py imports the profile-pinned binding first; the shared helper overrides binding-match without rebinding wake directories. The prior failed fixture wrote into the installed namespace. An isolated USERPROFILE validation workaround did not repair this helper. No new live inspection or cleanup is needed for implementation.

Canonical roadmap: roadmap/features/add-wake-first-relay-delivery.md remains queued and manager-owned. This test-only fix neither proves unloaded activation nor changes production wake reliability.

## Plan review

Agent technical review: native clean-context /root/fixture_plan_review, gpt-6.1-sol low, 2026-09-30, reviewed a2da9ecd and the bounded refinement. Approved two-directory rebinding for all shared-loader callers. Pre-existing P2: a session_start caller can contact the imported local service, and USERPROFILE isolation does not fence HTTP. Resolved in the plan with a common-local urllib/request SimpleNamespace copy; capture original urlopen/build_opener at test-module import and fence only copied defaults with OSError, preserving explicit mocks and unrelated global urllib. Cover default fail-closed calls, before/after mocks, repeated imports and five pinned-binding register/close variants with full pinned-tree preservation. No P1/P2 blocker with this test-only design; classification remains Routine/Simple.

## Evidence

Pre-edit check initially lacked the new checkout's required import-boundary report and blocked correctly. Running the existing scripts/run-import-linter.py generated real backend evidence; fresh Redline then BLUE/exit 0 and Agent Workflow clean/exit 0. No fabricated report or enforcement bypass.

Pending caller red/green and required checks; prior PR268 validation is not validation of this new test-fixture change.
