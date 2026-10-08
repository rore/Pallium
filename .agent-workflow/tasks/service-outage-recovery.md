# Service outage recovery

<!-- agent-workflow:start -->
**Outcome:** Explain the service outage and correct demonstrated supervision or launcher recovery defects without changing the user's live installation.

**Target:** Pallium local service supervision and Windows launcher generation.

**Scope:** Isolated investigation of AcceptEx error handling, API startup/restart budgets, supervisor terminal status and generated Windows launcher status propagation; minimal regression-backed corrections and focused caller-surface coverage; reviewed handoff to pallium manager.

**Constraints:** Pallium manager exclusively owns live restoration, health checks and installed operations. No installed edits, service operations, real database tests, configuration changes, native enrollment or parallel full qualification. Preserve the frozen Relay projection component and incident evidence. No speculative timeout-only patch, new dependency, weakened protected contract or inferred historical cause.

**Completion criteria:** Established source defects and unresolved incident causes are distinguished; each implemented correction has focused caller-surface lifecycle/failure coverage and independent smart plan/result review; coordinated whole-change validation, workflow/risk checks and PR/merge gates remain explicit; manager receives exact revision, evidence and any separately required live rollout scope.

**Requirement baseline:**
{"source":"work-record-initial","outcome":"Explain the service outage and correct demonstrated supervision or launcher recovery defects without changing the user's live installation.","scope":"Isolated investigation of AcceptEx error handling, API startup/restart budgets, supervisor terminal status and generated Windows launcher status propagation; minimal regression-backed corrections and focused caller-surface coverage; reviewed handoff to pallium manager.","constraints":"Pallium manager exclusively owns live restoration, health checks and installed operations. No installed edits, service operations, real database tests, configuration changes, native enrollment or parallel full qualification. Preserve the frozen Relay projection component and incident evidence. No speculative timeout-only patch, new dependency, weakened protected contract or inferred historical cause.","completion_criteria":"Established source defects and unresolved incident causes are distinguished; each implemented correction has focused caller-surface lifecycle/failure coverage and independent smart plan/result review; coordinated whole-change validation, workflow/risk checks and PR/merge gates remain explicit; manager receives exact revision, evidence and any separately required live rollout scope."}

**Risk:** Elevated

**Complexity:** Moderate

**Reason:** app/supervisor.py, app/cli/service.py and app/asyncio_windows_accept.py are unclassified gray/watch runtime surfaces; launcher and recovery changes affect availability and child lifecycle. scripts/install-service.ps1 and existing tests/docs are blue. Risk will be reassessed against the exact selected fix and final diff.

**Discovery:** Start from verified installed/shared-main f31ac14186943cdc60ce10dbb37e26c42a3496bc in a new managed isolated checkout. Later live fetch and ancestry establish current origin/main5106866622deb9c011fd7538732d6b145a8ba147 is newer, not stale; installed baseline is distinct and untouched. Runtime API restart exhaustion leaves exit_code initially0; both CLI and PowerShell-generated VBS launchers detach with wait=False, so scheduler sees launcher completion, not supervisor lifetime/status. Installed launcher's exact generation/provenance still needs reconciliation because the reported service_launcher.vbs differs from CLI run/pallium_launcher.vbs. Existing AcceptEx patch immediately reschedules transient failures; incident mechanism remains unproved. Manager reports independent restoration succeeded after one wrapper timed out, reproducing disagreement between wrapper and startup/recovery budgets.

**Material assumptions:** Source diagnosis and fake-process/private-home tests do not establish installed socket causality or scheduler acceptance. Same clean installed revision was restored by manager with no settings/code update. Tests require an explicitly coordinated bounded slot and fail-closed isolation; no test run begins during discovery.

**Plan:** First invoke the /agent-workflow skill to create the Work Record and classify risk before any code edit. Trace existing supervisor, CLI, PowerShell launcher and socket callers, distinguish fatal exhaustion from intentional stop and map all readiness budgets. Delegate bounded static tracing to a cheap non-writing agent. Select the smallest demonstrated correction, specify exact files and lifecycle/compatibility expectations, and obtain clean-context smart plan review before production edits. Preserve existing helpers, process-tree cleanup, hidden windows, identity/token fencing and bounded recovery. Stop on unproved assumptions or scope expansion. Only then implement in this checkout and run manager-allocated focused checks; retain exact commands, time intervals and logs. Independent smart result review and coordinated full/PR gates precede release; no installed action is authorized by this plan.

**Verification plan:** When recovery is fatally exhausted, the supervisor must expose failure rather than successful shutdown while intentional stop remains successful -> isolated fake-process caller regression through run_supervisor and CLI service/run dispatch. When a generated Windows launcher owns a service run, it must preserve hidden launch and propagate child terminal status rather than detach -> isolated generated-script/launcher execution checks with only private fixtures and mocked scheduler registration. When readiness budgets interact, the documented bounded lifecycle must agree with observed outcomes -> source-derived budget accounting and deterministic injected-clock caller checks, not an arbitrary timeout increase. Existing child cleanup, retry, token/foreign-process and transient/fatal listener behavior -> affected existing suites once a slot is allocated. Whole-change release -> selector/full lane, workflow/Redline/import checks and independent review; manager owns installed qualification and roadmap reconciliation.

**Plan review:** Agent technical review: native subagent /root/outage_plan_review, clean-context gpt-6.1-sol/high, approved the amended first-slice plan against source baseline f31ac141 (2026-10-08). Findings addressed before edits: fourth stop-verifier parser, PowerShell Unicode serialization, cancellation races/child ownership and retry-helper kill seam. Approval covers the four named production files and isolated regressions only; generated-host evidence is not installed scheduler acceptance. Startup optimization and AcceptEx cause remain open.

**Approvals:** Existing human outage investigation/prevention request relayed by pallium manager authorizes isolated implementation only. No new installed launcher/config/restart scope is approved. Separate human plan/result gate will be required if reassessment raises Risk to High.

**Exceptions:** —

**State:** Blocked
<!-- agent-workflow:end -->

## Implementation

2026-10-08: Accepted bounded ownership from pallium manager chat
01a0d7ce-83c6-77e2-90f7-d413894059e1. Manager owns restoration and reviews;
worker owns isolated investigation/fix, not production operation. Initial
State Blocked names the pending reviewed implementation plan, not a need
for another general task approval; read-only discovery continues.

Manager-reported outage evidence (not independently reread here): Oct8
08:09:39/49 UTC health probes failed amid WinError64 AcceptEx storm; API69796
killed, five replacement startups each hit30s deadline. Final startup52388
timed out08:12:52.484 and underlying API31024 logged startup complete
08:12:53.093, followed by supervisor cleanup08:13:11. Scheduled task appeared
Ready/LastTaskResult0. This establishes observation order, not socket root cause.

Manager-reported restore: ONE installed restart-service.ps1 wrapper exited1
at180s with last health503; later actual health/status/queue all200 at
08:45:13 UTC, status ingestionok/uptime32.8, vector and embedding ready,
17438 completed/no pending or failed ingestion. Replacement attempt2
timed out08:42:53; attempt3 started08:42:59/timed out08:43:30;
attempt4 started08:43:38/timed out08:44:09; attempt5 started08:44:20;
processors81236/cleaner77768 started08:44:42. Same installed f31ac141,
no update/settings change. Nine eligible pending/two uncertain Relay entries
are not payload receipt evidence. Worker performs no further live checks.

New checkout C:/Users/I347041/.codex/worktrees/service-outage-recovery/Pallium,
branch feat/service-outage-recovery, baseline f31ac14186943cdc60ce10dbb37e26c42a3496bc.
No source or test edit/run yet. Frozen projection branch and its evidence are
untouched. Manager owns any canonical roadmap association/status; no exact
new roadmap/work identity was supplied, so none is guessed or attached.

## Exact first-slice plan (2026-10-08)

1. Correct fatal terminal status in `app/supervisor.py`: runtime API replacement
   exhaustion returns failure when no stop was requested; intentional cancellation
   remains successful, including during initial startup. Skip child restart handling
   after an intentional stop. Unexpected repeated zero-code child exits that exhaust
   the restart budget are failures rather than successful service completion.
   A stop requested during successful readiness must retain the API slot for
   cleanup but not spawn helpers. Check cancellation before and after slot polling;
   a successful replacement must become owned by its slot before cancellation cleanup.
   Preserve existing retry counts/deadlines, launch-token fencing and tree cleanup.
2. Change both existing VBS generators (`app/cli/service.py` and
   `scripts/install-service.ps1`) to `WScript.Quit WshShell.Run(..., 0, True)`.
   Waiting alone is insufficient: the returned status must become the host exit code.
   Keep hidden windows, existing commands, paths, task identities and installation
   behavior. Do not run either installer against a real user installation.
   Correct the PowerShell generator's pre-existing ASCII path loss with BOM UTF-16
   serialization, matching the existing CLI generator; qualify Unicode privately.
   Align `docs/context/operations.md`: source sync/restart does not rewrite generated
   launchers; actual installed rollout needs its own approved regeneration/verification.
3. Update the three launcher-reading regexes in `scripts/restart-service.ps1`
   to recognize the new parenthesized Run call as well as legacy statement form.
   Also update the statement-form parser in `app/cli/service.py`
   `assert_service_stopped`; review found this fourth consumer before edits.
   Preserve exact interpreter/home/port validation and fail-closed cleanup scope.
4. Add focused regression coverage to existing supervisor/service/restart tests and
   a small isolated launcher lifecycle test if needed: fatal initial/runtime recovery;
   requested stop before/during recovery; successful recovery; zero-code rapid exits;
   clean child shutdown; both generated forms preserving terminal status; Unicode
   and space paths; legacy/new metadata parsing and malformed input exclusion.
   Drive generated VBS through a Windows script host with a private fake `app.run`
   or private stub child, never the real service. Any PowerShell installer test mocks
   scheduler registration and USERPROFILE into a private tree. Snapshot/config,
   kill-tree, network and scheduler seams must be fenced before test execution.
   Fence both injected `kill_fn` and module `_kill_tree` used by the retry helper.
5. Manager allocates the bounded focused-test slot; independent smart result review,
   whole-change selector/full suite and workflow/CI/PR gates follow separately.
   Manager owns publication and all installed qualification/rollout approval.

No timeout or provider/cache change belongs to this slice. Nominal supervisor API
retry budget is 5 x 30s + (2+4+6+8)s = 170s, excluding process termination/spawn
overhead; CLI readiness is120s and wrapper readiness180s. These differ, and manager
observed successful restoration after the wrapper deadline. They do not prove which
startup stage regressed. Source spans from provider initialization to vector-count
mismatch warning include HF file resolution, ONNX session/tokenizer creation,
optional inference probe, vector index load and database checks. Process-level
session cache does not survive retries. Stage attribution and regression-backed
optimization are a later reviewed slice; no arbitrary timeout increase, live cache
access or inferred socket cause is authorized here.

## Bounded offline startup attribution

2026-10-08 implementation checkpoint: reviewed first slice is being implemented by
a bounded cheap worker in this same isolated checkout; root owns this record and
profiling evidence. No tests run yet. Native full suite and installed operations
remain withheld. State uses the workflow's allowed pre-verification value, not an
invented `Implementing` state; `Ready for review` awaits verification evidence.

Manager explicitly authorized exact cached model/tokenizer inspection/copy, then
one installed-interpreter profile and private local-only Hub resolution. Neither
authorization permits installed writes, downloads, online calls or a live DB copy.
Copied assets for `intfloat/multilingual-e5-small`, snapshot
`614241f622f53c4eeff9890bdc4f31cfecc418b3`: model470268510 bytes SHA256
`CA456C06B3A9505DDFD9131408916DD79290368331E7D76BB621F1CBA6BC8665`;
tokenizer17082730 bytes SHA256
`0B44A9D7B51C3C62626640CDA0E2C2F70FDACDC25BBBD68038369D14EBDF4C39`.
Source cache was unchanged; copies/hash checks and scripts/logs are retained only
under ignored `build/startup-profile` in this isolated checkout (~0.975GB copies).

Actual provider constructor, with `_download_model` returning copied paths, in one
private offline process per interpreter (no app/service/DB imports, Python -B):

| Phase | Development interpreter | Installed interpreter |
| --- | ---: | ---: |
| ORT import |0.415476s|0.351917s|
| ONNX session |0.625196s|0.618762s|
| Tokenizer load |0.356802s|0.366045s|
| Dimension probe |0.008157s|0.017290s|
| Provider constructor |0.990358s|1.002317s|
| Imports + constructor |1.716437s|1.592166s|

Both Python3.13.14/ORT1.29.0/tokenizers0.23.2/HF1.30.0; numpy2.5.2 development,
2.5.3 installed. Separate installed-interpreter HF probe uses explicit
`local_files_only=True` and a reconstructed private cache: import0.490361s,
model resolution0.001991s/tokenizer0.000610s. Initial synthetic cache probe failed
because authored ref had a trailing newline; exact40-byte known main ref was copied
and corrected probe passed. Both logs retained; that fixture error is not a product
defect. These probes exclude normal online HF metadata resolution, index/DB work,
service build, OS/cache load under the historical outage and process contention.
They do not establish the historical culprit or claim a startup optimization.

Source attribution: optimized SQLite backfill existence query is preferred over
the paginated fallback; introduced Sep6 atd3e29e3f. It uses source/lexical inner join
and vector left join, with type/target indexes already available. Vector load reads
metadata/idmap JSON then nonempty native index. First reconcile waits2s in lifespan
and gates functional health; it is after service construction. Existing logs have
no completed INFO marker splitting HF/ORT/vector/backfill/count/reconcile stages.
uv.lock changed Sep7 at2fbb0f18; unchanged provider source since May2 does not prove
unchanged installed runtime, and current metadata cannot establish historical drift.

## Implemented first slice and focused verification (2026-10-08)

The reviewed four-file production correction is implemented, not deployed:
supervisor cancellation owns and cleans up children without restarting them;
fatal initial/runtime exhaustion and repeated unexpected zero-code exits report
failure; both hidden VBS generators wait and propagate child status; PowerShell
serialization preserves Unicode; all four stop/restart metadata parsers accept
legacy statement and new parenthesized forms while retaining scope validation.
Operations documentation explicitly distinguishes source sync from separately
approved installed launcher/task regeneration and scheduler qualification.

Tests run with the existing development interpreter
`C:/Dev/rore/Pallium/.venv/Scripts/python.exe -B`, private child environment before
pytest imports, serial `-n 0`, and private/mocked service, scheduler, kill and
configuration boundaries. New launcher lifecycle tests execute both actual
generators through a private Windows script host with only stub children and
fenced Python imports. They prove wait, status0/7 and Unicode behavior, not the
installed Task Scheduler recovery contract. No user service/app was stopped.

Initial complete focused command:
`python -B -m pytest tests/test_supervisor.py tests/test_service.py tests/test_restart_service.py tests/test_service_launcher_lifecycle.py -vv -q -n 0 -o faulthandler_timeout=30`
returned104 passed/18 skipped/2 failed in46.18s. The two failures were test harness
assumptions: private PALLIUM_HOME overriding default-home expectation, and a
PowerShell stdout/stderr encoding mismatch. Fixes explicitly unset that variable
for the default-home test and select UTF-8 in the harness; assertions were not
weakened and production source did not change. Exact two failed nodes passed
in1.38s, then both affected files `tests/test_service.py tests/test_restart_service.py`
passed78/18 skipped in40.29s. Skips are Windows-inapplicable Linux systemd tests.
Retained stdout logs under ignored `build/service-recovery-evidence`:

- `focused-initial.stdout.log`: SHA256 `861809B7266202A888B828AE89015D228A7E926E03650204CDE837D85F6181CE`
- `failed-nodes-rerun.stdout.log`: SHA256 `A0BE2C410C580A1843AB7FD03D5C40B9F65256C04083536C379F5F0641CC8E90`
- `affected-rerun.stdout.log`: SHA256 `DE6CC772FCABC476B54B4DAA949BD451490333834DE3C5011489C1316615E380`

Earlier partial runs are not acceptance evidence. A zero-code child fake initially
returned0 once then None forever; it was corrected to persist0, and its exact node
passed1 in0.45s. Only verified test-owned processes were terminated. An attempted
`uv run --no-sync python --version` created an ignored checkout-local `.venv`;
it is not used by tests and must not be confused with either existing runtime.

Selector against verified source baseline f31ac141 selected the full lane across
all10 changed files, including dirty/untracked changes. Final selector against
fresh origin/main, full non-slow validation, independent final result review,
workflow/CI/PR gates and publication are NOT complete. State Blocked records the
manager-withheld full qualification slot while isolated diagnosis/source review
continue. Manager owns roadmap reconciliation and installed rollout.

## Synthetic startup stages and next attribution boundary

Manager authorized one private synthetic DB/index process after the focused slot
drained. Actual installed interpreter and real storage/vector methods used a new
private paired SQLite main/Relay database,17438 synthetic sources,25805 vectors,
384 dimensions and a native index containing one orphan. No app/service builder,
actual installed DB/content/cache or online call was used. Results in seconds:
empty storage0.108682; populated storage0.180632; all-present backfill0.034216;
vector count0.002380; nonempty native load0.140813; first reconcile with orphan
0.078597; one missing-first-source backfill0.001251. Fixture index build1.554392
and save0.088951 are setup, not startup. Process exited0 in5.08s and drained.

Ignored probe script/log SHA256 evidence:

- `profile_model.py`: `5E8360A4765F96D54D11C6F89A54A2C077BB223048A226CFAE00E14C6BFAC24A`
- `profile_hf_cache.py`: `DEF149BD0EDFCF21EB52DDEC20D975F1C9B07CCF64041DA5B836FE1D25EB96EA`
- `profile_synthetic.py`: `5BA8B1410150E9A6874FA3A89727B4AB98519AF5E551340DEF3A38E44D0F53E5`
- `model-timing.log`: `1A5FDAB341BE5EAFEBE9E9481A89E261BD6541056A0A5BACF66257452829CF6D`
- `installed-model-timing.log`: `80A24FD6A4A56754C1B8CBBBDFE87E023D48F5A9B57C14E43E20BD102DA406E7`
- `hf-cache-timing-corrected.log`: `49539E90D521C5A1D49A31BB93CCF53DAE0CCB2858ABBCDC9946F08D231AE03A`
- `synthetic-stage-timing.log`: `81B054FE060A8D905B8B13CADC9CA390E98C4B8E4B104979360ECE0763E5BAC9`

All sampled isolated phases are fast now. Historical startup remains unexplained:
successful attempt5 spans08:44:20.305994 to08:44:41.487218 UTC; retained logs show
HEAD302 at local11:44:27 and vector mismatch at11:44:40, with no request-start or
final redirect timestamps. That approximately13s interval is not measured network
latency and offline samples cannot be subtracted to identify its cause.

Next authorized diagnosis from manager: ONE <=60s installed-interpreter/private
cache process timing normal public HF metadata resolution plus actual provider
constructor. No token, asset download, retry run, live cache/DB, installed mutation,
production instrumentation or service operation. Establish HEAD-only URL and asset
download guards before execution; if safe supported seams cannot guarantee that,
present the exact plan before executing. Current timing cannot prove historical
causality. Full qualification slot explicitly remains withheld.

Trigger2 dropped: consumer parser/test-fixture review corrections are not an
agent-workflow defect. Earlier missing guessed reference was an agent path error,
not a broken skill reference. Installed pallium-memory skill now reads completely;
exact injected Relay sender identity is still unavailable, so authorized manager
coordination continues by app-message fallback without guessed scope.

## Source freeze, review and direct network sample

Source freeze commit `835fdb0265dcebce07bb13fff4d20c551e12d7b9`, tree
`86640e1e478979d12c0d2e4f7083e137a217510e`. Clean-context source/isolation review
by native subagent `/root/outage_source_review` (gpt-6.1-sol/high) found no production
correctness defect and kept Elevated/Moderate. This is NOT final result acceptance;
the full validation slot is withheld. Reviewer independently matched all three
focused stdout hashes. One missing plan-required regression was identified:
cancellation during successful runtime replacement readiness. A test-only addition
is authorized; manager granted ONE exact serial private node after safety inspection,
not a subsystem/full run. Source/checkpoint review limits remain explicit.

The authorized ONE normal HF resolution + actual constructor sample completed
exit0 in3.38s wrapper with copied private cache and installed interpreter -B.
Supported custom HTTP client admits only known public HTTPS HEAD URLs, rejects
GET/unknown-host/auth/cookie; those guards were checked without network first.
Explicit token=False, implicit-token/telemetry/Xet disabled and trust_env=False;
asset-download entry blocked as extra defense. No retry or further sample.
Two HEAD302 responses took0.311924s/0.183916s; normal model resolution0.431265s,
tokenizer0.186007s; ORT0.635514s/tokenizerload0.382377s/probe0.005609s;
constructor1.655080s/total2.585028s. Only stderr was unauthenticated-Hub warning.
No installed/config/DB/service or source-cache write. This current sample did not
reproduce slowness and does NOT prove absence of a performance bug or its cause.

Private evidence SHA256:

- `profile_network.py`: `CD6FBE3D557C47D34B7546E2CE4384200685D34D65F7AD2D621157133932B1B6`
- `network-timing.log`: `E1453A39B3AFD1047A1559AC6F72D6F8A0233AD9B8F1E8005C066D401518D0F6`
- `network-stderr.log`: `131D86FC090736A011859DD38722CE9D9D0840E2602BA2A8048C8A1AF465F9EC`

The unused newly generated checkout-only `.venv` was verified as non-linked,
containing only fresh uv/bootstrap artifacts with no running process reference,
then moved recoverably to ignored `build/service-recovery-evidence/unused-uv-venv`.
Shared and installed runtimes are untouched. This avoids accidental adapter selection.

Initial workflow adapter check against frozen source passed record/baseline/order
checks but blocked on absent fresh Redline evidence and exact plan-review reference
syntax. This record now includes the actual native review reference; fresh generated
Redline/import evidence follows. No check failure is claimed green or waived.

## Initial diagnostic proposal — superseded below; not approved for implementation or rollout

Manager requested this exact source-free proposal after all current isolated samples
failed to reproduce the historical delay. Keep it separate from the four-file
recovery correction. No new tracing framework, dependency, setting, timeout change
or database operation. Proposed production files and existing boundaries:

| File | Minimal observation change |
| --- | --- |
| `app/supervisor.py` | Extend existing API spawn/readiness logs with monotonic start/completion duration and child PID; keep retry/nonce/deadline/kill behavior unchanged. |
| `app/run.py` | Capture an early monotonic module-entry value before heavy imports; emit module-import duration only for `serve`, through existing runtime logging once ready. |
| `app/main.py` | Capture module-import duration; log factory/config/MCP/early-storage and complete service-build boundaries, lifespan completion, and first reconcile start/completion or failure. Preserve the existing2s initial wait and set ready only after success. |
| `app/dependencies.py` | Fixed start/completion/failure markers around actual storage construction, embedding construction, index load/create, model/schema/backfill/pending-rebuild checks, count checks, and remaining service assembly. Do not add probes or duplicate any query. |
| `providers/embedding/onnx_provider.py` | Fixed duration markers for each actual HF resolution, ORT session, tokenizer load and dimension probe; distinguish existing process-cache reuse and explicitly supplied dimensions from executed phases. No URL, revision, token, path, model-input or exception text in new markers. |

Use existing `logging`/`emit_runtime_log` and stdlib `time.perf_counter()` only,
with fixed stage names, elapsed seconds, completion/failure/skipped status and
process PID where needed. Start markers identify an unfinished stage if killed;
completion/failure markers use `try/finally` without intercepting or changing the
existing error/degrade paths. Same-host monotonic timestamps join process-entry,
spawn and readiness boundaries without treating wall-clock or HTTP302 output as
network duration. Timers measure the original calls, not separate retries/probes.
Log only startup/first reconcile, not every periodic reconcile or query.

Reclassification before any edit: all five production paths are gray/watch under
current policy, no new dependency boundary or API/schema change. Elevated/Moderate
is proposed, subject to exact smart plan review and final diff; no policy exemption.
Prepare a separately identifiable Work Record/isolated branch before source edits;
do not enlarge the frozen correction silently. Manager remains roadmap/rollout owner.

Focused tests would extend existing caller suites located by repository search:
supervisor and `tests/test_app_run.py` for ordering and unchanged statuses; actual
provider construction with fake HF/ORT/tokenizer and fake monotonic times for cache
hit/miss, supplied/probed dimensions, each failure/degrade and no added download;
factory/build and first-reconcile HTTP health tests for success/failure/skipped-vector,
unchanged ready gating and exact no-extra-operation counts. Assert new marker keys
and fixed privacy-safe values (including hostile path/token/payload sentinels), not
machine-specific elapsed thresholds. Run private serial focused nodes first, affected
files then selector-required full non-slow and smart result review/CI before rollout.

Installed observation requires a new exact human approval, not current PR/test
approval. Proposed scope for manager to present after review/gates:
verify clean development/stable installed clones and exact approved revision;
record current commit and backup only affected installed source bytes into an
explicit recoverable private directory, with hashes and current launcher/task/config
identities retained. Fast-forward stable installed source only to the approved
diagnostic revision; no dependency update, launcher regeneration, task/config/env
change, DB copy/migration or native host change. Use exactly
`C:/Dev/rore/Pallium-installed/scripts/restart-service.ps1` ONCE with existing default
180s readiness deadline. This stops the current Pallium tree and briefly interrupts
HTTP/Relay/processing; its existing supervisor may make up to5 bounded API attempts.
No second restart, manual receive or automatic rollback restart is authorized by
that one-run scope. Retain stage logs/result and verify `/health`, `/status`,
`/debug/queue/health` on19836 plus actual running revision independently of wrapper
result. A timeout is a failed observation, not permission for another operation.

Rollback plan: preserve exact prior source/hash bundle and task/launcher/config;
if needed manager requests or reuses an explicitly included rollback allowance to
restore only those source files from the bundle and invoke the same restart wrapper,
then verify the three health endpoints and prior revision. Never destructive Git
reset, dependency downgrade, data/schema restore or host updater override. Present
the optional rollback restart separately from the ONE observation restart so the
human can approve its precise impact. Without approved rollout, deliver the diagnostic
PR only and leave installed attribution open. Even a fast installed observation
does not resolve a historical slow-start or AcceptEx incident.

## Review finding closed; handoff gates still open

Added only `tests/test_supervisor.py::test_stop_during_successful_runtime_replacement_cleans_owned_child`:
initial API healthy, API exits, replacement readiness requests stop and succeeds.
The observed contract is status0, two readiness checks, exactly initial API/helper/
replacement spawns, and termination of the helper and owned replacement. The same
clean-context smart reviewer inspected the exact40-line test-only delta and confirmed
the gap is closed in source, with no weakened assertions or lost isolation; prior
production review remains valid. Production source is identical to835fdb02.

Manager-allocated ONE node command
`C:/Dev/rore/Pallium/.venv/Scripts/python.exe -B -m pytest tests/test_supervisor.py::test_stop_during_successful_runtime_replacement_cleans_owned_child -q -n 0`
passed1 in0.10s, exit0, private harness2.581s. Test-ownedPID46220 and direct children
confirmed drained. Retained stdout copied to ignored
`build/service-recovery-evidence/cancellation-node.stdout.log`, SHA256
`564910381F636777F7FBAC7471EDC5A637523F2C34AC9FF9A43C5A156097A6E8`;
stderr empty. No subsystem/full suite was rerun.

Local source checks: import-linter produced no violations; generated Redline on
baseline-to-frozen diff isGRAY/advisory1 with no checkpoints/boundary violations,
and workflow adapter then returned clean0 after the exact plan-review reference
repair. Final fresh report must include the test-only delta and record before handoff.
These are local governance checks, not application/full/CI or installed acceptance.

Next owner: pallium manager must coordinate the held full non-slow qualification
slot and current-origin selector; then clean-context final result review, PR/review
threads/CI/merge, and separately approved installed launcher rollout/qualification.
Keep this managed checkout because source/tests and ignored proof assets remain
needed by that open work. Historical startup/AcceptEx and broader Relay recovery
acceptance remain unresolved; the diagnostic proposal is not an implementation or
live-change approval. No worktree retirement or model-evidence deletion is safe yet.

## Current-main integration checkpoint (before merge)

Manager granted the exclusive ONE full non-slow slot, then explicitly required
normal integration of exact current main before spending it. Two live fetches and
ancestry checks established origin/main `5106866622deb9c011fd7538732d6b145a8ba147`
is a descendant of installed baselinef31ac141, including PR298/300-305. Earlier
"stale origin" wording was wrong and is corrected; no deployed revision is inferred.
No full run began on the old base. Frozen correction `9ab72a3910e1243cf02fff516a62dae4a096b949`
and its reviews/logs remain valid for the original source, not the combined candidate.

Authorized next step: ordinary merge of exact510 into this isolated feature branch,
no force/rewrite/rebase, installed changes or publication. Inspect whole integration
and preserve our correction delta; any genuine semantic conflict stops for concrete
review rather than a guessed resolution. Independent reviewer assesses interactions,
then ONE full run on the clean combined candidate with private prepytest environment
and fail-closed external/model/live-service guards. Full harness safety inspection
precedes execution; root and cheap worker have explicitly withheld old-base execution.
Diagnostic proposal remains planning-only, not merged instrumentation or rollout.

## Combined candidate and full-validation failure

Ordinary conflict-free merge of exact main5106866622deb9c011fd7538732d6b145a8ba147
produced6044ced955c50ca965b3cb0f65bc57e02a8ea369, tree763da831afb97bdbfaff199aba310be844a53ce8.
Four production and four test files remain identical to9ab72a39. Operations docs
auto-merged, retaining both sets of guidance. Independent /root/outage_source_review
found no new interaction issue or extra focused node required; not final acceptance.
Fresh selector required the complete non-slow lane. Import checks had no violations;
Redline GRAY/advisory1, no checkpoints/boundary violations; workflow clean0.
Ignored build evidence hashes: redline-verdict.json
43E8247F6BB53DA65488B11D6C3DF5689E4DD68B05802F31C0974A175657FA07;
import-linter-report.json
341EE0AF66997863E05BA32563DACEF54980DFE6E64D7CE3E889973982B72103;
service-recovery-evidence/workflow.stdout.json
6D591AACDF07D3DA4339763ABA7818009531916DADD056D1646B5F072F7D8F52.

Manager-allocated ONE full command on clean6044:
`C:/Dev/rore/Pallium/.venv/Scripts/python.exe -B -m pytest tests/ -x -q -n 0`
failed:1 failed/512 passed/482 deselected/1 xfailed in175.76s, wrapper185.238s.
Node: tests/test_async_worker.py::test_supervisor_spawns_snapshot_worker_when_enabled.
Harness PALLIUM_SNAPSHOT_ENABLED=false overrode the fixture enabled=true TOML:
root's configuration-precedence mistake, not a source defect or waived failure.
Controller also lacked Get-FileHash and left EXIT blank; native status was not
captured. Pytest failure summary is authoritative. No guard blocks/pytest stderr.
Owned PIDs79660/35084/43044/71808/8436/33936 and descendants confirmed drained.
Retained ignored service-recovery-evidence logs:

- full-first.stdout.log: D5D3AA550E0003917B8E8CAE9CD17AC246084B47450FE2F44E36E30EE2E10AF0
- full-first-controller.stdout.log: B45588B248DB6A96374BFB35C5A27F8F691FBE1BE48A3C13DCBD6C75C8C7C230
- full-first-controller.stderr.log: DDBE92130B4E14DE3A1840515C701EF19467CDCA7C296201D09BF6F7AC0A6E70

## Corrected harness and exact-node outcome

Removed six global semantic overrides: storage backend, main/Relay DB, snapshot
enabled/path, vector path. Default private TOML supplies safe paths; fixture TOML
can replace it via PALLIUM_CONFIG_FILE. Private profile/TEMP/wakes/caches, Python/
Node network guards and private/mocked native process/service seams remain.
These process-local guards are not a native Windows firewall guarantee. Retained
process handle and validated integer exit capture precede Python-native hashing;
hash errors cannot replace pytest status. Independent quick reviewer approved the
exact node, with portable Path.read_bytes hashing corrected before execution.
No source/assertion/installed change.

Manager-allocated ONE exact failed snapshot node on clean6044 passed1 in0.17s;
native/controller exit0, wrapper2.665s. Owned controller74484/Python21408 and
descendants drained; empty stderr, no hash errors/guard blocks. Actual fixture
TOML retained enabled=true and private main/derived Relay DB and snapshot files.
Ignored service-recovery-evidence/snapshot-node.stdout.log SHA256
8FE1A5EBE3BEF9E75708F4835E8B369440D1A5A7B0BAD4ED8A81513C7B8D4FC5.
Corrected exact-node runner SHA256
A18AD63E1A567ED9EDD7B9885726C61DD82B88BFCD063D5F55F2FD5845CD6D20.

Manager grants ONE complete non-slow run on source-identical6044, pin records-only
head if changed, after independent review of corrected private full scope. No retry
on failure. State remains Blocked on incomplete full validation then final review
and manager-owned publication/CI. Root records outcome before transition. Installed
service untouched; scheduler/native acceptance, historical startup/AcceptEx cause
and broader Relay reliability remain open.

## Superseding three-file diagnostic proposal — planning only

Smart critique and manager planning acceptance replace the earlier five-file proposal:
only app/main.py coarse factory/build/lifespan/first-reconcile boundaries;
app/dependencies.py actual storage/provider/index/grouped rebuild/count/build phases;
providers/embedding/onnx_provider.py actual HF/ORT/tokenizer/probe and cache/supplied-
dimensions outcomes. Omit supervisor/run import detail: existing PID/attempt/readiness
logs bracket processes; no factory marker means before-factory, not a proved import
cause. Add detail only if that region is measured slow. No source instrumentation yet.

Use existing logging/helper and stdlib perf_counter, same-process durations plus PID,
fixed stage/status values only. No cross-process clock subtraction, URLs/model names/
revisions/paths/tokens/payloads/exception text, duplicate operations, new settings or
framework. Enable logging before markers. Failure logging must preserve the original
exception; finally must not imply success or mask failure. Preserve readiness,2s
initial wait, retries/degrade and first-reconcile-only scope. Separate isolated branch/
Work Record, exact risk/plan review, focused lifecycle/privacy checks, selector/full/
final review/CI before any deployment. Three paths gray/watch, proposed Elevated/
Moderate subject to final diff. Manager owns roadmap and exact human rollout request.

Earlier file-only rollback proposal is withdrawn: it leaves mixed source. Installed
scope must record actual prior commit, clean state and COMPLETE approved revision
delta, recoverable refs/work/settings/data; fast-forward may include more than the
three diagnostic files. Restore exact prior committed tree with an explicitly approved
ordinary Git operation, not reset-hard. Select exact operation after installed-state
inspection; any temporary detached HEAD must include restoring normal branch/update
behavior and must not be called local main. No launcher/task/config/env/dependency/
native-host/DB change silently included. ONE default180s restart wrapper observation
briefly interrupts HTTP/Relay/processing; an optional rollback restart needs distinct
explicit scope approval. Verify actual revision and all three health endpoints. No
live change is authorized here; a fast future sample cannot close a historical incident.

## Second full run — failed; no retry

Clean-context /root/outage_source_review cleared ONE full non-slow run on clean
d5f7ee64fead13e87c91b5a2aa5e80817fe8dde3, source identical6044. Runner SHA256
3B394D8AE42B1778DA2D6FF381B8C5845D2A33F33E34C4E8F66243D87DAA2ACE;
Python guard D2C3317EF893C78FD5C6ADF4DB0035EF9DA8EF1AF708A7D62F86C83EDBBF7C87;
Node guard387D3DBF30CDF27BD00EEACC2770093562908A98FAF499BC9524F14EEA478D6E.
Private TOML retains fixture precedence; guards are process-local, not an OS firewall.
Reviewer explicitly limits sampling-based drain evidence: tracked parent PID is not
creation-validated when admitting children, and a short-lived parent can be missed.
Before launch, worker caught root's typo in an abbreviated guard hash; full hash
matched the reviewed artifact and root corrected the instruction. No mismatched run.

The same complete command failed: 1 failed, 855 passed, 2 skipped, 482 deselected,
1 xfailed in257.69s; inner native exit1, controller exit1, runner266.666s.
Exact node tests/test_claude_wake_instance_isolation.py::test_two_instances_real_hook_http_and_outage_recovery
failed at line78: register_claude_wake returned False and HTTP ledger seen=[] before
a request. Pytest truncated the diagnostic tuple, so whether its binding check was
False is unknown; root's initial binding-rejection wording is withdrawn. This result is not classified as product or
harness failure pending its source/artifact chain. Original failed run is retained.
No retry, source/test/assertion change, live operation or publication.

Private run b916e2b9f8a8416791a94593d0e9cfaa and controller
da8d01b6186d45da8b5e7a8ca04deafe are retained under local Temp. Hidden controller27300,
test root72064. Both guards produced no block log; pytest stderr empty. Outer
collector's separate Test-Path -and parsing error occurred after it had recorded
the native failure, hashes and sampled drain; it did not mask the pytest result.
Do not conflate collector error with binding assertion or claim successful evidence.

Worker and root independently compared all47 retained PID/creation identities to
current CIM processes:0 exact remainders. Worker private-path check found only its
read-only audit itself, no test residue. This proves recorded identities absent,
not completeness of sampling. Copied ignored service-recovery-evidence SHA256:

- full-second.stdout.log: 1ABE1AA941C4120AF3AE0182B65051E6F429EB1A39C0C9EDCCFD8A61BC887BA0
- full-second.stderr.log: E3B0C44298FC1C149AFBF4C8996FB92427AE41E4649B934CA495991B7852B855
- full-second-controller.stdout.log: BFACDB772B927B8DEA0D3E64E627C6DCE86C3776D95784CAB3F8320359929754
- full-second-owned-identities.log: 2DC0EC7239D1791312DE67DC89105A44F401F271A46344F9D18F6B29962B7695

Manager informed and authorized bounded READ-ONLY attribution only: retained private
binding inputs/path origins, before-import fixture/environment precedence, module
caching/order and unchanged baseline510 sources. Cheap worker owns this trace; root
does not duplicate it. Next is one concrete cause/reproduction hypothesis and a safe
exact-node proposal, not a blind full retry or weaker binding checks. State Blocked;
required full/final acceptance and manager-owned PR/CI remain unsatisfied. Installed
service and separate diagnostic proposal unchanged.

## Read-only failure attribution and bounded proposal

Worker verified test_claude_wake_instance_isolation.py, conftest.py,
app/claude_wake_binding.py and Claude common.py unchanged510 to tested d5f7.
No correction caller reaches this in-process TestClient/fresh-module hook journey;
it does not invoke supervisor, installed service, scheduler or restart wrapper.
Fixture patches Path.home and explicitly selects first/second database. Hook loads
fresh after bindingA is written; persisted binding/marker20101/ownerA and corresponding
B/20102 artifacts agree. An earlier test_app_run serve test leaves service port8011
in the process environment, explaining an extra B marker8011, not this failure:
hook uses pinned20101. Its conflict flags were not recoverable from the truncated
assertion; neither binding rejection nor that environment leak is proven causal.

Concrete path hypothesis: retained intent base189 characters; target.json and lock
259; temporary.json.tmp263. Digest
efbb4ed828adb30f0d26b8d98613c4347f4fc5b5e0efea1a7f7803eee2474c34.
Only1-byte lock survives in intents directory, no target or temporary file.
_write_wake_intent catches OSError on temporary write/replace and returns False
before HTTP. This fits legacy Windows MAX_PATH failure after acquiring the lock,
but long-path awareness or another write/replace failure can produce the same state.
This is a source/artifact hypothesis, not a reproduced product defect or historical
Relay incident explanation. Runner defaults do not select this fixture's explicit
app databases or patched-home binding paths.

Proposed smallest discriminator sent to manager: ONE unchanged exact failed node
with fresh short private pytest --basetemp under system Temp, retaining private
profile/config/wakes/caches/network/native seams and independently reviewed cap/
command. No prior-test leak fix or stronger/weaker assertion, source instrumentation,
second node/full retry or live operation. A pass narrows path interaction; a failure
needs captured import flags/operation errors, not guessed causality. Test allocation
not yet granted. All required full/final/publication gates remain unsatisfied.

## Unchanged short-path node — narrow reviewed pass

Manager subsequently granted ONE exact node with fresh short --basetemp after
independent isolation/command review. Reviewer /root/outage_source_review cleared
runner583A39E59E7A9BEE8FF48F6619168EF10610A26EC276D21EE7D6D587685C274D,
pinned clean1ea6368b6f2374adf12c766e6b282c89a8f70605; source/assertions/guards
unchanged. Unique absolute basetemp verified absent before pytest:
C:/Users/I347041/AppData/Local/Temp/sr-e3fbed824cad4c30af65e0cb42ab1b96.
It is newly owned, not a reused directory pytest could delete. Known1385 blocked
read-only preflight once; elevated retry succeeded before launch. No test retry.

ONE unchanged test_two_instances_real_hook_http_and_outage_recovery passed1 in1.70s.
Worker launch-tool output reports native/controller0, root77844, runner4.667s.
No separate controller file/PID or three sampled PID/creation identities were retained;
do not claim those are independently verified. Pytest stdout is independently read
and hash-verified by root and reviewer, copied to ignored
service-recovery-evidence/short-path-node.stdout.log SHA256
454A4A62447DBF9A80CB8B7B117DA144779D64C7E21E04AA1FD32669F840395D.
Stderr empty, both guard logs absent. Exact private run remains in Temp:
pallium-full-suite-run-3602f7e42116479089cc78e00aff29cf.

Retained fixture intent JSON/lock lengths208, temporary212; same digest as prior.
Lock exists, target/temporary absent after lifecycle teardown. Private default TOML
and fixture paths remain private. Runner sampled3/drained=true; worker and root
post-run CIM scans found0 private-path matches excluding their own audit and root
77844 absent. These observations do not reconstruct missing historical identities
or prove a complete sampled descendant tree.

## Bounded diagnostic result review

Agent technical review: native subagent /root/outage_source_review, clean-context
gpt-6.1-sol/high, read-only review of the unchanged short-path outcome.
Reviewed revision:1ea6368b6f2374adf12c766e6b282c89a8f70605.
Verification adequacy: adequate for this narrow one-node pass, not whole-change
acceptance. Reviewer independently matched short-node and preserved failed-full
stdout hashes; confirmed Work Record-only revision difference. Native/controller
exit0 remains supplied launch-tool evidence without a retained controller artifact.
Cleanup limitations above remain; no native or installed acceptance.

Standalone short-path pass removes preceding test order as well as shortening paths:
it is compatible with MAX_PATH hypothesis but proves neither causality nor order
independence. No caught OSError/winerror was captured, no product defect inferred,
and no production fix proposed from this evidence. Do not fix leaked port in this
slice. The prior full validation remains failed and State Blocked; no further full
allocation assumed. Manager receives exact outcome/review/limits for disposition of
a next whole-change run with ordinary short isolated paths and retained controller/
identity evidence. Separate startup diagnosis/installed rollout/Relay acceptance
and manager-owned publication remain open; installed environment untouched.

## Next complete validation allocation — before execution

Manager grants ONE complete non-slow run after independent review of fresh short
owned --basetemp and retained controller exit/identity ledger. Fresh git fetch
confirms origin/main and FETCH_HEAD remain5106866622deb9c011fd7538732d6b145a8ba147;
no source integration is needed. Production source remains6044, no application/
assertion/leaked-port changes. Pin684e or this records-only successor; no parallel
profiler/native/full run, no installed operation/publication, stop on failure.

Cheap worker prepares only the existing private harness: complete tests/ -x -q -n0,
1800s cap, short fresh GUID pytest base verified absent before cleanup, same private
default config/guards without global feature/identity overrides. Inspect worst-case
derived paths, not only the passing node. Retain controller PID/exit/log and sampled
PID/creation identities as actual artifacts; validate tracked-parent creation when
admitting descendants, retain short-lived-parent/sampling limitations. Independent
smart command/isolation review precedes ONE execution. Full pass then final independent
whole-change result review; neither hypothetical path cause nor installed/native
acceptance is inferred. State Blocked until required full result and review exist.

## Complete non-slow validation — passed, final review pending

ONE authorized run on clean1dd6d3c63dde378d54303d310cd6d8fdacafb883 completed:
`6415 passed, 45 skipped, 482 deselected, 2 xfailed in 1389.00s (0:23:09)`.
Command: existing development Python `-B -m pytest tests/ -x -q -n 0 --basetemp`
with newly owned absent-before-launch short Temp directory
`sr-30b56aa97e31454f8c4da21272b8bf10`; pyproject's non-slow selection retained.
Pytest, runner and capture exited0. Test process elapsed1399903ms; controller1403691ms.
No retry, additional test, profiler, source/assertion change or installed operation.

Run artifacts: Temp/pallium-full-suite-run-1d93ca6afd7744ceb6ac8d613f5729e6.
Capture artifacts: Temp/pallium-full-suite-capture-b3534fb3e2844772b7be0a5f5ceb4ad5.
Controller79532, collector60924, pytest18360; actual creation/executable records
retained. Runner and independent collector record76 owned identities drained,
0 remaining and0 unknown. Root independently checked current CIM inventory:
none of these76 PIDs, controller or collector present. Five-second sampling can
miss short-lived descendants; this is recorded-identity drain, not complete
historical process-tree proof or global network isolation.

Python guard recorded21 denied resolutions:20 installed-service port19836,
1 remote DNS/name lookup. Node guard log absent/empty. Denials remain explicit;
this pass does not qualify unguarded installed/native integrations. Stderr empty.
Copies under ignored build/service-recovery-evidence/full-final-* retain the
full summary, controller identity, guard, ledger, runner/independent drain and
hash manifest. Root independently matched:

- stdout: 2C6CC59E3866FE4A8CC2AA02DD023D937E8A1D2FB7392BC7E89820DEFCFC3189
- Python guard: B77F20F859F98B4517E2958A9EC9E2E92AC16B6B6E5234E3BAACA46D24D22AEE
- independent drain: 79F81AF14143288D0690C22A4AD11C6CFA3A735F1ECCA709991D7152202057FC
- capture summary: 87DDB371201BEC0CDC65170680AB54228253F5A217DEABA085FF238B5447E1CD

Earlier failed fulls remain recorded, not waived or erased. Short paths plus
complete-suite pass narrow the earlier fixture failure; without a captured
OSError they do not prove MAX_PATH causality or explain historical Relay incidents.
Independent whole-change result review requested from /root/outage_source_review.
State remains Blocked until that review is complete. CI/publication/merge, installed
launcher qualification, outage causal diagnosis and broader Relay acceptance remain
manager-owned/open. The user's everyday installation is unchanged.

## Result review

Agent technical review: native subagent /root/outage_source_review,
clean-context gpt-6.1-sol/high, independent whole-change source/result review.
Reviewed source6044ced955c50ca965b3cb0f65bc57e02a8ea369 and tested records-only
head1dd6d3c63dde378d54303d310cd6d8fdacafb883 against main5106866622deb9c011fd7538732d6b145a8ba147.
All10 changed paths inspected; no actionable production/test/documentation defect.
Technical source review approved; Elevated/Moderate unchanged. Review covers fatal
versus requested-stop status, readiness/poll cancellation and replacement ownership,
helper cleanup, generated hidden/waiting VBS exit propagation, Unicode serialization,
all four legacy/new metadata parsers, lifecycle regressions and rollout documentation.
Full summary/controller/drain/manifest and primary hashes independently verified.

Verification adequacy: qualified, NOT unqualified whole-change acceptance.
Manager required guard-event attribution before acceptance. Cheap read-only trace
establishes retained21 category-only entries lack timestamp, PID, hostname, stack
or pytest node; quiet pytest stdout has no event correlation. No exact test mapping
or intended-negative classification can be recovered. Guard blocks remote names
before underlying resolution; literal-loopback resolution can precede port19836
rejection. No successful installed-service HTTP is demonstrated by these entries.

Candidate input inspection does not establish causality: global discovery invalid/
untrusted destination tests parse URLs and assert requests unawaited; registered
trace paths and representative retained-wake/reconnect clients are mocked. The
two-instance Claude outage test uses an in-process opener/offline adapter. Default
Claude hooks catch request exceptions, so an unintended real-service dependency
could be hidden by a denial; no event is attributed to that path from available logs.

State remains Blocked pending manager disposition of this attribution gap. Smallest
proposed closure is a separately allocated private run correlating each guard denial
with PID, current pytest node and bounded sanitized stack/callsite, preserving all
guards/assertions. No further test, instrumentation or production change is approved
or performed here. Green alone does not waive missing attribution; existing evidence
cannot be retrospectively backfilled. Source correction, installed Task Scheduler
acceptance and historical causal diagnosis remain distinct. Manager received exact
pass, source review, gap and proposed next discriminator; publication is not authorized.

Skill feedback considered: runner/runtime mistakes are consumer/environment-owned,
not a demonstrated upstream agent-workflow defect. No upstream report or mutation.

## Attribution-only allocation — before execution

Manager subsequently allocates ONE attribution-only complete run on the same
production source/private harness/guards/assertions with fresh short basetemp.
Earlier6415-pass evidence remains preserved. No production code change, native
qualification, parallel full/profiler, installed mutation or publication authorized.

Before execution, cheap worker prepares only minimal private guard logging delta;
independent smart review must approve exact command/isolation and logging semantics.
Each denial records PID, monotonic timestamp, sanitized current pytest node when
available, fixed category and bounded repo-relative file/function/line stack.
No locals, arguments, parameter IDs, payloads, URLs, query text, tokens or absolute
home paths. Unknown/inherited child context stays explicit; add a minimal node
timeline only if needed. Record before raise; logging failure cannot bypass the
guard or replace the original denial. Preserve existing network policy/configuration,
source freeze, cleanup identity ledger and controller evidence. Root pins the clean
records-only successor before release; no retry. A failure retains its attribution
and failure evidence, not a waiver. Goal is classification of actual calls, not an
additional arbitrary acceptance gate. State remains Blocked pending this result.
