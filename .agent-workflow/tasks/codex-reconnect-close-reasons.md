# Explain retained Codex reconnect refusals before registration

Provenance: [#375](https://github.com/rore/Pallium/pull/375) and
[`add-wake-first-relay-delivery`](../../roadmap/features/add-wake-first-relay-delivery.md).
This replacement starts at `5d33ed575a264cbe31f38991dbc54dd16b2dbd5c`.

<!-- agent-workflow:start -->
**Outcome:** The existing retained Codex close log identifies why a reconnect candidate was rejected before REGISTER.
**Target:** Retained Codex inventory worker reconnect.
**Scope:** The owned candidate exits before REGISTER in app/mcp/codex_desktop_bridge.py, the existing retained recovery fixture, and this Work Record.
**Constraints:** Preserve predicate order, short-circuiting, disposal, fencing, timing, retry and protocol. Do not add a log on success or change anything after REGISTER. No publication or installed operations.
**Completion criteria:** Pre-READY expiry reports reconnect-window-exhausted. After successful READY, stop, expiry and other eligibility failures report their distinct close reasons; each rejection disposes the exact candidate once with no candidate REGISTER. Healthy adoption adds no diagnostic.
**Requirement baseline:**
{"source":"roadmap/features/add-wake-first-relay-delivery.md","outcome":"The existing retained Codex close log identifies why a reconnect candidate was rejected before REGISTER.","scope":"The owned candidate exits before REGISTER in app/mcp/codex_desktop_bridge.py, the existing retained recovery fixture, and this Work Record.","constraints":"Preserve predicate order, short-circuiting, disposal, fencing, timing, retry and protocol. Do not add a log on success or change anything after REGISTER. No publication or installed operations.","completion_criteria":"Pre-READY expiry reports reconnect-window-exhausted. After successful READY, stop, expiry and other eligibility failures report their distinct close reasons; each rejection disposes the exact candidate once with no candidate REGISTER. Healthy adoption adds no diagnostic."}
**Relationships:**
{"schema_version":1,"sources":[{"provider":"minimap","scope_ref":"roadmap:v1:git:github.com/rore/pallium#roadmap","local_ref":"item:v1:add-wake-first-relay-delivery"}],"pull_requests":[]}
**Risk:** Elevated
**Complexity:** Simple
**Reason:** The runtime bridge is a watched, gray path. This change labels existing cleanup; it does not change channel ownership or the wire contract.
**Discovery:** Both owned pre-REGISTER exits in InventoryWorker._auto_reconnect use the generic close reason. Earlier eligibility checks own no candidate. The existing close sink accepts bounded reasons from _CLOSE_REASONS; the retained MCP fixture drives recovery through the actual worker and protocol.
**Material assumptions:** The existing stop, elapsed, capability, continuity and unresolved observations remain authoritative and are not repeated to pick a label.
**Plan:** Invoke Agent Workflow before source edits. Add three allowed reasons, label pre-READY expiry, and turn the existing post-READY short circuit into an ordered reason selection with the same one cleanup call. Extend the existing retained MCP recovery fixture; no other runtime changes.
**Verification plan:**
Pre-READY expiry and post-READY stop/expiry/eligibility, exact disposal and no REGISTER on refusal -> test_actual_mcp_idle_ready_preserves_or_fences_source_channel.
Valid adoption with no new log -> test_actual_mcp_idle_ready_preserves_or_fences_source_channel[resolved-transport-failure].
Subsystem and integration compatibility -> both affected reconnect test files and the full non-slow suite selected by scripts/test-plan.py.
**Plan review:** Agent technical review: the independent Pallium architect accepted the narrow current-main replacement, reported in the manager's assignment for #375 at 5d33ed57. Use the existing observations and close sink only, leaving the REGISTER and adoption path alone.
**Approvals:** Not required at this risk level. Standing reliability fix approval applies to the assigned offline implementation.
**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

Scope: `InventoryWorker._auto_reconnect`, `_CLOSE_REASONS`, and
`test_actual_mcp_idle_ready_preserves_or_fences_source_channel`.
The pre-REGISTER guard now selects a reason from the same ordered
checks and calls `_finish` at the original point. There is no added
diagnostic call, native observation, or success-path I/O.

## Evidence

Base `5d33ed57`, plus the two-file uncommitted application/test diff.
Git blobs: bridge `f96bf29d6bcec72ea898afd844d1dad9e75017c8`;
test `ec99832f0f45720083b38870ca82ff243d7da2ec`.

- Before the runtime edit, five cases failed on the existing `cleanup`
  label and the valid adoption control passed. An earlier invocation
  collected no cases because the local dependency path omitted pywin32.
- After the edit, both reconnect files passed: 242 tests on Windows
  CPython 3.13.14. The new cases verify the actual close log via MCP,
  one exact candidate disposal, and no candidate REGISTER. The
  adoption control confirms no added success record.
- Import boundaries passed. Redline classified the bridge gray with no
  required checkpoint. The local workflow check passed; the PR-history
  check needs a committed head and was not satisfied by the local diff.
- The selected full non-slow lane ran once in an isolated Windows profile
  on CPython 3.13.14. It stopped with exit 2: 2,717 passed, 2 failed,
  3 skipped and 1 xfailed. `test_unusable_claude_credentials_revoke_exact_wake[long_socket]`
  failed while setting up a valid prerequisite registration in the other
  container: `mark_active` returned 503 with `setup_deadline` and 696 ms
  in `setup_pragma`. `test_claude_session_start_compact_leaves_registry_state_untouched[pending_close]`
  failed because the initial registration returned `False` before the
  test reached compaction. The second failure's cause is unestablished.
  Neither failing call reaches the changed Codex retained reconnect path.
  The full run remains failed. Private `full-once/result.xml` SHA-256:
  `fb279c3d1a29137e122f423062720bac3e0a361063d988867b13bfd086ecdc79`.

## Handoff

`fix/codex-reconnect-close-reasons` is uncommitted at base `5d33ed57`.
The two tested blobs above are unchanged. The manager accepted source
and focused evidence for ordinary hosted validation. The two unrelated
Claude registration failures remain part of the failed local run.
The old #375 branch and installed environment were untouched.

## Result review

Agent technical review: The independent architect accepted the exact
source and focused evidence for publication and normal hosted checks.

Reviewed revision: `5d33ed57` plus bridge `f96bf29d` and caller-test
`ec99832f`.

Verification adequacy: The 242 focused passes verify reason selection,
disposal once and no REGISTER on rejection, with unchanged successful
adoption and no extra I/O. Neither failure in the full Windows run
reaches the changed path. One has an acquisition-deadline diagnosis;
the other remains unclassified. No full or installed pass is claimed.
