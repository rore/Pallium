<!-- agent-workflow:start -->
**Outcome:** Native Windows Claude exact-session wake is qualified only for verified-idle sessions; Channels is unavailable in the qualified environment, and production remains passive until coordinator dedupe, admission, fallback, and cross-platform gates are implemented.

**Target:** Claude Code wake ingress qualification.

**Scope:** Work Record; sanitized evidence; `docs/designs/017-relay-wake-phase0.md`; relevant roadmap item(s); ignored `.local/` disposable probes; one official Claude self-update from 2.1.246 to at least 2.1.248 only if it is noninteractive and does not change user settings or terminate existing sessions.

**Constraints:** No production adapter, coordinator, database/schema, dashboard, dependency, or existing-user-session changes. Do not expose a socket path, token, or secret in model context, Relay, arguments, files, output, logs, responses, or commits. Windows live proof only; no soak test. Runtime remediation is limited to the official Claude self-update; stop on prompts, broader changes, settings mutation, or existing-session impact.

**Completion criteria:** A two-disposable-session Windows probe either proves one candidate's exact-target admission and required Phase 0 observations without secret exposure, or records a bounded passive-only/unknown verdict with stop evidence.

**Risk:** Elevated

**Complexity:** Moderate

**Reason:** Intended committed paths are blue-zone documentation and workflow metadata, but live cross-session ingress and private-frame handling are security-sensitive and have meaningful multi-session uncertainty; engineering judgment raises the task to Elevated.

**Discovery:** `docs/designs/017-relay-wake-phase0.md` keeps Claude passive-only: Path A needs a disposable Windows proof and a correlated `Stop`-hook admission; it rejects `UserPromptSubmit` as the idle signal. PR #80's `ClaudeWakeRegistry` is memory-only (900 s TTL), hides token/socket values from representation, and has no public probe/trigger surface. `claude --version` reports 2.1.246. Official Channels documentation describes hidden preview flags, so absence from local `--help` is not an availability verdict; the isolated development-channel preflight must exercise the documented hidden flag. The roadmap’s earlier Path-A feasibility claim conflicts with the newer design/code evidence; this task uses the latter until a live trace proves otherwise.

**Material assumptions:** (1) Disposable Claude sessions can be launched and addressed without touching existing sessions; Claude owns session identity unless the installed CLI explicitly confirms `--session-id`, and any ambiguous target ownership stops the probe before a send. (2) The PR #80 memory-only boundary supplies secrets only out of model-visible surfaces; disprove by any required secret serialization, then stop. (3) An isolated Pallium app/probe process can receive the disposable hook registration into its in-memory `ClaudeWakeRegistry` and invoke an injected transport in that same process without a public trigger or secret serialization; if existing composition cannot do this without production edits, Path A is blocked. (4) Channels can be enabled with the documented hidden development flag, a temporary MCP config/server, non-secret per-session probe identity, and no persistent user configuration; unexpected permission/organization blocks or mutation outside `.local/` stop that path.

**Plan:** (1) Invoke agent-workflow and establish this record before edits. (2) In ignored `.local/`, prepare one PowerShell launcher with two isolated scratch/config directories, start only two fresh Claude processes (never `--resume`/`--continue`), use Claude-owned identity unless `--session-id` is explicitly supported, record only non-secret probe IDs/PIDs privately, and tear them down at the first stop condition. (3) Exercise Channels first using the documented hidden development-channel flag, a temporary MCP config/channel server, per-session non-secret identity, loopback ingress, and no persistent user config; expected local development-channel consent is allowed. (4) If Channels completes or reaches a bounded stop, investigate Path A only through an isolated Pallium app/probe process whose in-memory registry receives the disposable hook registration and whose injected internal transport performs the pipe call in the same process. Add no public trigger and serialize no secret; if existing composition cannot support this without production edits, record Path A blocked. (5) Preserve token/socket values only in target hook → loopback memory; command lines, markers, Relay text, logs, evidence, and commits contain only non-secret IDs. Do not inspect registries or target-process environments. (6) For each path that passes preflight, use one non-secret marker at a time and capture sanitized evidence for exact targeting, idle distinct-turn admission, busy non-steering (or documented unavailable plus fallback), duplicate, closed/restart, and transport ACK distinct from admission. (7) Stop immediately on ambiguous targeting, existing-session contact, secret exposure/persistence, unexpected permission/organization block, mutation outside `.local/`, missing safe Path-A composition/frame proof, busy steering, or process escape. A stop yields passive-only/unknown evidence; no workaround or retry. (8) Commit only sanitized evidence and concise design 017/roadmap updates, then run workflow/redline checks and request final review. (9) Because 2.1.246 exposed neither Channels nor a messaging registration, inspect only the official self-update help/install source; if its supported noninteractive path can reach >=2.1.248 without settings changes or existing-session termination, run it once and rerun each disposable preflight once. Otherwise finalize passive-only without another installer or workaround.

**Verification plan:** When a candidate passes preflight and is exercised, evidence shall show an exact disposable target and separate admission outcome versus transport ACK → sanitized probe transcript and design update. When any stop condition occurs, no additional sends shall occur → launcher/process lifecycle record and Work Record evidence. When no candidate satisfies the security/admission gate, design 017 shall remain passive-only → reviewer-visible verdict. Workflow fields and final changed paths shall validate → agent-workflow/redline checks.

**Plan review:** Approved with corrections by manager/architect `codex:@relayarch`; see `## Plan review`.

**Approvals:** Not required at this risk level.

**Exceptions:** —

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

- 2026-08-28: Branch created from `origin/main` at `242e3120c106df254ea7e47c6e0e460c9e8d844b`; agent-workflow invoked and record initialized before edits.
- 2026-08-28: Focused discovery completed. The current secure registry lacks a public live-send seam. Official docs identify Channels flags as hidden, so availability must be tested through an isolated temporary development-channel launch rather than inferred from `--help`.
- 2026-08-28: Architecture review approved Channels-first qualification and narrowed Path A to same-process isolated composition. Planning corrections are recorded; no disposable session or probe has run yet.
- 2026-08-28: First live qualification stopped safely: Channels reported unavailable; the headless worker reached the isolated app but exported no messaging registration, so no pipe was opened. Architecture review authorized one official self-update to the documented >=2.1.248 floor and one rerun per path; no alternative installer or workaround is allowed.
- 2026-08-28: Official supported self-update completed noninteractively: Claude Code 2.1.246 → 2.1.250. Existing non-disposable sessions were not terminated; persistent Claude settings and MCP configuration were unchanged.
- 2026-08-28: Fresh isolated Channels preflight on 2.1.250 still reported Channels unavailable and ignored the documented hidden development-channel flag. No plugin or persistent configuration was installed.
- 2026-08-28: Path A succeeded on native Windows through the approved same-process boundary. A fresh exact disposable idle target registered through the normal hook, an authenticated transport write occurred, a distinct model-visible turn started, and Claude returned the unique marker. A simultaneous non-target disposable session remained untouched.
- 2026-08-28: Native duplicate suppression failed: two byte-identical frames with the same message ID produced two queue operations and two user admissions. Pallium must deduplicate before transport and suppress blind ambiguous retries.
- 2026-08-28: Busy behavior is not Relay-safe. During a deterministic 25-second tool call, native ingress joined the active turn; Claude completed the original request and did not process the wake as a distinct later request. The adapter may advertise only `idle_wake`; busy must defer or fall back.
- 2026-08-28: Closed-session transport failed with a missing-endpoint error; fresh runtime launches re-registered successfully. A stale endpoint is never reusable. The isolated harness made two rejected open attempts before its bounded timeout and sent no frame; production must make one coordinator-owned attempt and release fallback.
- 2026-08-28: Live probes ended. No production adapter, coordinator, schema, dashboard, dependency, or tracked test code was added. Windows results do not qualify macOS/Linux UDS behavior.
- 2026-08-28: Process record: `apply_patch` failed with the documented Windows process-creation error, so tracked documentation updates used narrowly scoped deterministic PowerShell replacements. An initial isolated-config attempt briefly copied the opaque Claude login credential file into ignored `.local`; work stopped immediately, the exact copies were verified and deleted before any Channel launch, and no content was inspected, logged, relayed, or committed. Subsequent probes used normal authentication with strict temporary MCP configuration and no persistent settings/plugin change.

## Evidence

- Installed CLI preflight: `claude --version` → 2.1.246. Hidden preview flags are intentionally absent from `--help`, so this is version evidence only.
- [Claude Code Channels documentation](https://code.claude.com/docs/en/channels) describes a research-preview startup opt-in with plugin, sender-gating, and organization requirements; this is not an installed-runtime admission proof.
- Official update evidence: supported updater completed at 2.1.250; the required feature floor was met without an alternate installer.
- Channels evidence: fresh disposable launches at 2.1.246 and 2.1.250, using strict ignored temporary MCP configuration and the documented hidden flag, both reported the feature unavailable.
- Exact/idle evidence: one exact target received and answered a unique marker in a distinct turn; the concurrently live non-target had no marker; sanitized transport write and target-history admission were correlated separately.
- Duplicate evidence: one message ID written twice yielded two queue-operation records and two user records in only the addressed target.
- Busy evidence: target history showed the launch-time user request, active tool call, injected marker inside that active turn, and the original `ACTIVE-DONE` response; there was no distinct wake response.
- Closed/restart evidence: after target exit, transport returned only a missing-endpoint error; each fresh disposable launch produced a new valid registration and successful later idle proof.
- Security evidence: probe logs contain only event names, non-secret markers, message IDs, counts, and error types. Socket/token values remained hook → loopback registry → injected transport memory and are absent from tracked changes.

## Plan review

Manager/architect review required four corrections: do not infer Channels availability from hidden help; qualify Channels first with isolated temporary configuration and authorized local consent; limit Path A to an isolated same-process Pallium composition that preserves the memory-only secret boundary; and use Claude-owned session identity unless `--session-id` is explicitly supported. All four are incorporated above. Live work may proceed under the recorded stop conditions. A later bounded review authorizes one official self-update and one rerun per path under the added stop conditions.
