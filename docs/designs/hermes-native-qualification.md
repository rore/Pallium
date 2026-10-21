# Hermes integration validation

This contributor reference describes the integration's validation surfaces and
coverage boundaries. User setup belongs in the
[package guide](../../integrations/hermes/README.md); the
[integration overview](../hermes-integration.md) describes current behavior.

<a id="current-scoped-result"></a>
## Coverage

| Surface | Coverage |
|---|---|
| Linux TUI | Hermes v0.22.0/v0.22.2, built-in-provider memory-off and custom-provider memory-on journeys |
| Windows Desktop and TUI | Both releases, both interfaces, memory off/on; Windows Server 2025 with unpacked apps |
| Relay | Full 16,000-code-point Unicode delivery under default hook spill, reply and no-reply turns, busy delivery, endpoint outage and controlled host/MCP relaunch |
| History and memory | Distinct-session capture/search/expansion, opt-in write/recall/correct/supersede/forget, privacy and preserved profile data |
| Package lifecycle | Install, repeat setup/update, status and removal; unchanged unrelated configuration, plugins and databases |
| Caller boundaries | Trusted identity/generation, stale and ambiguous admission, middleware vetoes, payload limits, concurrent callbacks, 24-hour presence and optional-vector fault handling |

The accepted evidence and retained failures are linked from
[merged PR #324](https://github.com/rore/Pallium/pull/324) and its
[implementation](../../.agent-workflow/tasks/hermes-production-slice4.md) and
[native runner](../../.agent-workflow/tasks/hermes-native-qualification.md) records.
These records preserve exact revisions, receipts and failed attempts; they are
not setup instructions. Reuse evidence only for unchanged surfaces. A later
service exception-path fix needs its own fault tests, not a claim that an earlier
UI journey injected that fault.

## Boundaries

- Runtime admission checks public capabilities, not a hard release allowlist.
  A compatible API check does not establish behavior on every future release.
- Windows Server/unpacked evidence does not qualify Windows 11, MSIX installation,
  the native updater, native app Quit or automatic standalone MCP reconnection.
- Synthetic providers prove configuration, transport and tool dispatch, not model
  quality, every provider/memory combination or arbitrary competing middleware.
- Controlled owned-process relaunch is different from automatic recovery after
  uncertain enqueue, claim or ACK. Preserve uncertainty fences and inspect status.
- Shared Relay availability failures remain unresolved. Keep failed CI and
  unreached assertions visible; later passing evidence does not prove a cause or
  cure. A source or safety finding affecting Hermes still needs investigation.

## Reusing and refreshing evidence

For a documentation-only change, verify commands, tool catalogs, links and current
support statements without rerunning native journeys. For an application change,
identify the affected contracts, run the missing caller regressions, and refresh
only materially affected host evidence. Keep exact source/runtime hashes and
independent review references with the result. Do not combine partial or skipped
cases into a complete matrix or count helper tests as actual UI coverage.

## Disposable Windows runner

Use the existing manual-only
[qualification workflow](../../.github/workflows/hermes-native-qualification.yml).
It checks an immutable candidate, pinned release/runtime sources, sequential
release jobs, no-skip actual UI cases and retained artifacts. Each release job has
a 60-minute timeout. Do not duplicate an active dispatch or rerun unchanged failed
source without an evidence-based next experiment.

Keep dependency builds, Hermes backend, Electron/userData and process-home paths
inside a disposable VM. A temporary `HERMES_HOME` alone does not isolate Desktop
URL registration or install scripts. Use synthetic profiles and loopback
service/provider stubs without real credentials or paid inference. Keep Hermes
source and native updater untouched; use the workflow's separate Hermes/Pallium
Python environments and source/runtime verification.

## Local Linux qualification

Prefer a separate task-owned WSL distribution for Linux work. Leave existing
distributions, defaults and global settings alone. Confine offline test processes
with detached Windows/shared mounts, private mount/PID/user/
binfmt/network namespaces, an unprivileged UID with zero capabilities and
`no_new_privs`, and loopback only. WSL settings and Python network guards alone
are not isolation from Windows executables, mounted drives or host networks.
Use a disposable VM if these controls are unavailable. Never copy everyday
credentials or profiles into the test environment.

## Required observations

Drive the actual composer and rendered answers with normal tool discovery;
correlate tool results and public state by exact returned IDs. For each required
release/interface/memory case, verify:

1. The default catalog, bundled skill, plugin coexistence and private scope.
2. Address/send, full Unicode payload after default spill, one claim/ACK,
   no-reply completion, a later explicit reply and post-reply model continuation.
3. Busy-turn delivery, endpoint outage, stale/foreign/ambiguous identity refusal
   and no unsafe replay after uncertain outcomes.
4. A real new session, later-session History search/expansion and opt-in memory
   lifecycle; memory-off leaves Relay/History functional.
5. Two owned host/MCP generations with old PID/birth/executable identities gone,
   distinct current-session identity, preserved data and completed late privacy
   and egress checks.
6. Repeat setup, status and removal after owned shutdown, comparing configuration,
   unrelated plugins and database inventories/hashes, including SQLite sidecars.

The native journey uses the supported `approvals.destructive_slash_confirm: false`
setting. `/new` still uses normal composer input and requires a different actual
session ID; the optional confirmation overlay is not covered by these checks.

Record the actual OS/image and source/runtime provenance. Require successful
driver/source postconditions and normal identity-safe cleanup of both generations.
Preserve the primary failure through artifact and cleanup errors. Provisional
read-only client-disconnect classification is valid only at its explicit retirement
boundary with normal old-generation cleanup/death and a verified distinct later
session; active, foreign, mutation and unexplained errors stay fatal. A cancelled
or incomplete journey does not qualify its unreached checks.

Do not run Desktop builds or qualification against an everyday installation,
alter a native updater, or promote test launchers into normal use. Isolated test
authorization does not authorize installed rollout.
