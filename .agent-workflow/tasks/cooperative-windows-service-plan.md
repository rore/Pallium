# Cooperative Windows service lifecycle — behavior review and implementation plan

<!-- agent-workflow:start -->
**Outcome:**
Produce one source-grounded implementation plan and behavior-review contract for cooperative Windows service lifecycle recovery, ready for separate technical and human behavior review.

**Target:**
Pallium Windows service lifecycle at published origin/main fd14a77d19713e878105a537de0dfee9735dc88e.

**Scope:**
Planning artifact only in this Work Record: inspect selected-base supervisor, child stop callbacks, launcher generators, restart wrapper and existing test harnesses; define containment, stop, settlement and bounded restoration behavior plus mocked regression coverage.

**Constraints:**
No product code, tests, live service actions or census, installed configuration changes, forced maintenance, push or PR. Preserve shared main and all existing owners' branches. Do not transplant installed callbacks into the selected source. No network, registry, daemon, backup or new orchestrator mechanism.

**Completion criteria:**
Record the exact isolated base and source findings, reconcile launcher-generator differences, specify minimum touched files and an implementation sequence, resolve spawn fencing/settlement/restoration review corrections, list mocked regression cases and remaining behavior decisions, and leave State returned to planning awaiting behavior review.

**Requirement baseline:**
{"source":"work-record-initial","outcome":"Produce one source-grounded implementation plan and behavior-review contract for cooperative Windows service lifecycle recovery, ready for separate technical and human behavior review.","scope":"Planning artifact only in this Work Record: inspect selected-base supervisor, child stop callbacks, launcher generators, restart wrapper and existing test harnesses; define containment, stop, settlement and bounded restoration behavior plus mocked regression coverage.","constraints":"No product code, tests, live service actions or census, installed configuration changes, forced maintenance, push or PR. Preserve shared main and all existing owners' branches. Do not transplant installed callbacks into the selected source. No network, registry, daemon, backup or new orchestrator mechanism.","completion_criteria":"Record the exact isolated base and source findings, reconcile launcher-generator differences, specify minimum touched files and an implementation sequence, resolve spawn fencing/settlement/restoration review corrections, list mocked regression cases and remaining behavior decisions, and leave State returned to planning awaiting behavior review."}

**Relationships:**
{"schema_version":1,"sources":null,"pull_requests":[]}

**Risk:** High

**Complexity:** Moderate

**Reason:**
Actual artifact is blue workflow metadata but non-exempt. Proposed lifecycle changes cross process ownership, crash policy and persistence-sensitive shutdown; judgment raises risk to High. Several cooperating components and Windows OS assumptions require expanded planning.

**Discovery:**
Selected base already contains startup-safe OwnedServer.request_exit and worker/cleaner/snapshot stop predicates. Supervisor drops failed API attempts and replaced roots, uses forced Windows tree termination, and only polls injected should_stop after helper startup. CLI and PowerShell installers generate different launch paths. See Source findings below; no live state inferred from these sources.

**Material assumptions:**
- Planning authorization is not behavior/implementation/installation approval. Required behavior decisions below remain open.
- Supported Windows permits pre-resume Job assignment and restricted local events. Unsupported permissions or host containment fail before resume with no uncontained fallback. Nested attempt Jobs are not part of the recommended minimum.
- Private generation metadata is only discovery material, not proof of process ownership, exit or clean drain. Missing/contradictory OS evidence makes the outcome unknown and forbids replacement.

**Plan:**
1. First implementation step: invoke the /agent-workflow skill to create or resume the Work Record and classify risk before any code edit; reconcile this proposed contract with the task owner's exact behavior approval and obtain clean-context technical review.
2. Add one narrow standard-library Win32 adapter and use the existing launcher role as observer: restricted per-generation stop event, suspended creation/Job assignment, retained process/Job handles, monotonic spawn gate, terminal receipt and observation. No new daemon, network endpoint, registry authority, backup mechanism or recovery orchestrator.
3. Wire supervisor attempts and existing child stop paths; replace Windows force/retry paths with the fail-closed settlement contract below. Preserve POSIX behavior. Update both launcher generators and their private fixtures, then CLI stop/start/restart/uninstall consumers and the supported PowerShell wrapper.
4. Add the mocked cases and private E2E journeys below using existing harnesses. Align operations documentation with the approved behavior; do not claim Task Scheduler or installed qualification from mocks.
5. Gate the unchanged start's actual startup mutations as specified below; removing wrapper initialize-wakes alone is insufficient. Run selected validation only after the implementation task receives its test allocation; complete independent result review. Unsupported containment, ownership ambiguity, new persistence/API change or changed behavior returns to planning.

**Verification plan:**
- Artifact contract -> source reads, complete changed-path inspection and governance checker only; no tests allocated or executed.
- Implementation outcomes -> matrix below, caller-surface private Windows E2E, existing app.run lifespan cleanup test, affected subsystem tests, then python scripts/test-plan.py --base origin/main and its required checks (application/mixed change requires full non-slow suite once).
- Protected contracts -> preserve tests/behavior_contracts/**; classify any edit and verify via existing PR test job.

**Plan review:**
Pending clean-context technical review and separate human behavior review. No implementation approval is implied by this planning assignment.

**Approvals:**
Planning-only scope accepted by parent assignment. Human implementation/behavior approval has not been supplied; do not fabricate an approval quote.

**Exceptions:**
—

**State:** Blocked or returned to planning
<!-- agent-workflow:end -->

## Implementation

- Initialized expanded record before source discovery on isolated branch `feat/cooperative-windows-service-plan` in `C:/Dev/rore/Pallium/build/cooperative-windows-service-plan`; sole source base `fd14a77d19713e878105a537de0dfee9735dc88e`. Shared checkout is dirty and was left untouched.
- Applicability: intended path `.agent-workflow/tasks/cooperative-windows-service-plan.md` is a Work Record, expressly ineligible for documentation-only exemption; normal workflow applies. No roadmap state change is assigned.
- Completed source discovery and the planning-only contract/matrix. Last committed initial-record revision before this artifact update: `f4a708dc`; final handoff reports the committed artifact revision. No implementation has begun.

## Evidence

- Local `refs/remotes/origin/main` and `git merge-base HEAD origin/main` both equal selected base. No fetch performed.
- No application tests, service calls, process census or installed-file reads performed.
- Governance attempt: expanded shape, state, baseline and relationships pass; checker correctly blocks pending High technical/human review. Reporter could not produce a verdict because selected base requires absent `build/import-linter-report.json`; no synthetic pass, policy override or unallocated backend/test run was substituted. Full governance validation remains pending; manual applicability selects non-exempt Work Record.
- The only changed path is this Work Record; `git diff --check` passed. Ignored `build/planning-*` files retain local checker output/path evidence, not product assets.

## Source findings (all code references are at fd14a77d)

| Surface | Evidence and consequence |
|---|---|
| `app/supervisor.py:410`, `:476`, `:727` | API startup loops up to five times, kills an alive unverified process, returns only the successful root; slot replacement overwrites its old process. Finally sees current slots only and uses per-child waits plus forced escalation. A stop flag is not a cooperative drain or complete ownership ledger. Health recovery also force-kills API. |
| `app/run.py:26` | Existing OwnedServer.request_exit latches requests during startup and applies should_exit on entering main_loop; owned_factory uses loop.call_soon_threadsafe. Reuse this exact callback for the native event. Do not transplant installed code or set should_exit early (Uvicorn can skip lifespan cleanup). |
| `app/worker.py:42`, `app/cleaner.py:33`, `app/snapshot.py:193` | Existing should_stop checks between processing/retention/snapshot operations. Keep work atomicity and error handling; interrupt idle/backoff waits, not an active provider/SQLite/native operation. Worker boundary between no item and thread rebuild also needs the predicate before claiming a second operation. `app/snapshot_worker.py` does not exist. |
| `app/processor.py:24`, `app/signal_context.py:14` | Processor currently forwards config/sleep only; forward stop predicate without changing defaults for other callers. Shared signal context can combine signal state and generation event and provide stop-aware waits; retain injectable sleeps for tests and non-Windows callers. |
| `app/cli/service.py:322`, `:401`, `:898`, `:1002` | CLI generator writes UTF-16 `home/run/pallium_launcher.vbs`, calls current Python with `-m app.run service run --home`, waits and propagates status, sets no VBS cwd and no task cwd. `_start_windows` discards its WScript Popen; `_cmd_stop_impl` attempts HTTP then force kill; restart ignores a false stop result. Uninstall also consumes stop and must refuse removal when settlement is unproved. |
| `scripts/install-service.ps1:74` | Deprecated generator writes `~/.pallium/service_launcher.py` with explicit SQLite/vector env and sys.path, then `run(["all", ...])`; UTF-16 VBS launches pythonw, waits and returns status; task cwd is source RepoRoot. These are configuration/entrypoint differences, not interchangeable templates. |
| Supplied installed evidence, not inspected here | Actual `C:/Users/I347041/.pallium/service_launcher.vbs` uses CurrentDirectory `C:/Dev/rore/Pallium-installed`, stable `.venv` Python and direct `-m app.run service run --port 19836 --home ...`, waits/propagates status; task WorkingDirectory points to development. Thus it is neither generator verbatim. VBS CurrentDirectory wins for its child; task cwd still matters for preflight. Never regenerate it or silently use development cwd from this plan. |
| `scripts/restart-service.ps1:183`, `:211`, `:311`; `docs/context/operations.md:347` | Wrapper stops task, force-sweeps listener/PID/signature roots, then starts task. Docs say it "drains" although implementation is forced; docs also explicitly require separate approved launcher regeneration. Proposed cooperative path must reject legacy/noncontained launchers before stopping them, identify exact approved migration, and retain installed metadata compatibility for read-only/preflight parsing. No existing Job adapter was found in app/tests/scripts. |

The selected base equals local origin/main and already contains the needed API callback and launcher-lifetime tests. It is suitable; no cherry-pick or alternate base is needed. No canonical roadmap status is changed or feature completion claimed. The relevant design file `docs/designs/refactor-service-decomposition.md` concerns core/service decomposition, not this lifecycle mechanism.

## Proposed behavior contract — review required

1. **Ownership before execution.** Existing hidden WScript launcher waits for a small Python observer in the existing service launch path. Observer owns one generation Job and restricted manual-reset stop event, acquires the single-generation launch exclusion, creates supervisor suspended, assigns it before resume, and propagates generation identity/event access. No breakaway is allowed; trampolines, API, workers and later descendants inherit containment. No child runs if creation/assignment/event/authority setup is incomplete. A partial suspended creation remains tracked until conclusively disposed without executing application code.
2. **One-way stop gate and complete ledger.** Any signal, controller request, stop predicate, fatal startup/recovery failure or deadline closes a monotonic gate. A same-generation restricted local mutex serializes controller event signaling, supervisor gate closure and each create/assign/resume admission; check latched stop again immediately before resume. Once closed it never reopens, including during token generation, readiness, retry sleep, helper startup and health recovery. A suspended creation racing close is retained and never resumed. Register every created root before readiness or callbacks, retain handles/exit results through all attempts and slot swaps, and retain every attempt's descendant ownership until terminal observation. Current slots are only scheduling pointers. An abandoned mutex or unverified admission owner fails closed.
3. **Cooperative work boundary.** Event signal reaches supervisor and every child without HTTP. Worker, cleaner and snapshot reuse their own should_stop/between-operation checks; processor forwards the predicate. Idle/poll/backoff waits wake on event. In-flight operations finish via existing cleanup; no new work starts after observing stop. API schedules the selected-base OwnedServer.request_exit on its loop, including a request before the loop is captured or while startup is running; repeated requests are idempotent. Keep initialization/lifespan cleanup, native listeners and tracked storage operations intact.
4. **One deadline, no escalation.** One monotonic absolute operation deadline covers stop request, waits and settlement verification; compute remaining time for each wait, never N children times a fresh timeout. Existing independent per-attempt startup budgets remain clipped by their enclosing operation budget. Timeout, permission failure, contradictory identity or unknown state returns an explicit non-success result: no taskkill, TerminateProcess, scheduled-task stop, Job close-to-kill, replacement or restoration. Observer remains alive and retains Job/event/process handles after a controller times out or exits; it can outlive that caller indefinitely while children drain. Do not run a shutdown snapshot against unsettled children or begin a new unbounded operation after the deadline; existing snapshot policy needs the decision below.
5. **Trustworthy terminal observation.** Private per-generation receipt discovery contains schema version, random generation ID, exact launch/config identity, observer and WScript identity (PID plus creation identity), supervisor identity and exit status, each retained attempt's terminal result, Job-empty observation, and terminal outcome. Observer atomically publishes the restricted receipt only after same-generation Job emptiness and known terminal observations. Controller opens/retains verified OS process handles before acting, validates receipt against generation/launch identities, and waits for the actual observer process **and actual WScript launcher** to exit; known Task Scheduler action settlement is additionally required for task-started generations. A receipt, PID disappearance, stopped task, empty port or empty Job alone is insufficient. Missing receipt, access denial, PID reuse, stale generation, result conflict, unfinished launcher or uncertain observation yields unknown.
6. **Outcome is separate from nonoverlap.** Clean means requested cooperative exit, all required known terminal results successful, Job empty, terminal receipt valid, observer exited, launcher/task settled. Known nonzero/crash is failed-but-settled, never clean. Empty Job proves only no remaining contained process; it does not prove ACK, commit, completed application work or successful cleanup. Unknown terminal status stays unknown even when nonoverlap is known. Never promise message ACK or transaction completion from a process exit.
7. **Bounded restoration.** Normal restart starts its intended new generation only after verified clean old-generation settlement. If that start fails, permit at most **one** same-config restoration start and spend that allowance atomically. Eligibility is either (a) definitive failure before any application launch/resume, with no live observer/launcher or suspended handle left, or (b) the failed new generation has known failed terminal results, empty Job and verified observer/launcher/task settlement. A start exception is not proof of (a). Running-but-unready, readiness timeout, lost controller, unknown outcome and still-running old/new observer forbid retry. Restoration preserves exact interpreter, cwd, home, port, args and environment/config identity; it is a start retry, not a code/config rollback. A successful restoration is reported as recovery with the original failure, not ordinary restart success.
8. **Crash policy is an explicit behavior choice.** Proposed generation Job uses kill-on-close for unexpected observer loss to prevent orphan trees; that is abrupt termination and can interrupt writes. It must never trigger on an ordinary controller timeout/exit, and no implementation may assume its approval. If declined, retain no-kill crash behavior and report observer loss/possible survivors unknown until separately authorized recovery; no automatic replacement. Scheduler's current 3x automatic restart must not bypass this contract or the one restoration allowance; its exact revised policy must be approved.

Attempt retries need descendant settlement as well as a root exit. Recommended minimum: when an attempt fails and its descendants cannot independently be proved settled, close retry admission and cooperatively drain the entire generation. The one generation Job then proves nonoverlap. This explicitly changes Windows five-attempt startup and per-slot automatic retry behavior; it must be approved. Subordinate per-attempt Jobs could preserve more healthy-slot retry behavior, but add nested-Job compatibility and handle complexity and are **an unaccepted alternative, not necessary for the required no-unknown-overlap guarantee**. Never substitute root-only poll success for descendant settlement.

Receipt protection is same-user private runtime-directory ACL plus a generation-specific event DACL limited to the owning user and required OS account, with minimal query/signal rights; use random names, not predictable PID-only names. Metadata never confers authority. Receipt publication, process identity verification and actual-exit observation form one contract; stale/forged/unreadable evidence cannot advance it. No machine-wide process census is required.

## Startup effects and same-config start gate

The controlled restart/restoration start is allowed to update its private runtime PID/token/receipt files and logs, acquire/release ownership locks, and resume already configured durable processing, lease expiry/reclaim, current-generation fencing and reconciler work. It does not install profiles/integrations, expand access, import legacy authority, create a missing durable store or rewind a database. Existing runtime recovery can write existing stores and dispatch already-authorized pending work; do not label it read-only or delete it just because its name contains recovery/initialize.

| Selected-base startup path | Actual effect; controlled-start rule |
|---|---|
| `app/codex_wake_lifecycle.py:69`, invoked by `app/cli/service.py:_cmd_run` and `app/run.py:run` | Existing valid SQLite wake marker: read-only marker validation and return. Genuinely absent main/relay/legacy paths: under owner lock, constructs SQLite storage/schema and initializes durable wake authority. Existing files without marker: refuses and requests explicit offline upgrade. Controlled restart requires the existing expected pair and valid marker first; absent/mismatched authority fails before stop/start and never becomes implicit fresh setup. Do not remove validation or bypass its lock. |
| Wrapper `service initialize-wakes`, lifecycle `initialize_codex_wakes_offline`, `core/codex_wake.py:102`, `storage/sqlite_relay.py:727` | Explicit offline operation proves old owner stopped, can load legacy reservations, writes reservation rows and generation high-water authority (existing marker is idempotent). Remove it from ordinary restart/restoration sequence; retain the supported separately authorized offline operation and its drain/owner-lock checks. This is persistent setup/import, distinct from runtime fence reconciliation. |
| `app/supervisor.py:508`, `app/snapshot.py:107` | Configured startup restore skips a complete existing main/relay pair, rejects a partial pair, and can repopulate an absent pair from snapshots with file replacement/WAL cleanup. Recovery start gate requires intact live pair; no snapshot substitution, deletion, schema repair, rewind or restore-on-start as a fallback. Preserve standalone restore behavior pending its own approval; do not introduce new DB recovery. Revalidate gate inside generation launch exclusion before resume. |
| `app/main.py:389`, `app/dependencies.py:676` | Existing lifespan resumes interrupted vector-index swap/rebuild, reconciles registrations, starts wake reconciler; persisted wake recovery rechecks candidates/current fences and dispatches existing authorized pending work. These are ordinary durable/runtime recovery, not permission to enroll a new profile. Preserve current scope, lease/generation/CAS checks and shutdown ownership. No new recovery hook or altered Relay state machine is proposed. |

Before stopping, validate same effective interpreter/cwd/home/port/config/environment and existing live-store authority read-only; repeat ownership/identity checks inside launch exclusion. Configuration drift, missing/partial stores, legacy authority, new credentials, access expansion or installation need a separately described approved operation. Unchanged approved runtime reconciliation remains permitted after launch, including its existing durable writes and scoped wake dispatch. Restore eligibility never authorizes changing these gates. Add mocked cases for existing marker, fresh/partial/missing/legacy stores, import refusal, unchanged lease/fence recovery, configuration drift, no database rewinds and no profile/install/access mutation.

## Minimum implementation reach

| Files | Minimum change |
|---|---|
| New `app/windows_service.py` | Narrow Win32 Job/event/process/identity adapter using standard library ctypes; observer lifecycle and receipt protocol stay specific to existing service launch, no dependency or generic framework. If clean separation needs a second production module, justify it in review first. |
| `app/cli/service.py` | Existing service launcher/observer entrypoint, exact launch metadata, controlled-start read-only authority gates and controller OS-handle settlement; route Windows stop/restart/start/uninstall through it, retain observer/WScript ownership and gate every new launch. No network shutdown or implicit setup. |
| `app/supervisor.py` | Single spawn gateway/ledger and stop event; all startup/helper/retry/recovery paths; cooperative finalization and bounded terminal summary, no Windows kill path. |
| `app/signal_context.py`, `app/processor.py`, `app/worker.py`, `app/cleaner.py`, `app/snapshot.py` | Shared event predicate and stop-aware idle waits; processor forwarding; only missing operation-boundary fences. Reuse current functions and keep non-Windows/injected behavior. |
| `app/run.py` | Connect event to existing OwnedServer request_exit on loop; preserve pre-main-loop latch and actual lifespan cleanup. |
| `scripts/restart-service.ps1`, `scripts/install-service.ps1` | Wrapper delegates only approved contained lifecycle and fails closed on legacy launcher; both generator paths use the same observer contract. Keep UTF-16/hidden wait/status, exact cwd, port, home and legacy env differences explicit. Existing installed files are untouched without separate migration approval. |
| Existing tests below; `docs/context/operations.md` | Extend harnesses/fixtures and private E2E; document cooperative/unknown/crash behavior and supported migration. No API/schema/model/core/storage change, exports, dependency, global config, or roadmap edit is needed. |

Caller audit found run_worker also used by `app/live_exploratory_runner.py`; keep all new callback parameters optional and preserve its injected behavior. Existing tests in `tests/test_async_worker.py` assume forced supervisor cleanup; revise only Windows expectations to approved behavior, preserving POSIX semantics and coverage. Existing launcher tests assert no eager `app.cli.service`/`app.supervisor` import inside private stubs; adapt fixtures to the observer entrypoint without weakening cold-launch isolation.

Generator reconciliation: CLI retains its service-run/home semantics. Deprecated PowerShell generator must retain its explicit SQLite/vector environment and run(all) behavior inside the observer initially, or obtain exact approval to migrate to service-run (which additionally loads home config/.env and credential-dependent processors). Do not silently normalize them. Both record effective child cwd explicitly; actual installed mixed metadata is tested as a fixture and rejected for cooperative operation until separately regenerated with a reviewed rollback.

## Mocked regression matrix and private E2E plan

| Existing harness | Required observable assertions |
|---|---|
| `tests/test_supervisor.py` fake processes/time | Stop before first spawn; during nonce/cwd/env construction; between create/assign/resume; readiness success racing stop; retry sleep; each processor/cleaner/snapshot spawn; runtime crash and health-retry path. Spawn count stays frozen after gate close; no force calls; every initial/failed/replaced attempt remains in terminal ledger, including chains longer than two and create/assignment exceptions. |
| `tests/test_supervisor.py`, `tests/test_supervisor_kill_tree.py` | Zero/one/many helpers; restart budget boundaries; alive-unready vs known root crash with live descendants; Job empty vs not empty/unknown. Unproved attempt-descendant settlement closes admission and drains generation. Windows path never invokes legacy kill helper; existing POSIX kill tests remain. |
| `tests/test_async_worker.py`, `tests/test_runtime_logging.py`, `tests/test_snapshot.py`, `tests/test_snapshot_failure.py` | Stop before operation, during blocking operation and between operation classes; release first operation, verify no second claim/provider/retention/snapshot action; idle/backoff event wake; existing transient/nontransient errors retained; disabled snapshots and full create/mutate/stop/dispose lifetime. |
| `tests/test_app_run.py::test_owned_server_terminal_exit_runs_actual_lifespan_cleanup` | Drive native-event exit through same callback before loop capture, during startup, during serving, repeated signal and failure. Assert actual lifespan finalizers, listener exit, tracked-operation closure and token cleanup via existing read paths; no early should_exit bypass. |
| `tests/test_service.py`, `tests/test_restart_service.py` mocked PowerShell call log | Wrong generation/event/ACL, stale receipt, PID reuse, permission denial, malformed/partial receipt, supervisor exit with descendant alive, Job empty with unknown/nonzero result, observer still alive, WScript still alive, task still running. No launch/force/removal/success on uncertainty. Same single fake deadline across 0/1/many children; controller timeout/exit leaves observer holding Job. Unicode/spaces, exact cwd, home, port min/max/invalid, interpreter trampolines and other homes cannot cross-target. |
| Same controller harnesses | Start fails definitely before launch => one restoration; throws after launch => no restoration without terminal settlement; known failed new generation with full settlement => one restoration; running-unready/timeout/unknown => zero; restoration itself fails => no third start. Assert exact same config and ordered terminal evidence before each start, plus failure vs recovered output. Concurrent controllers share one launch/restoration allowance. |
| `tests/test_service_launcher_lifecycle.py` private Script Host harness | Both generated forms, supplied mixed-installed fixture, Unicode BOM and exact cwd, hidden window, real wait and 0/nonzero status propagation. Mock OS adapter verifies create-suspended → assign → resume order, restricted event, no breakaway and handle retention after controller loss. Do not claim these mocks qualify real Job behavior. |
| Extend same private launcher harness with actual temporary caller-surface Windows E2E | Isolated home, unregistered task façade, disposable stubs/SQLite and private ephemeral port; start via generated VBS, make descendant chain >2, request stop through public CLI/wrapper surface, observe receipt plus OS observer/WScript exit, assert durable state via normal HTTP/list/read path and no replacement before settlement. Include hung operation, crash/nonzero, concurrent start/stop, controller exit, containment-assignment refusal and full create→mutate→stop→dispose. Mark polling tests slow. Actual OS containment and any kill-on-close crash case require separately authorized isolated test allocation; no installed service/task touched. |

Mocks prove control decisions; actual private OS E2E must prove containment and process settlement. Neither qualifies the registered Task Scheduler instance. No tests are run by this planning task.

## Checkpoint and missing behavior decisions

Architecture/security/operations behavior review is required by judgment (existing proposed runtime paths are gray/blue in current Redline, not falsely reported as policy-red). There is no proposed API/schema edit or boundary import violation. High risk reflects process/persistence consequences, not Work Record file classification.

- Approve exact before/after Windows contract: forced stop/retry becomes cooperative fail-closed; timeout can leave a draining generation alive indefinitely and blocks availability/replacement. Select the finite whole-operation deadline; readiness and restoration consume that same remaining budget, with no fresh per-phase allowance.
- Decide kill-on-close on unexpected observer death, and coordinate Task Scheduler restart-on-failure so scheduler cannot bypass settlement or exceed one restoration. This is abrupt crash behavior, distinct from ordinary stop.
- Approve minimal whole-generation drain on failed attempts with unproved descendants, changing current Windows per-slot/startup retry semantics. Nested attempt Jobs are optional alternative complexity, not a prerequisite.
- Decide the existing supervisor final snapshot policy within the same deadline. Recommended: no additional final snapshot after stop; periodic snapshot operation already in flight completes. This removes current best-effort final snapshot and requires explicit behavior approval; no backup redesign.
- Decide whether deprecated PowerShell-generated run(all) stays supported with its old env semantics or receives a separately reviewed service-run migration. Actual installed launcher/task regeneration, backups/rollback, normal launch/update checks and any live stop/restart remain separately scoped environment work.

No behavior decision above is approved by the broader planning acceptance. Next action: parent obtains clean-context technical review of this record and presents the concrete open choices to the human; only then may an implementation task advance.

## Result review

Artifact complete; parent clean-context technical review and human behavior review remain pending. State deliberately remains returned to planning, not implementation-ready. This worktree remains owned by the planning task for concrete review/revision; do not retire it while that use remains. No push or PR is requested.
