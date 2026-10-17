<!-- agent-workflow:start -->

**Outcome:** Pallium's tracked Agent Workflow and Minimap roadmap consumers reflect the approved upstream source pins while retaining Pallium-specific behavior.



**Target:** Pallium repository.



**Scope:** The existing `.agents/skills/agent-workflow/**` and `.claude/skills/agent-workflow/**` mirrors, mapped `scripts/agent-workflow-check.py`, `.claude/skills/minimap-roadmap/**`, and this Work Record.



**Constraints:** Preserve Pallium applicability, policy, shadow mode, boundaries, import-linter, CI, hooks, settings, AGENTS guidance, and all consumer customizations. Use only committed package blobs from the assigned pins. Do not alter other paths, installed tools, service state, or publish.



**Completion criteria:** Only scoped consumer paths and this Work Record change; upstream updates are reconciled with Pallium customizations; source manifests and blob parity are recorded; applicable non-application checks pass.



**Requirement baseline:**

{"source":"work-record-initial","outcome":"Pallium's tracked Agent Workflow and Minimap roadmap consumers reflect the approved upstream source pins while retaining Pallium-specific behavior.","scope":"The existing `.agents/skills/agent-workflow/**` and `.claude/skills/agent-workflow/**` mirrors, mapped `scripts/agent-workflow-check.py`, `.claude/skills/minimap-roadmap/**`, and this Work Record.","constraints":"Preserve Pallium applicability, policy, shadow mode, boundaries, import-linter, CI, hooks, settings, AGENTS guidance, and all consumer customizations. Use only committed package blobs from the assigned pins. Do not alter other paths, installed tools, service state, or publish.","completion_criteria":"Only scoped consumer paths and this Work Record change; upstream updates are reconciled with Pallium customizations; source manifests and blob parity are recorded; applicable non-application checks pass."}



**Risk:** Elevated



**Complexity:** Moderate



**Reason:** The mirrored `.agents` consumer includes unclassified paths, setting the provisional Elevated floor. Multiple consumer trees and a mapped checker need coordinated source parity and compatibility review.



**Discovery:**

The reserved branch was clean at `f062cc72` with no branch-only commits, then fast-forwarded to fetched `origin/main` `f602753edf46d0b7a5d88bcd79725a143e311dba`. Whole-change documentation-only applicability does not apply: the scope includes workflow skill trees and a root checker outside the configured allowlist. The committed source pins match the requested revisions: Agent Workflow `2e1233634263695dc7c4a41eaf5122825158b2e6`; Minimap `5072122c7353f7519c1aeda4fcac072682b55b26`. Only the specified source package paths are candidates; the source checkouts contain unrelated dirty/untracked files and those were excluded.



The initial comparison used stale Agent Workflow baseline `a940b846` and incorrectly treated 13 files as Pallium customizations. Independent clean-context review compared them with the actual prior consumer pins (`fbe6c768` / `7f20e06`): both local mirrors are identical and all 13 files are exact committed upstream blobs, with zero Pallium-only deltas. The current package has 77 files per mirror versus 67 locally. The mapped root checker is the package's mapped consumer and will be copied from the same pin. Pallium's current Minimap skill matches its prior vendor pin `afbec214` (45 files); the assigned pin has 52 files, including 23 updates and 7 additions, with no Pallium-only tracked paths. The recent Pallium refresh Work Record is `.agent-workflow/tasks/pallium-minimap-roadmap-skill-refresh.md`.



**Material assumptions:**

The two assigned committed source pins remain authoritative. If source manifests or committed blobs do not match the pins, stop and report the mismatch before copying.



**Plan:**

Copy the exact committed 77-file Agent Workflow package to both existing mirrors and copy its mapped checker to `scripts/agent-workflow-check.py`. Include package `.gitattributes` inside each skill mirror; do not install package templates into root configuration or guidance. Copy the exact 52-file Minimap package only into `.claude/skills/minimap-roadmap/`. Preserve all out-of-scope Pallium config, policy, CI, hooks, settings, AGENTS, and documentation mirrors. Compare source manifests, both-mirror identity, and root checker blobs. Run the focused governance compatibility checks, Redline, and diff hygiene. Minimap JavaScript changes select full application qualification; do not start it while another agent owns the shared test slot. Stop on any out-of-scope path or unexpected source/package mismatch.



**Verification plan:**

Only scoped consumer paths and this Work Record change; Pallium root configuration and guidance remain intact → inspect final diff and path inventory. Both Agent Workflow mirrors equal the 77-file pinned package and each other; mapped root checker equals its source blob → compare package manifests and Git blob IDs. The Minimap skill equals its 52-file pinned package → compare package manifest and Git blob IDs. Focused governance compatibility checks, Redline, and diff hygiene pass → run those checks; full qualification waits for the shared test slot.



**Plan review:**

Agent technical review: `/root/consumer_plan_review` (native agent result delivered to root; reviewed this Work Record at `f602753e`). Reviewer returned REVISE; root accepted the revisions recorded here. All 13 apparent workflow conflicts are exact prior upstream blobs, so the plan is exact pinned-package sync with no hand-merge. Minimap JavaScript changes select full qualification, deferred until the shared test slot is available.



**Approvals:** Not required at this risk level.



**Exceptions:** —



**State:** Ready for review

<!-- agent-workflow:end -->



## Implementation update



- After the independent plan review, copied the exact committed packages to the two Agent Workflow mirrors, the mapped checker, and the existing Minimap skill directory. Root configuration and guidance remain unchanged.

- Fresh parity checks passed: 77/77 files per Agent Workflow mirror, mirrors identical, mapped checker exact, and Minimap 52/52. All changed paths are within the assigned consumer scope plus this Work Record. Selector-required full qualification completed after test-slot release; see the full qualification result below.



## Verification update



- Recorded governance rerun evidence is retained under `build/minimap-consumer-refresh-20261017/`, including source blob manifests, changed-path inputs, stdout/stderr and exit files. `tests/test_agent_workflow_ci.py`: 19 passed in 13.81s (exit 0). Checker compatibility smoke passed for legacy, valid and invalid Relationships and Elevated review reference/placeholder behavior. Node syntax checks passed for all 36 Minimap JS/MJS files. Import-linter returned 0 violations (exit 0). `git diff --check` passed and the changed-text scan found no trailing whitespace across 208 paths.

- Fresh Redline returned exit 1 (`RED`, “Red-zone files changed”) with zero boundary violations. The Workflow checker returned advisory exit 1 only: `scripts/agent-workflow-check.py` is red-zone and its `architecture-review` checkpoint is unsatisfied in shadow mode. No blocking predicate failed.

- The independent source review returned conditional GO. The selector-required full non-slow suite ran in a private CPython 3.13.14 environment after slot release. Attempt 1 stopped before collection because xdist workers raced to clean an explicit `--basetemp` that was also the process TEMP path. Attempt 2 reached 3,447 passes before a config test correctly exposed the globally supplied `PALLIUM_SQLITE_URL`; that override was removed for attempt 3. Attempt 3 recorded 2,735 passed, 2 skipped, and 1 xfailed before failing in `tests/test_claude_wake_durability.py::test_crashed_intent_lock_owner_allows_hook_publication_and_http_recovery[normal-portal]` at `process.wait(timeout=1)` immediately after `process.kill()` (test line 1469). The child had written its ready marker after acquiring and holding the lock; the HTTP 409 deadline check and the hook negative checks had passed. The logged `OSError` during injected `lock_setup` and `PermissionError` during expected held-lock refusal are stimuli/expected checks, not the failing assertion. A subsequent single passive run of that exact node passed and captured Popen PID 58428 as the private venv `Scripts/python.exe` with descendant PID 35776 as the base CPython image and PPID 58428 at the ready and pre-kill observations. Local Windows `subprocess.Popen.kill()` terminates the process represented by Popen's handle, demonstrating that this call targets the launcher process rather than the descendant lock owner. In the focused run `wait(timeout=1)` returned code 1 and the after-wait snapshot showed no descendant. This proves a process-custody mismatch but does not prove it caused the earlier full-suite timeout, which had no process snapshots and was not reproduced by the focused run. Detailed observation artifacts are `normal-portal-observation.{stdout,stderr,exit}.txt`, `normal-portal-process-tree.jsonl`, and `normal-portal-observation-inputs.json` under `build/minimap-consumer-refresh-20261017/`. Pre/post source snapshots match at `f602753e`; no installed changes, service operations, push, or PR were performed.



## Implementation



- Copied only committed package blobs from the two assigned pins into the existing consumer locations. The Agent Workflow package contains 77 files in each skill mirror; its mapped checker is synchronized to the root script. The Minimap skill contains 52 files. Package `.gitattributes` is included inside the Agent Workflow mirrors; no root template or configuration was installed.

- The initial apparent workflow customizations came from a stale baseline. The clean-context plan review confirmed they are prior upstream blobs; root accepted the review revisions and the exact pinned sync plan. Pallium root configuration, policy, CI, hooks, settings, guidance, and docs remain outside the diff.



## Evidence



- Reserved checkout: `feat/minimap-consumer-refresh`, fast-forwarded from clean `f062cc72` to fetched `origin/main` `f602753edf46d0b7a5d88bcd79725a143e311dba` before edits.

- Source pins: Agent Workflow `2e1233634263695dc7c4a41eaf5122825158b2e6`; Minimap `5072122c7353f7519c1aeda4fcac072682b55b26`.

- Parity: Agent Workflow 77/77 files per mirror, mirrors identical, mapped checker exact; Minimap 52/52 files exact. No out-of-scope path changed.

- Independent clean-context plan review: `/root/consumer_plan_review`, result delivered to root; REVISE findings resolved before implementation. Independent source review returned conditional GO. The later selector-required full run and its two unrelated test failures are recorded below.

- Retained check outputs, source pin manifests, and changed-path manifest are in `build/minimap-consumer-refresh-20261017/`. The independent source reviewer verified Git-normalized parity. Failed logger artifacts are preserved and excluded from evidence; the direct clean run logs are named `workflow-ci.clean.*`, `checker-smoke-v2.*`, `node-clean-*.{stdout,stderr,exit}.txt`, `import-linter.clean.*`, `redline-v2.*`, `workflow-check-v2.*`, and `diff-check.clean.*`.

- No installed changes, service operations, push, or PR were performed. A focused node and one selector-required full suite were run later; outcomes are recorded below.

- The repository selector was run from the assigned checkout with `--base origin/main`; it selected `full` and `python -m pytest tests/ -x -q`. The private locked environment at `C:\Users\I347041\AppData\Local\Temp\pcmr-q-20261017\v` matched all 66 pinned inventory packages and passed `uv pip check`. The final attempt used a short private HOME/profile/config/temp root, omitted the explicit shared pytest basetemp, and cleared inherited Pallium overrides and live bridge/socket variables. Its failure and corrected disposition are recorded above; no follow-up suite run was started.





## Follow-up qualification correction



- Plan: launch the lock-owner child directly with `sys._base_executable`, record its PID in the existing ready marker, and assert it equals `Popen.pid`. This corrects the demonstrated launcher/lock-owner custody split. The prior full-suite timeout cause remains unknown.

- Independent simplicity review approved the exact three-line test change. Independent encoded setup review also returned GO after checking the full caller journey, the unchanged readiness/deadlines/security and recovery oracles, and cleanup.

- The first focused invocation did not collect because the runner set `PYTEST_DISABLE_PLUGIN_AUTOLOAD=0`; pytest treats any set value as disabling plugin autoload, hiding installed xdist. Read-only inspection confirmed pytest 8.4.2, pytest-xdist 3.8.0, and its pytest entry point. With that variable absent, `python -m pytest --help` exited 0 and recognized `-n, --numprocesses`.

- After root released the test slot, the corrected command ran the exact normal-portal node with `-q -n 0`, the variable absent, and isolated HOME/config/temp paths. Result: 1 passed in 1.12s, exit 0. The synchronous invocation returned and `-n 0` created no xdist worker. Focused-node logs, exit, cwd, and source SHA256 `769192452B7B6903B0F9504926A209F4089A1D6094D99FFC8BF7CA0CFE0D964E` are retained under `build/minimap-consumer-refresh-20261017/custody-fix-normal-portal/`.

- This focused result does not explain the earlier full-suite timeout. A later selector-required full suite failed in two unrelated test nodes, recorded below. A later corrected short-path full suite completed successfully; see the full qualification result below.

## Candidate verification after custody review



- The fresh whole-change selector against origin/main exited 0 and selected the full lane: python -m pytest tests/ -x -q (86 changed paths). Selector stdout/stderr/exit are under build/minimap-consumer-refresh-20261017/candidate/.

- Fresh import-linter boundary check exited 0 and produced build/import-linter-report.json. Fresh Redline used the selector's changed-path manifest and matching numstat evidence, exited 1 with verdict RED (Red-zone files changed) because scripts/agent-workflow-check.py is red-zone. Its JSON and logs are retained under the same candidate evidence folder.

- The local Agent Workflow checker, run with the private interpreter selected process-locally, exited 1 advisory with no blocking predicates. The shadow architecture-review checkpoint remains unsatisfied for the red-zone checker; a second nonblocking advisory notes Work Record and code are in the same local commit. The first wrapper attempt exited 2 because Python was not selected; its preserved output is not represented as a successful check.

- Full qualification was subsequently completed after root released the shared test slot. See the terminal result below; the corrected private runner used a short isolated temp root with separate TEMP and pytest basetemp directories.




## Result review

Agent technical review: /root/encoded_setup_review (independent final candidate review; result delivered to root).
Reviewed revision: c48318945efcb47ab552baa96919735ed22f927e.
Verification adequacy: Adequate for the consumer-sync and custody-fix scope. The reviewer checked the full-suite stdout and exit, process-drain receipt, matching before/after hashes for all 86 selector paths, and the custody correction with its unchanged assertions and cleanup. Source parity remained 77/77 per Agent Workflow mirror and 52/52 for Minimap.
Limits: The review did not resolve the shadow architecture-review advisory or substitute for hosted checks. Later hosted results are recorded on PR #320.

## Full qualification result

- The earlier full attempt with longer temporary paths exited 2 after `-x` stopped on two failures: 3,726 passed, 2 skipped, 1 xfailed, 2 failed in 288.45s. The first failure was `tests/test_hook_common_parity.py::test_work_refs_stops_parent_walk_at_64[cc_common_parity]`; at line 999, `deep.mkdir()` failed with `FileNotFoundError [WinError 206]` when the nested xdist temporary path exceeded the Windows path-length limit. The second was `tests/test_health.py::test_production_factory_drains_claude_wake_thread_before_storage_close[transport]`; before shutdown/teardown, `write_json_atomic(registration_path, registration)` failed on its first `temporary.write_text(...)` with `FileNotFoundError [Errno 2]` under the test's `intents` directory. The first failure was explained by the overlong path; the second remains strongly consistent with path constraints but was not conclusively explained. Neither failure was treated as an application defect or fixed.
- Neither failing test file nor `app/claude_wake_binding.py` differs from `origin/main`; no vendor-refresh path touches those test files. Pre/post source SHA256 values match for all 86 selector paths and HEAD remained `c9c5cc29c82e570701214a94f693764e83396f6d`.
- The one corrected short-path full run, selected by the unchanged 86-path selector, exited 0: 7,169 passed, 34 skipped, 2 xfailed in 411.53s. It used the isolated private CPython 3.13.14 environment, short temp root `C:\Users\I347041\AppData\Local\Temp\f18`, `TEMP/TMP/TMPDIR` at `...\f18\t`, and pytest `--basetemp ...\f18\b`; these paths are distinct, plugin autoload remained enabled, and no package installation occurred. Pre/post hashes matched for all 86 selected paths; HEAD remained `c9c5cc29c82e570701214a94f693764e83396f6d`. A post-run exact-interpreter query found zero remaining owned processes. Logs, exit, before/after source manifests, and drain receipt are retained under `build/minimap-consumer-refresh-20261017/full-suite-shortpath-20261018/`. No further app test run, source fix, waiver, installed change, push, or PR has occurred.
