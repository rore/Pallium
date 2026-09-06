# Work Record - Linux service lifecycle qualification

Task branch: `codex/linux-service-lifecycle`
Roadmap item: validation-only unless an observed defect changes a documented product claim

<!-- agent-workflow:start -->
**Outcome:**
Pallium's Linux user-service lifecycle is qualified on a clean Ubuntu 24.04 WSL2 environment with reproducible evidence for install, start, stop, restart, crash recovery, WSL restart, and uninstall. Any observed defect is fixed at the shared lifecycle seam with caller-surface E2E coverage; no behavior is inferred from synthetic tests alone.

**Target:**
The isolated Linux clone at `/home/i347041/code/pallium-linux-validation`, its WSL-only Python environment, disposable Pallium home, `systemd --user` unit, and isolated port `29836`.

**Scope:**
First validate existing behavior without source changes. If and only if a reproducible defect is found, the smallest permitted change may touch `app/cli/service.py`, the three `scripts/*service.sh` wrappers, focused tests under `tests/`, and Linux operations/getting-started documentation under `docs/`. This branch does not include Relay wake implementation or integration setup changes. The wrapper scope was clarified after discovery showed all three shipped wrappers diverged from the canonical CLI; this did not change the risk classification.

**Constraints:**
Windows is immutable for this task: do not install, uninstall, restart, stop, reconfigure, or invoke the Windows Pallium service, Codex, or Claude. Do not use Windows agent homes, Windows npm globals, `/mnt/c` config paths, or shared Git metadata. Recheck captured Windows executable/config/task/service fingerprints before and after each material Linux setup stage and stop on unexpected drift. Keep Linux state under `/home/i347041`, use port `29836`, and never run the Windows `codex` shim visible through WSL PATH. Snapshot any pre-existing Linux unit before mutation and restore it on cleanup; never fall back to a Windows service or direct daemon. Every lifecycle command must use the same isolated `--home`; the single per-user unit must never silently retarget from home A to home B. Preserve service data by default. Any `--remove-data` path must prove managed ownership or lie within the controlled disposable root, and refusal must leave an external sentinel untouched; never recursively delete an arbitrary `--home`. Never run global `wsl --shutdown`; terminate only `Ubuntu-24.04`, and only after proving no unrelated workload or unit is active, otherwise request permission.

**Completion criteria:**
1. Baseline Linux tests and environment facts are recorded from the isolated clone.
2. A WSL/systemd-user-manager preflight fails actionably if the user bus is unavailable and records the linger policy rather than silently changing it.
3. Install creates a correct user unit using the exact Linux-native executable, home, and port; `/health`, `/status`, and `/debug/queue/health` are ready.
4. Systemd is the sole Linux lifecycle authority: install starts once; start, stop, restart, and uninstall check every `systemctl --user` result; stop closes the service cgroup/process tree and port.
5. Linux status combines `LoadState`/`ActiveState` with application readiness instead of trusting a PID file.
6. Install A then install B cannot silently retarget the one per-user unit: it fails without changing A, or requires an explicit replace action.
7. The public CLI lifecycle is canonical; shipped shell wrappers delegate to it and verify the same three readiness surfaces, or are explicitly removed/deprecated with docs.
8. Unexpected process exit follows the declared `systemd` recovery policy, and named-distro WSL terminate/start behavior is observed only after the unrelated-workload safety preflight.
9. Missing unit, failed manager command, stale PID, occupied port, custom port, custom home, path-with-spaces, Unicode, repeat operations, and uninstall lifecycle behavior are exercised through caller-visible surfaces.
10. Uninstall removes only the exact Linux user unit and preserves data by default. `--remove-data` rejects an unmanaged/unsafe home and leaves a sentinel untouched; repeated cleanup is safe.
11. Caller-surface E2E invokes `pallium service install|status|restart|uninstall` with the same isolated `--home` and verifies systemd state, cgroup/port absence after stop, plus all three application health surfaces.
12. Any fix has focused regression coverage plus required E2E coverage, full relevant Linux tests pass, documentation makes only WSL-qualified claims, and final Windows fingerprints match the safety baseline.

**Risk:**
Elevated

**Complexity:**
Moderate

**Reason:**
`app/cli/service.py` is gray-zone guarded runtime/process code and `app/**` is watched. No redline checkpoint, API/schema/security/config surface, or dependency boundary is in scope, but incorrect lifecycle behavior can leave stale processes or report false readiness.

**Discovery:**
The isolated clone is clean at `310284551b40263d00f5b131067315225beda793` on `codex/linux-service-lifecycle`. Ubuntu 24.04 WSL2 runs `systemd` as PID 1 and has a working user manager. No Linux Pallium unit exists and port `29836` is free. Existing Linux service helpers invoke `systemctl --user`; install/start/uninstall calls require runtime qualification because return codes appear unchecked. `_install_linux` uses `enable --now` and the install caller starts again. Linux restart first uses generic process shutdown/SIGKILL and then asks systemd to start, creating competing lifecycle authorities. `scripts/restart-service.sh` restarts the unit but does not verify application health. Shell install runs `app.run all` while the CLI unit runs `pallium service run`; the supported canonical path must be established from behavior and docs. Linux CI exercises Python tests, but not an installed WSL user-service lifecycle. Redline review classified intended files GRAY overall, watch on `app/cli/service.py`, no checkpoint or boundary risk.

**Material assumptions:**
- A1: WSL's user manager behaves closely enough to qualify Linux `systemd --user` integration. Disproof: service behavior depends on WSL-specific startup/session state; action: record WSL-only evidence and do not generalize to all Linux distributions.
- A2: Existing lifecycle behavior may already be correct despite competing lifecycle paths. Disproof: a caller reports success after a failed `systemctl` action, starts twice, leaves a cgroup/process/port behind, or returns before health readiness; action: capture the exact reproduction, then make systemd the sole Linux lifecycle authority at the shared seam.
- A3: Service qualification does not require native Linux Codex or Claude. Disproof: a service lifecycle assertion depends on integration setup; action: defer it to the separate Relay-wake branch rather than expanding this slice.
- A4: Windows fingerprints remain stable while WSL-only work runs. Disproof: any monitored Windows file, scheduled task, executable resolution, or service health changes unexpectedly; action: stop immediately and report the drift before continuing.
- A5: Linger need not be changed for WSL qualification. Disproof: restart-after-named-distro-termination cannot be tested without it; action: report the limitation and request explicit permission before any `loginctl enable-linger` state change.
- A6: The public CLI lifecycle and its generated unit are the canonical Linux path. Disproof: repository docs designate a shell-generated unit as canonical; action: stop and reconcile the plan before implementation.
- A7: The single per-user unit has no safe implicit multi-home semantics. Disproof: an existing explicit replacement/ownership contract is found; action: test and preserve that contract rather than inventing another.

**Plan:**
1. Invoke the `/agent-workflow` skill to create the Work Record and classify risk, before any code edit.
2. Complete the required clean-context plan review and fold in findings before changing source.
3. Normalize and revalidate Windows safety fingerprints, then preflight Linux `systemd --user`, user bus, linger status, absence/snapshot of an existing unit, native executable paths, free port, and unrelated workloads in the named distro.
4. Create only a Linux-native virtual environment inside the isolated clone and run focused baseline tests.
5. Designate the public `pallium service` lifecycle plus its generated unit as the canonical Linux path. The unit must preserve the exact native executable, home, port, spaces, and Unicode. Shipped wrappers must delegate to this path and verify all three endpoints, or be removed/deprecated explicitly.
6. Install and exercise the public CLI with one disposable Linux home on port `29836`, recording unit content, `systemctl` state/return codes, cgroup/process tree, endpoints, logs, and start count. Test install A then B without allowing silent retarget.
7. Exercise failure and edge cases without editing code. If an observable contract fails, stop, capture the exact reproduction, trace every caller of the shared seam, then implement the smallest root-cause fix. Linux stop/restart/uninstall must use checked systemd operations; status must combine manager state with readiness.
8. Add focused regression checks plus caller-surface E2E for every changed contract, including safe `--remove-data` refusal, install/status/restart/uninstall, cgroup/port cleanup, and all three health surfaces. Do not use mocks as the E2E witness.
9. Run focused and full relevant Linux verification, validate data-preserving cleanup/idempotence, update only evidence-backed operations documentation, and run workflow/redline checks. Terminate only the named distro, never all WSL, and only if no unrelated work is active.
10. Recheck Windows fingerprints and provide the evidence/result review. Relay wake remains a separate branch and work record.

**Verification plan:**
Criteria 1-12 → use Linux-native commands with a sanitized PATH and explicit WSL distro. Before mutation, assert `systemd` PID 1, `systemctl --user`/user bus availability, linger state, exact unit path, no prior unit (or snapshot/restore it), and no unrelated workload before any named-distro termination. Invoke every installed `pallium service` E2E command with the same isolated `--home`; inspect and verify the unit with `systemd-analyze --user verify`; assert every manager-command exit and relevant stderr; combine `LoadState`/`ActiveState` with `/health`, `/status`, and `/debug/queue/health` readiness on `127.0.0.1:29836`, including `embedding_provider_ok`; record MainPID/cgroup and port ownership before and after transitions. Test missing unit, manager error, stale PID, occupied/custom port, install A then B, safe quoting for spaces/Unicode, restart/crash recovery, repeated operations, preserved data after normal uninstall, and refusal of unmanaged `--remove-data` with an untouched sentinel. Assert wrappers delegate to the canonical CLI/unit path and verify the three endpoints, or remove/deprecate them with docs. Run focused tests plus repository-required suite/checkers for any changed surface. Compare Windows file/task/executable fingerprints and the three Windows service endpoints with the captured baseline before/after material stages.

**Plan review:**
Clean-context review: APPROVE-WITH-CHANGES. Required revisions were folded in: explicit one-unit/cross-home behavior, contained `--remove-data`, named-distro-only WSL restart with unrelated-workload stop condition, checked systemd-owned Linux status/stop/restart/uninstall semantics, and one canonical CLI/unit path for shipped wrappers.

**Approvals:**
Not required at this risk level. User explicitly authorized starting after reviewing the isolation and validation plan.

**Exceptions:**
-

**State:** Ready for review
<!-- agent-workflow:end -->

## Discovery

See the marker block. Append only evidence that changes a material assumption, scope, or plan.

## Plan review

Clean-context review `/root/linux_service_plan_rereview`: APPROVE-WITH-CHANGES. P1/P2 findings were incorporated into the marker-block constraints, completion criteria, assumptions, plan, and verification plan before any install or source edit.

## Implementation

Validated the unmodified lifecycle first and reproduced two shared-seam defects: unchecked/competing systemd operations left a child cgroup in `deactivating` and made restart block for roughly 95 seconds, while the shell wrappers installed a different daemon command and were not executable. Updated the canonical CLI so Linux lifecycle is checked and owned by systemd, added `start`, persisted the custom port, verified all three readiness endpoints, safely quoted units, refused cross-home retargeting, and contained `--remove-data` behind a managed-home marker. Reduced all three shell scripts to executable CLI delegates, then added focused and real user-service E2E coverage plus WSL-qualified docs. Result review then found and prompted fixes for Linux status reliance on PID files, default-home deletion ownership, cgroup-empty stop proof, and incomplete wrapper E2E; all were corrected at the same shared seam and caller surface.

## Evidence

- Isolated branch/base: `codex/linux-service-lifecycle` at `310284551b40263d00f5b131067315225beda793`; Ubuntu 24.04 WSL2, systemd PID 1, working user manager, linger unchanged (`no`).
- Real caller-surface E2E covered install/status/restart/wrapper restart, cross-home refusal, stop/start, crash recovery, preserved-data uninstall, unmanaged-delete refusal, custom-home delete refusal, spaces and Unicode: `1 passed, 2 warnings in 95.31s`.
- Focused service suite: `35 passed, 8 skipped, 2 warnings in 0.23s`.
- Full Linux suite: `4314 passed, 72 skipped, 2 xfailed`; three failures came from the disposable local TOML BOM and passed after removing that local setup. Six unrelated OpenCode structural E2E cases require native Linux `node`, which is not installed.
- Import linter, `bash -n` for all wrappers, `systemd-analyze --user verify`, and `git diff --check` passed.
- Manual evidence: one install start (`NRestarts=0`); stop inactive in 6s with no main PID/cgroup/port owner; restart in 12s with new PID and custom port preserved; occupied-port failure in 31s; crash recovery with new PID and healthy endpoints; enabled unit recovered after terminating only `Ubuntu-24.04`; exact unit and disposable homes removed afterward.
- Final Windows read-only gate: Codex/Claude executable resolution, static hook/config hashes, Pallium scheduled-task hash, `/health`, `/status`, and `/debug/queue/health` match/are healthy. Runtime-owned `~/.claude.json` changed at 10:30:32Z while seven Windows Claude processes were active; length stayed 22648 bytes. No Windows service or agent lifecycle command was run.

## Result review

`/root/linux_service_plan_rereview`: APPROVE-WITH-CHANGES after all technical blockers were addressed. Final review confirmed Linux status uses systemd MainPID, stop proves an empty cgroup, wrappers share the canonical CLI and real E2E, cross-home retargeting is refused, and recursive deletion is limited to a marked default home. Windows runtime-metadata drift was stopped and attributed to active Claude processes; static integration and service safety surfaces remained exact. Required closeout was only this record update and removal of the disposable virtual environment. Risk remains Elevated; no redline checkpoint or boundary violation was triggered.
