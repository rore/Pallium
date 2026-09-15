<!-- agent-workflow:start -->
**Outcome:** Determine whether the installed Codex native protocol can safely wake a genuinely unloaded Desktop task without seizing a live owner; make the next native queue failure diagnosable.

**Target:** Pallium Relay Codex wake adapter.

**Scope:** `app/codex_wake.py`, `tests/test_codex_wake.py`, one disposable exact-binary proof harness or focused test under `tests/relay/wake/`, this Work Record, and the existing RW-031 roadmap entry. `core/codex_wake.py` is excluded unless proof establishes that durable queue identity is both necessary and safely representable, followed by reclassification and review.

**Constraints:** Do not touch, wake, open, or message existing user tasks; do not use Codex app `create_thread`; do not restart services/hosts or change hooks/configuration. Use only a disposable fixture task and the exact installed binary. Never log raw stderr, prompts, paths, settings, credentials, or private data. Do not restore the removed `codex exec resume` path or ship cold activation unless ownership, Desktop usability, hooks/MCP/permissions/settings preservation, and turn lifecycle are evidenced.

**Completion criteria:** A bounded isolated-home proof reports whether queue/add followed by threadId-only resume preserves one exact queued submission, whether dispatch is automatic or requires exact queue/start, and whether server B rejects the exact resume while server A demonstrably owns the fixture but accepts the identical request after A exits. Exact before/after cwd/settings/hooks/MCP/permissions metadata is unchanged, any started turn is terminal before shutdown, and the isolated fixture is removed after both servers exit. If any guarantee or Desktop-equivalent owner route cannot be established, production cold activation remains unchanged and the missing Codex platform capability is named. A simulated native nonzero exit writes a sanitized category and numeric code only to the existing correlated local log, without raw stderr or state-machine changes. Focused regressions and workflow/redline checks pass; RW-031 states only measured results.

**Risk:** Elevated

**Complexity:** Moderate

**Reason:** Clean-context Redline classified `app/codex_wake.py` and optional `core/codex_wake.py` gray/watch, with tests/roadmap/record blue and no boundary or contract checkpoint. Moderate complexity reflects native owner/lifecycle uncertainty and the requirement to preserve Desktop execution context.

**Discovery:** Installed Codex `0.154.0-alpha.6.2` supports `thread/queue/add`, `thread/queue/list`, `thread/queue/start`, and threadId-only `thread/resume`. The preserved workflowdev row proves enqueue without observed activation for that unloaded task; the isolated proof did not establish a safe Desktop-equivalent activation or ownership route. The relaydev native process exited nonzero with no row, but `_finish_launch` discards stderr and `_attempt_from_launch` discards the numeric exit code. Commit `0591e982` removed the former `codex exec resume` then active-writer fallback because inherited service cwd changed task workspace and Relay scope; it must not be restored. Commit `98218255` previously logged numeric exit codes, but later activation refactoring dropped that field while RW-026 still claims it.

**Material assumptions:** An isolated temporary Codex home and workspace can test protocol ownership without touching live Desktop state, but cannot by itself prove Desktop-context preservation; absent a supported Desktop owner-discovery/handoff surface, that gap is a production blocker rather than an inference. Server A must first prove it owns and can query the exact fixture; server B must then reject the exact same threadId-only resume while A lives and accept it after A exits, or exclusivity is unproven. No paid model call is needed unless queue dispatch cannot be observed otherwise; at most one bounded authorized turn may then be used and recorded. Raw subprocess output is untrusted; only a fixed category and integer return code may enter the existing correlated local log.

**Plan:** First, complete this workflow/risk gate and clean-context review before edits or native submission. Reuse the exact installed app-server protocol with an isolated temporary Codex home and workspace. Server A creates and demonstrably owns one durable fixture; capture exact non-secret cwd/settings/hooks/MCP/permissions metadata. Attempt the same threadId-only resume from server B while A lives, then terminate A cleanly and repeat the identical resume from B. Queue exactly once, retain the returned ID, verify exact queue/list readback, observe automatic dispatch or invoke queue/start for only that ID, require terminal completion before shutdown, compare metadata, and remove the verified isolated directories only after both processes exit. Any concurrent-owner success, duplicate dispatch, metadata drift, nonterminal turn, failed post-owner resume, unexpected protocol event, timeout, or failed fixture disposal ends the proof and forbids a production activation change. The isolated proof cannot establish Desktop equivalence; absent a supported owner-discovery/handoff surface, report that specific blocker. Independently restore the already-returned numeric exit code to the existing sanitized correlated local log only; do not change `ActivationAttemptResult`, durable trace schemas, scheduler behavior, or public contracts. Add one focused regression plus only affected existing wake tests. Fold measured RW-031 and stale RW-026 wording into the eventual code PR; no separate documentation PR. Key conventions: exact-ID-only operations, queue/add is enqueue rather than admission, ambiguous writes are never retried, official installed protocol surfaces only. Target files are limited to the Scope above.

**Verification plan:** When the isolated task is unloaded, one queue/add shall yield one exact readback ID and resume/start behavior shall be observed without duplicate dispatch -> bounded exact-binary transcript/assertion. When A owns and can query the task, B shall reject the exact resume; after A exits B shall accept the identical request, or the result shall name the ownership blocker -> same disposable proof with explicit controls. Before/after non-secret execution metadata shall match, every turn/process shall be terminal, and verified isolated directories shall be removable -> proof assertions and cleanup result. When native launch exits nonzero, the existing correlated local log shall retain a fixed safe category and integer code while hostile stderr remains absent -> one focused `tests/test_codex_wake.py` regression. Existing wake outcomes, reservation retention, trace shape, and retry behavior shall remain unchanged -> affected Codex wake test nodes/file. Final diff shall pass workflow and Redline checks.

**Plan review:** Clean-context Sol review `/root/native_queue_plan_review`; initial REQUEST_CHANGES addressed and re-review returned PASS.

**Approvals:** Not required at this risk level.

**Exceptions:** —

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

- 2026-09-15: Established isolated branch `feat/codex-native-queue-proof` from `origin/main` at `0f48c9c8`. Clean-context Redline classified the intended scope GRAY, Elevated/Moderate, with no boundary violation or mandatory checkpoint. Required clean-context plan review returned PASS after four concrete corrections.
- Generated the exact installed `0.154.0-alpha.6.2` experimental schema into excluded `build/` and ran a stdlib harness against only a temporary Codex home/workspace. Server A created and read the disposable task. Server B returned `-32600` for identical threadId-only resume both while A lived and after A exited; queue/add returned `-32603`; the isolated home remained temporarily locked after the parent app-server processes exited. Four known OpenAI/Codex auth variables were removed and no model turn occurred. The exact fixture directory was validated and removed after handles released.
- The failed positive controls triggered the accepted mechanical stop: no production cold-activation path was added. A safe Desktop-equivalent owner-discovery/handoff and lifecycle route was not proven.
- Restored the already-returned native exit code to the existing sanitized correlated local wake log without changing activation traces, persistence, retry, reservation, or delivery semantics. Added one hostile-stderr regression and corrected RW-031's cause, inference, and blocker.

## Evidence

- Preserved installed evidence: workflowdev has one durable native queue row with no turn; relaydev has `nonzero_exit` with no retained code/stderr and no row. Neither target was touched.
- Isolated exact-binary proof command: `python build/codex_native_queue_proof.py` using a one-off excluded stdlib harness and exact installed binary. Sanitized second-run output:

```json
{
  "binary": "codex-cli 0.154.0-alpha.6.2",
  "concurrent_resume_error_category": "unclassified_b5b97eec5104",
  "concurrent_resume_error_code": -32600,
  "concurrent_resume_succeeded": false,
  "fixture_cleanup_ok": false,
  "owner_exit_clean": true,
  "post_owner_exit_error_category": "unclassified_b5b97eec5104",
  "post_owner_exit_error_code": -32600,
  "post_owner_exit_resume_succeeded": false,
  "queue_add_error_category": "unclassified_b019a7dd5da0",
  "queue_add_error_code": -32603
}
```

  A start/read succeeded. Metadata preservation, dispatch, terminal-turn, duplicate, and queue-drain checks were not reached. The reported cleanup failure was the in-run immediate deletion while handles remained; a subsequent exact-path validated removal succeeded. The proof is inconclusive for ownership and therefore blocks production cold activation.
- `python -m pytest tests/test_codex_wake.py::test_nonzero_exit_log_keeps_code_without_stderr -q -n 0`: 1 passed.
- `python -m pytest tests/test_codex_wake.py -q -n 0`: 86 passed.
- `python -m py_compile app/codex_wake.py tests/test_codex_wake.py` and `git diff --check`: passed.
- Fresh Redline verdict: GRAY/watch on `app/codex_wake.py`, blue tests/roadmap, zero boundary violations or checkpoints. `scripts/agent-workflow-check.py --repo-root . --slug codex-native-queue-proof`: clean.
- `python -m pytest tests/ -x -q`: 5019 passed, 34 skipped, 2 xfailed in 232.93s.

## Plan review

Initial REQUEST_CHANGES: isolate the fixture and define supported disposal; prove A ownership before B rejection and repeat the identical B request after A exits; keep exit-code retention app-local/log-only unless reclassified for trace persistence; make unsafe proof outcomes mechanical stop conditions. The revised plan incorporates all four. Re-review returned PASS.

## Result review

Clean-context smart review `/root/native_queue_result_review` returned REQUEST_CHANGES: restrict RW-031 to measured outcomes and retain the sanitized failed-proof output with unreached checks explicit. Both corrections are applied. Re-review found one P3 wording overclaim; corrected to four known OpenAI/Codex auth variables. Final re-review returned PASS with no remaining findings.
