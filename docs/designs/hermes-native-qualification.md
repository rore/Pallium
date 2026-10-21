# Hermes native qualification

## Current scoped result

Independent review accepted all eight actual Windows UI cells in native run
[39650756737](https://github.com/rore/Pallium/actions/runs/39650756737), candidate
`d5896a24ec3b72c1f23f5323e43ab8d2a06e60ca`. Both release jobs passed 83 checks
with zero failures, errors or skips: v0.22.0 in 420.693 seconds and v0.22.2 in
394.092 seconds. They ran on Windows Server 2025 with unpacked builds and
synthetic providers. The package remains experimental pending human release
acceptance; everyday installation remains a separate rollout decision.

Native15's application was `b96a05e1cb7b7046243398922ccd497750807548`;
`d5896a24` preserved that application and added the test probe's JSON transport
correction and regression. The shared Windows/Linux journey passes a complete
16,000-code-point Unicode wake through
to the provider, followed by a short reply wake, retaining admission, privacy
and cleanup checks. Separate deterministic caller E2E covers the 24-hour
liveness boundary and uncertain outcomes.

The later production head `a48b0fef48d91868ffefd903742ef025e66ceeed` corrects
exactly two logger bindings in optional vector-failure catches. Native15 and
the Linux matrix remain evidence for unchanged host/plugin/MCP normal behavior;
they did not inject these service faults or test this exact whole application.
Direct HTTP E2E covers vector import and construction failures across remember,
correct and supersede, plus remember vector-persistence failure and unchanged
lexical-failure propagation/persistence timing. Before the fix, seven cases
failed with `NameError` and the lexical control passed (5.33 seconds). Afterward
all eight passed (3.39 seconds); the affected memory HTTP/E2E/storage subsystem
passed 178 tests with zero failures, errors or skips (57.76 seconds). Clean
review accepted reuse of the existing native evidence without another host run.
Independent technical review accepted the corrected source, actual main
composition, final prose and distinct failed CI classifications. Corrected-head
human acceptance remains pending; the earlier release acceptance applied to
`5f21bfcb`.

Corrected-source [CI 39667217842](https://github.com/rore/Pallium/actions/runs/39667217842)
remains **failed**. Python 3.13 stopped at the unchanged Codex ordinary/mismatched
fence test's second send (`mismatch` / `mismatch-fenced`): HTTP 503 `relay_busy`
after 1600 ms, with `late_begin` and `setup_pragma` at 1599 ms. Registration and
the ordinary send succeeded; fence creation, claims and preservation assertions
were not reached. It recorded 3242 passes, 22 skips and one expected failure in
296.99 seconds. Clean review accepts shared availability classification under
the task owner's proceed policy, without establishing a cause or cure.

Python 3.12 separately failed
`test_first_cancelled_mcp_admission_records_validated_reply[registered]`: its
one-second wait for the mocked registration callback did not complete, with
`retained-register-registered-ok` reported by the Codex bridge during cleanup
after the worker was released. The cancellation notification was not sent;
cancellation-response, validated-reply logging, disposal and no-operation
assertions were not reached. It recorded
3147 passes, 16 skips and one expected failure in 349.75 seconds. This is a
distinct failure, not the Python 3.13 send's HTTP 503. Neither lane is a passing
full-suite result. Clean review found no demonstrated Hermes safety regression:
the unchanged Codex retained lifecycle is not enabled by the Hermes server, and
the new memory logger bindings do not affect that path. The missed deadline's
cause remains unknown; this is no cancellation-success or identity-safety proof.
Windows smoke passed 626 tests with seven skips in 164.20
seconds; [governance 39667217848](https://github.com/rore/Pallium/actions/runs/39667217848)
passed. Both Linux logs and the reviewed merge-source receipt are retained.

The journey also checks the actual pinned `hook_output_spill` helper
inside the gated disposable runtime: its default 10,000-character limit spills
the long synthetic text into an owned file but preserves the short placeholder.
Actual UI execution then proves public request-middleware expansion and the raw
complete-context admission gate with unchanged host spill settings. Earlier
request middleware sees only the placeholder; later filters can inspect or veto
full context. The helper proof uses per-call test output paths, not global or
profile configuration changes.

| Hermes source pin | Surface | Memory | Result | Duration |
|---|---|---|---|---:|
| v0.22.0 `e06df9c2` | TUI | Off | Passed | 83.873 s |
| v0.22.0 `e06df9c2` | TUI | On | Passed | 168.307 s |
| v0.22.0 `e06df9c2` | Desktop | Off | Passed | 67.003 s |
| v0.22.0 `e06df9c2` | Desktop | On | Passed | 85.642 s |
| v0.22.2 `d923a5eb` | TUI | Off | Passed | 78.356 s |
| v0.22.2 `d923a5eb` | TUI | On | Passed | 145.234 s |
| v0.22.2 `d923a5eb` | Desktop | Off | Passed | 70.326 s |
| v0.22.2 `d923a5eb` | Desktop | On | Passed | 85.781 s |

All journeys passed busy-turn delivery, History, privacy/source assertions,
profile preservation, post-drain error audit, driver exit 0 and normal
two-generation cleanup. Memory-on cases completed the optional-memory lifecycle.
All final audits recorded zero cancellations and zero fatal errors. Windows
evidence used Server 2025 and unpacked apps; it does not qualify Windows 11,
MSIX or updater behavior, native app Quit, or automatic standalone MCP
reconnection. Linux TUI passed both pins separately: default-off used the built-in
`openai-api` configuration, while memory-on used a custom synthetic provider.
Windows cases used synthetic providers. Paid-provider quality and every
provider/memory combination remain untested. Runtime admission is capability
based and is not hard-pinned to these release versions.

Earlier candidate CI [39650707590](https://github.com/rore/Pallium/actions/runs/39650707590)
remains failed. Python 3.12 passed the full non-slow suite: 7,921 passed, 93 skipped and
two expected failures in 529.37 seconds. Python 3.13 failed at generic
Codex/Claude registration before hook assertions: HTTP 503 `relay_busy` after
1,949 ms, with `setup_deadline` / `session_factory` at 1,947 ms. It recorded
3,131 passed, 22 skipped and one expected failure in 365.80 seconds; the exact
failed iteration is unknown. Windows passed, as did governance
[39650707403](https://github.com/rore/Pallium/actions/runs/39650707403).
Independent review classified this as unchanged shared availability under the
task owner's explicit policy allowing Hermes work to proceed alongside those
failures. The failure remains an availability limitation; the Hermes changes
do not repair it.

The later predecessor `5f21bfcb` also retained failed generic Codex recovery CI
with `late_begin`. That recovery failure is distinct from `d5896a24`'s initial
registration HTTP 503 above; neither failed receipt is reclassified by the
vector-logger repair or by the successor CI.

Earlier failed receipts remain failed historical evidence. No read reset
occurred in the accepted matrix, so its success does not establish a cure for
the earlier unexplained resets. Separate focused real-loopback tests exercise
the explicit retirement cancellation boundary.

## Prior candidate diagnostics

Native run [39648573274](https://github.com/rore/Pallium/actions/runs/39648573274)
on `b96a05e1` failed all four v0.22.0 UI cases before launch in the spill-helper
probe: 78 checks passed and four failed in 43.308 seconds; v0.22.2 was cancelled.
The parent sent UTF-8 JSON through a pipe decoded by the Windows child using its
locale and `surrogateescape`; the helper correctly refused surrogate-containing
UTF-8 output. The test-only correction uses ASCII JSON escapes, matching the
existing driver transport. Its real-child `cp1252:surrogateescape` regression
failed before the fix (one failure, 1.22 seconds) and passed afterward (one pass,
0.59 seconds), preserving the exact 16,000-character payload and output file,
helper defaults, placeholder and containment checks. Native15's pass does not
reclassify native14.

Independent review previously accepted the shorter journeys in
[39626758387](https://github.com/rore/Pallium/actions/runs/39626758387), candidate
`b3601c79a8269e8a734450c67e9e40c3e330b9fb`, with 81 passing checks and zero
failures, errors or skips per release. Later full-package reviews found ordinary
registration expiry and long-payload/spill blockers. That historical matrix did
not cover the corrected lifetime and maximum-payload boundaries now proved above.

Run [39617852210](https://github.com/rore/Pallium/actions/runs/39617852210), candidate
`143683d650692aff52b7633cdbde4402ced0e966`, passed 66 v0.22.0 checks and failed
one, with zero skips in 396.29 seconds. Both Desktop memory modes completed
through Ctrl+N, and TUI memory-on passed. TUI memory-off reached History before
another read-only poll response reset; later privacy/profile checks were not
reached. Its failed poll belongs to the original process generation, with a
different session used after relaunch. Timing and cause remain unknown, and
this case stays failed. v0.22.2 was cancelled. Full CI on this candidate passed
both Linux lanes, Windows and governance; that does not cure prior incidents.

At that stage, the proposed fixture marked only the exact original poll scope immediately
before its intentional process retirement. A completed HTTP 200 read response
cancelled during that explicit boundary can be recorded provisionally, then
accepted only after normal cleanup, old-generation death and a distinct later
session are proved. Active/unmarked cancellations, mutations, non-200 responses,
forwarding failures and unknown errors remain fatal. No second HTTP 500 is sent
after response writing starts. A real-loopback cancellation/state/recovery test
and a final audit after handler drain must pass before another native attempt.
The earlier failed receipts are not reclassified as passes.

Run [39612888749](https://github.com/rore/Pallium/actions/runs/39612888749), candidate
`480c0613075869503f21ada404a263a23ce47811`, failed three v0.22.0 checks with
64 passed and zero skips in 329.79 seconds. Both Desktop cases failed at the
second process generation's initial New session: the driver required an
optional sidebar row that did not yield one visible match. The captured error
does not distinguish match count from visibility. TUI memory-off completed;
TUI memory-on reached History and distinct-session checks, then failed on a
read-only pending-candidate GET whose HTTP 200 response write hit a client reset.
The cancellation trigger is unknown. Later privacy and profile lifecycle
assertions were not reached. Parent source and owned-process cleanup passed in
all four cases; v0.22.2 was cancelled. The failed cases remain unqualified.

The next reviewed driver uses the default Windows Ctrl+N fresh-session command
from the ready composer, once with the existing timeout, then observes `#/`
and checks the composer. Both pins support this public command independently
of sidebar visibility. Its handler resets fresh-draft UI state without an idle
guard; it does not prove server work completed. Initially fresh remains a
route-state barrier, with actual distinct-session assertions still required.
No shortcut override, private state, fallback, retry, timeout increase or
application change is introduced. The read-reset assertion stays fatal.

Run [39605845935](https://github.com/rore/Pallium/actions/runs/39605845935), candidate
`c73f383e3d06af0b3fab878b96ca6163dfa81fb4`, passed all 67 v0.22.0 checks with
zero skips in 391.703 seconds. Independent review accepted its four full UI
journeys, including distinct History sessions, two normal process generations
and profile lifecycle checks. v0.22.2 passed 66 checks and failed Desktop
memory-on while waiting for the History answer after New session and Enter
returned. The captured provider and HTTP evidence contains no History prompt,
query or answer; this does not establish all internal effects or justify a
submission retry. Later privacy and profile lifecycle checks were not reached.
Parent source and cleanup checks passed in all four cases. Six structured
process records show newer PID replacements left untouched. Seven passing UI
cells do not qualify the eight-cell matrix.

The driver in that next candidate selected the sidebar navigation row instead
of the similarly named asynchronous header-plus action. It clicks once, waits
for the observable fresh-chat hash route `#/`, then checks composer readiness
and empty text. An initially fresh route is a state barrier rather than proof
of a transition; actual later-session identity checks remain required. This is
a test-caller correction, with no forced navigation, action retry, increased
timeout or application change. Its visibility precondition failed in run
39612888749 above; native qualification remained incomplete at that point.

Run [39603091244](https://github.com/rore/Pallium/actions/runs/39603091244), candidate
`f0da4ee1b2534da1b7ab9f3e94f41740dea8cbd3`, progressed through Desktop memory-on
History submission using plain Enter and the later egress/secret assertions. It
failed at driver shutdown before the profile lifecycle checks: Windows had reused
an exited owned console process's PID for a newer system process, and the cleanup
fence correctly refused to kill that replacement. The aggregate was 61 passed,
one failed in 362.34 seconds; the other three v0.22.0 UI cases passed and v0.22.2
was cancelled. The full Desktop case remains unqualified.

The reviewed fixture correction recognizes only a strictly newer creation time
as proof that the saved owned identity has exited. It records both identities
and leaves the replacement untouched and outside its wait list. Every kill still
requires the exact saved creation time and executable; unresolved mismatches and
inspection errors remain fatal. This changes Windows test-process accounting,
not application cleanup or the user's installations. Fresh full-journey proof is
still required, including the profile lifecycle that this run did not reach.

Run [39598460905](https://github.com/rore/Pallium/actions/runs/39598460905), candidate
`534b546936ce9d9a2fb0d5a1e8415302c9c6b652`, again failed v0.22.0 Desktop memory-on
at History submission after New session (61 passed, one failed in 392.12 seconds).
The new failure snapshot shows that click was entered, Send initially resolved
then became invisible, and the visible composer was empty without a submit
control. No History query or prompt appears in captured HTTP/provider evidence;
this does not prove all internal effects or justify resubmitting. The other three
UI cases passed. Parent source/cleanup passed in all four, but the failed driver
exited 1 and its full journey remains unqualified. v0.22.2 was cancelled.

The next reviewed driver uses the visible editor's ordinary plain Enter handler
as its first and only submission action. Both pinned releases read live editor
text on that path. It retains existing form/control readiness gates, then binds
one editor, checks its exact nonempty payload and presses Enter once on that
same element. Cleared, missing or detached input fails; there is no refill,
fallback or retry after an ambiguous action. These gates do not prove idle state.
This changes the test's caller mechanism; it does not repair or qualify the
failed Send-button route. At that point, the integration and Windows matrix
remained experimental pending native proof; the scoped matrix later passed as
recorded above. The failed Send-button route itself remains unqualified.

At that point Windows qualification remained incomplete. Diagnostic run
[39593293647](https://github.com/rore/Pallium/actions/runs/39593293647), candidate
`d5b7e3d9644801472674e1310aa484a7da75a62e`, passed three v0.22.0 UI cases but
failed Desktop memory-on while submitting History after New session. The submit
operation timed out waiting for its control; child cleanup also refused a changed
process identity. Parent source and cleanup checks passed, but the driver failed
and that case remains unqualified. The failed UI state and observed process
identity were not captured. No HTTP server error occurred; this does not explain
or cure the earlier response-write abort. Attempt 2 tried to continue only the
cancelled v0.22.2 job, but fail-fast cancelled it without executing any steps.
No additional second-release evidence resulted. The next fixture changes add
bounded failure diagnostics while preserving the original errors and guards.

Earlier run [39588545910](https://github.com/rore/Pallium/actions/runs/39588545910)
tested candidate `b13a3dd29eefc243ef0b10920fdd6b2d33aefbde`: v0.22.0 passed all
61 checks in 360.95 seconds; v0.22.2 passed 60 and failed one in 417.18 seconds.
Its TUI memory-off case recorded a fatal API response-write
`ConnectionAbortedError(10053)`. The failed operation is unidentified, and the
case remains unqualified pending investigation.

Independent review accepted all four v0.22.0 Desktop/TUI memory-off/on cells in
earlier run [39586401041](https://github.com/rore/Pallium/actions/runs/39586401041)
on `7df9975dd6e6176e5c0a8b5b046e173179f62e97`. That aggregate failed a pure-helper
cleanup mock. The task's cumulative run cap has since been removed; per-job
timeouts and isolation remain. Shared-test availability failures on Python 3.12
and 3.13 remain recorded and were not repaired by the Hermes changes.

## Earlier qualification receipts

The runner is merged; the first run is
[39474582150](https://github.com/rore/Pallium/actions/runs/39474582150), testing
candidate `973f21902168bb81ef2fdc7fe629cecad836ff27`. It failed four native cases
after 30 helper checks passed; the second release was cancelled by fail-fast.
Evidence showed initial real UI/skill/Relay/wake progress, followed by fixture
scope matching, metadata-response and Desktop-control readiness failures.
Those partial observations do not qualify the full integration. The second
run [39483789032](https://github.com/rore/Pallium/actions/runs/39483789032) tested
reviewed candidate `91ffe1ad3158786f922c57ba5ed11e024cad9390` after full CI passed.
It failed three native cases after 42 checks passed, including the complete
v0.22.0 Desktop memory-off journey. TUI off/on failed rendered-text observation;
Desktop memory-on rejected a legitimate mixed memory/History query response.
Fail-fast cancelled v0.22.2. Owned cleanup and source postconditions passed in
all four cases.

The additional approved run
[39490754190](https://github.com/rore/Pallium/actions/runs/39490754190) tested
`b29299499cab10871cafd54e35ffdcdc6402940e` after required CI passed. It failed
three native cases after 58 checks passed. Desktop memory-off completed again;
both TUI cases crashed the screen observer on an empty wide-character continuation
cell, and Desktop memory-on rejected a valid nullable expansion field. Fail-fast
cancelled v0.22.2. All four owned-cleanup and source postconditions passed.
This is historical approval and attempt accounting; subsequent user direction
removed the cumulative cap. Harness repair and pure replay are not a native pass.
The fourth run
[39557493207](https://github.com/rore/Pallium/actions/runs/39557493207) tested
`f348f00f9b4ef0b6fbf63d0e87df245102318498`: 59 passed and two failed on v0.22.0.
Both memory-off UI journeys completed. Both memory-on cases reached the memory
lifecycle but failed an assertion using the History attribution field for an
ordinary memory query. All four cleanup/source checks passed; v0.22.2 was
cancelled. The corrected assertion was not yet qualified at that stage; the later
accepted matrix does not change that failed receipt.
At the time of the fourth run, conservative elapsed accounting including
cancelled jobs totaled 5,026 seconds, leaving 9,374 seconds under the then-current
14,400-second cap. Later user direction removed that cap. The user’s preference
for local WSL validation before remote Windows qualification was fulfilled for
this candidate and remains the order for future material changes.
At that stage Hermes remained experimental pending the then-current Windows
matrix. The approval excluded local recovery and everyday installation or
rollout. The accepted scoped result is recorded at the top; the package remains
experimental pending human release acceptance.

At that stage, the remaining integration proof needed real Desktop and Ink TUI
journeys. Gateway RPC tests and test-helper checks establish narrower contracts. The then-current
[qualification matrix](../../integrations/hermes/README.md#production-qualification-in-progress)
remains authoritative about unqualified behavior.

## Disposable Windows runner

Use one manual-only GitHub Actions workflow, with `contents: read`, no
credentials, no publishing, no scheduled runs and no changes to existing CI or
branch protection. Run releases sequentially with fail-fast cancellation,
concurrency protection and a 60-minute limit per release. Use only synthetic
profiles and loopback service/provider stubs; no paid inference.

GitHub requires a manual workflow to exist on the default branch before it can
be dispatched. Land an approved runner-only change separately. Dispatch that
registered workflow on main with a required full candidate commit input, and
verify its checkout before source execution and again before qualification.
The feature branch need not contain the runner workflow. Do not merge an
unqualified feature merely to register its test workflow. See
[GitHub's manual workflow instructions](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/manually-run-a-workflow).

| Release | Immutable source revision |
|---|---|
| v0.22.0 | `e06df9c2eae6901f4c88f464e0ae6e753c0428b8` |
| v0.22.2 | `d923a5eb487a17c0a68801bba9ef0f56c81040a8` |

Each job prepares separate Pallium Python 3.13/MCP SDK1 and Hermes Python
3.14.6/MCP SDK2 environments. Preserve Hermes's Python lock and source workspace
scripts. Both pinned sources declare uv 0.12.3 in `pm/lock.json`; verify its
Windows x64 archive hash before executing it from runner temp. Use supported Node
24 and task-local npm 11.9.0, including nested npm scripts. Build the TUI using
`npm run build --workspace ui-tui` and the unpacked Desktop using
`npm run pack --workspace apps/desktop`. Fail explicitly on each native command
error and missing or ambiguous output; do not install MSIX packages or patch
upstream source. Build prerequisites and the unpacked executable layout passed
on v0.22.0; native builds/execution for both pins were subsequently verified in
the accepted run documented above.

Dependency install scripts and Desktop startup can write outside redirected
profile paths. A temporary profile does not isolate those effects: Windows
dependency builds and native Desktop/TUI qualification use a disposable VM.
Tests must fail closed outside that approved runner, preserve owned-process
identity, and clean up only their own process trees. TUI tests additionally use
child-level network guards and self-checks; these are not an OS sandbox.

## Local Linux qualification

Develop and validate Linux behavior in a separate task-owned WSL2 distribution,
leaving existing distributions, defaults and global WSL settings unchanged.
WSL settings alone are not a Windows security boundary. The reviewed lane uses
private mount/PID/user namespaces, detaches shared host mounts, installs an empty
private binary-format registry, and drops all capabilities with `no_new_privs`.
Dependency bootstrap has separate network access. Application tests use a fresh
network namespace with loopback only and synthetic profiles, providers and data.
Bound process count, CPU use and command duration; preserve owned cleanup evidence.

A root-protected per-run manifest binds the live namespaces, UID maps, launcher
identity and mount state. The Linux TUI gate verifies those values before setup
or launch and never supplies GitHub runner markers. The shared journey uses a
POSIX terminal adapter; Windows Desktop and ConPTY gates remain unchanged.
Preinstall the hash-pinned screen observer during bootstrap and verify its
receipt offline. Copied venv interpreters preserve the intended SDK environment
when native setup resolves interpreter paths.

On candidate `2943fc75`, local subsystem checks passed 234 with three skips;
released Gateway E2E passed on both pinned hosts, and the two SDK2 bridge cases
previously skipped for missing prerequisites subsequently passed. These are
Linux subsystem/Gateway results, not native TUI or Windows Desktop acceptance.
Complete useful local validation first. The local WSL pass remains the preferred
step before remote qualification for future material changes.

The complete Linux TUI journey subsequently passed with memory off and on for
both pinned releases on clean candidate `1896605eef514e76f77b454afea44a92463aaed9`:
v0.22.0 took 106.15 seconds and v0.22.2 took 107.72 seconds. Independent review
verified all four non-skipped cells, clean source and owned-process cleanup,
two distinct host/MCP generations, later-session History and the optional-memory
lifecycle. These runs use the custom synthetic provider.

On composed candidate `13029e3847b756b70cf387b4e0344262d0bf27a8`, the same two
Linux cases passed on both releases again: v0.22.0 in 115.69 seconds and v0.22.2
in 109.08 seconds. Memory-off now exercises the supported built-in `openai-api`
configuration with explicit chat-completions mode and synthetic credentials/URL
supplied only through the isolated environment. Each release recorded 31 matching
chat-completions requests; the profile contained neither key nor base URL, and
both inspected MCP generations omitted both provider variables. Memory-on retains
the custom provider and complete optional-memory lifecycle. Independent result
review accepted all four non-skipped cases and cleanup/source postconditions.
This covers integration transport and configuration, not paid-model quality or
every provider/memory combination. These Linux results supplement the later
Windows matrix and required CI results documented above.

The host-qualified application `b96a05e1cb7b7046243398922ccd497750807548`
passed all four actual Linux TUI cases again, independently accepted with zero
failures, errors or skips. The v0.22.0 suite took 115.475 seconds and v0.22.2
112.384 seconds. Memory-off used built-in `openai-api`; memory-on used the custom
synthetic provider. The complete 16,000-code-point payload, subsequent reply,
History, memory, two normal host/MCP generations and profile preservation passed.
The later `d5896a24` probe transport correction left that application unchanged;
the subsequent `a48b0fef` service exception-path change has the HTTP proof above.

Record the actual runner image and Windows version in every native result.
Hosted Windows Server evidence must not be described as Windows 11 or installed
MSIX qualification. The Pallium release gate covers its profile
install/update/remove lifecycle while preserving unrelated settings and data.
Hermes's own installer, updater and OS support remain upstream contracts; this
integration neither replaces them nor claims untested package/OS coverage. See
the [GitHub runner images](https://github.com/actions/runner-images) and
[upstream Desktop build contract](https://github.com/NousResearch/hermes-agent/blob/v0.22.2/apps/desktop/BUILDING.md).

## Required observations

Drive real composer input and rendered answers with default Tool Search, then
correlate public state reads with actual tool results. Cover Relay address/send,
an incoming no-reply turn followed by an explicit reply, a new conversation and
later-session History search/expansion, and opt-in memory lifecycle with
memory-disabled independence. Preserve synthetic terminal/UI, provider, HTTP and
JUnit evidence. A scripted provider proves native integration transport and
dispatch; it does not qualify ordinary providers or competing middleware.

The shared journey now has independent TUI/Desktop and memory-off/memory-on
cases. It drives the actual composer and default Tool Search, remembers in one
session, then recalls and mutates in a verified different session. Returned IDs,
expansion payloads, supersession and forgetting are checked through public reads.
The synthetic profile uses the supported
`approvals.destructive_slash_confirm: false` option: `/new` still uses composer
input and requires a fresh success plus a different actual caller session ID,
but this matrix does not qualify the upstream confirmation overlay.
After the owned UI tree stops, the same profile undergoes repeat setup/update,
status and removal. Database inventory and hashes include SQLite sidecars and
are compared after each step, alongside unrelated settings, plugin metadata and
a Unicode note. Removal must delete only Pallium-owned package entries/files.
The Desktop adapter uses the owned unpacked executable and a numeric-loopback
Chromium CDP endpoint; it shares the identity-checked watchdog and cleanup ledger
with TUI. Mocked adapter checks do not establish Desktop qualification. The
accepted run above now covers the full scoped native matrix. The shared fixture
recognizes only the
authored scope suffix on exact memory stages and waits for the actual Desktop
submit control to mount; unexpected stage text and ambiguous controls still fail.
It also checks an enabled, harmless peer hook and a bounded forwarding-endpoint
outage before the first no-reply wake. These checks passed in the current matrix;
endpoint downtime does not establish full service-process or MCP restart recovery.
The current journey also uses two owned process generations
using the same synthetic profile. It verifies exact old PID/birth/executable
identities are gone before and after relaunch, then requires a real new-session
MCP call and persisted memory/History reads. Desktop userData reuse requires the
same prior profile/runtime/source, successful dispatcher cleanup and contained
non-reparse paths. Both legs retain separate evidence. This is controlled
owned-tree teardown and relaunch, without a graceful native Quit or automatic
standalone MCP-reconnect claim. The current result is recorded above.
Python network guards do not confine Electron/Chromium networking, and hosted
runner environment markers are only accidental-launch guards, not an OS sandbox.
The recorded approval covers this disposable runner and its bounded manual runs.
It does not authorize changing everyday applications, services, settings, data,
installation or updater behavior.
