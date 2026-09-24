# Prove isolated Codex post-failure Relay delivery

<!-- agent-workflow:start -->
**Outcome:** The isolated callback-loss recovery regression proves the recovered Relay payload reaches a delivered state exactly once.

**Target:** Pallium Relay Codex wake validation.

**Scope:** `tests/test_codex_wake.py`, `roadmap/features/add-wake-first-relay-delivery.md`, and this Work Record only.

**Constraints:** No production behavior changes, live recipient experiments, native queue writes, fence clearing, or model/effort/scope changes. Reuse existing verified suite evidence.

**Completion criteria:** After an exact HTTP claim commits and its callback is lost, a live lease holds the fence; after lease expiry one replacement wake is scheduled, the recovered HTTP turn exposes the same payload, ACK yields delivered with attempts 2, and later sweeps do not duplicate wake or payload.

**Requirement baseline:**
{"source":"manager-task-01a07bef-18c8-71b2-89ab-c0cbe91e73ad","outcome":"The isolated callback-loss recovery regression proves the recovered Relay payload reaches a delivered state exactly once.","scope":"`tests/test_codex_wake.py`, `roadmap/features/add-wake-first-relay-delivery.md`, and this Work Record only.","constraints":"No production behavior changes, live recipient experiments, native queue writes, fence clearing, or model/effort/scope changes. Reuse existing verified suite evidence.","completion_criteria":"After an exact HTTP claim commits and its callback is lost, a live lease holds the fence; after lease expiry one replacement wake is scheduled, the recovered HTTP turn exposes the same payload, ACK yields delivered with attempts 2, and later sweeps do not duplicate wake or payload."}

**Risk:** Routine

**Complexity:** Simple

**Reason:** Test, roadmap, and Work Record paths are Redline blue; no production or contract surface changes.

**Approach:** Extend the existing isolated callback-loss HTTP regression through second turn, ACK, public status readback, and no-repeat sweep. Update the roadmap's stale review status and evidence boundary.

**Verification:** Exact callback-loss recovery node and tests/test_codex_wake.py locally; reuse the prior 5,300-pass repository suite and installed Desktop witnesses; PR CI runs the repository suite.

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

Pre-edit classification: all intended paths blue, no checkpoints or boundary risk. The existing regression stops after one stubbed replacement launch; it does not observe recovered payload delivery. Intended edits are limited to the existing test, roadmap status, and this record.

The test now drives a recovered exact /relay/turn through payload readback, /relay/deliveries/ack, delivered status with attempts 2, reservation release, and no further wake or payload. The roadmap's stale “under review” wording is corrected in the same test-bearing change. The original plan named a local full-suite run; the task's explicit cost constraint instead reuses the already passing 5,300-test result because production code is unchanged, with PR CI providing the fresh broad check. The known Windows 1385 apply_patch failure required exact-file deterministic replacements; only the named files were written. Skill-feedback trigger 1 dropped: this is a documented machine-local environment issue, not agent-workflow-owned.

## Evidence

The exact regression passed (1 test, 2.20s) and tests/test_codex_wake.py passed (139 tests, 39.49s) from this isolated worktree using the repository virtual environment. The installed loaded-idle Desktop witness and earlier busy-to-idle witness remain separate native-path evidence; the test's native launcher is stubbed and does not prove Desktop failure recovery. Independent routine review found no blocking issue and requested an explicit live-lease assertion. The stored UTC timestamp is naive; the test now normalizes it through its existing controlled_now helper. The final exact node passed (1 test, 1.10s).