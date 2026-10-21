# Hermes native qualification

Status: the user approved the disposable runner in PR #328, subsequently one
additional attempt, and then up to two further disposable-VM attempts in response
to the renewed request on 2026-10-21. Five total attempts including reruns are
authorized within the unchanged four-runner-hour ceiling. Four are consumed;
at most one remains, subject to fresh candidate checks and remaining time.
The isolated environment and evidence may be retained through completion.
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
Before further execution, reconcile actual attempts and conservative elapsed job
time against the unchanged total ceiling; each next run's full worst-case time
must fit. The additional approval does not waive candidate checks or review.
Harness repair and pure replay are not a native pass.
The fourth run
[39557493207](https://github.com/rore/Pallium/actions/runs/39557493207) tested
`f348f00f9b4ef0b6fbf63d0e87df245102318498`: 59 passed and two failed on v0.22.0.
Both memory-off UI journeys completed. Both memory-on cases reached the memory
lifecycle but failed an assertion using the History attribution field for an
ordinary memory query. All four cleanup/source checks passed; v0.22.2 was
cancelled. The corrected assertion is not yet natively qualified.
Conservative elapsed accounting including cancelled jobs totals 5,026 seconds,
leaving 9,374 of 14,400 seconds. The next run's 7,200-second maximum fits.
The user now directs isolated local WSL validation first and remote Windows
qualification last. Existing Windows runner checks remain unchanged.
Hermes remains experimental. This approval excludes local recovery and everyday
installation or rollout.

The remaining integration proof needs real Desktop and Ink TUI journeys. Gateway
RPC tests and test-helper checks establish narrower contracts. The current
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
on v0.22.0; v0.22.2 native build/execution remains unverified by this workflow.

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
Complete useful local validation before spending the remaining remote attempt.

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
every provider/memory combination. Required CI and final Windows qualification
remain separate gates.

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
with TUI. Mocked adapter checks do not establish Desktop qualification. The full
native matrix remains unaccepted. The shared fixture now recognizes only the
authored scope suffix on exact memory stages and waits for the actual Desktop
submit control to mount; unexpected stage text and ambiguous controls still fail.
It also checks an enabled, harmless peer hook and a bounded forwarding-endpoint
outage before the first no-reply wake. These additions require native proof;
endpoint downtime does not establish full service-process or MCP restart recovery.
The next candidate also splits each journey into two owned process generations
using the same synthetic profile. It verifies exact old PID/birth/executable
identities are gone before and after relaunch, then requires a real new-session
MCP call and persisted memory/History reads. Desktop userData reuse requires the
same prior profile/runtime/source, successful dispatcher cleanup and contained
non-reparse paths. Both legs retain separate evidence. This is controlled
owned-tree teardown and relaunch, without a graceful native Quit or automatic
standalone MCP-reconnect claim. Native proof remains pending.
Python network guards do not confine Electron/Chromium networking, and hosted
runner environment markers are only accidental-launch guards, not an OS sandbox.
The recorded approval covers this disposable runner and its bounded manual runs.
It does not authorize changing everyday applications, services, settings, data,
installation or updater behavior.
