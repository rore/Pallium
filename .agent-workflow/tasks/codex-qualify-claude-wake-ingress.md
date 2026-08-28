<!-- agent-workflow:start -->
**Outcome:** Qualify one safe Claude wake-ingress candidate on Windows using only disposable sessions, with a documented evidence-based recommendation.

**Target:** Claude Code wake ingress qualification.

**Scope:** Work Record; sanitized evidence; `docs/designs/017-relay-wake-phase0.md`; relevant roadmap item(s); ignored `.local/` disposable probes only.

**Constraints:** No production adapter, coordinator, database/schema, dashboard, dependency, or existing-user-session changes. Do not expose a socket path, token, or secret in model context, Relay, arguments, files, output, logs, responses, or commits. Windows live proof only; no soak test.

**Completion criteria:** A two-disposable-session Windows probe either proves one candidate's exact-target admission and required Phase 0 observations without secret exposure, or records a bounded passive-only/unknown verdict with stop evidence.

**Risk:** Elevated

**Complexity:** Moderate

**Reason:** Intended committed paths are blue-zone documentation and workflow metadata, but live cross-session ingress and private-frame handling are security-sensitive and have meaningful multi-session uncertainty; engineering judgment raises the task to Elevated.

**Discovery:** `docs/designs/017-relay-wake-phase0.md` keeps Claude passive-only: Path A needs a disposable Windows proof and a correlated `Stop`-hook admission; it rejects `UserPromptSubmit` as the idle signal. PR #80's `ClaudeWakeRegistry` is memory-only (900 s TTL), hides token/socket values from representation, and has no public probe/trigger surface. `claude --version` reports 2.1.246, whose local `--help` does not advertise `--channels`; current official Channels documentation nevertheless describes a research-preview, startup-opt-in channel plugin with sender gating. The roadmap’s earlier Path-A feasibility claim conflicts with the newer design/code evidence; this task uses the latter until a live trace proves otherwise.

**Material assumptions:** (1) Disposable Claude sessions can be launched and addressed without touching existing sessions; disprove by any ambiguous target ownership, then stop without a live send. (2) The PR #80 memory-only boundary supplies secrets only out of model-visible surfaces; disprove by any required secret serialization, then stop. (3) A service-owned, secret-opaque test transport exists or can be exercised without a production adapter; disprove by the current registry’s lack of a safe invocation seam, then stop before Path A send and record the limitation. (4) Channels can be enabled only when the exact installed CLI/plugin/organizational gate proves available; disprove by absent flag/plugin/gate, then record unavailable without installing, configuring, or using external credentials.

**Plan:** (1) Invoke agent-workflow and establish this record before edits. (2) In ignored `.local/`, prepare one PowerShell launcher that creates two fresh GUID session IDs and isolated scratch directories, starts only those two Claude processes (never `--resume`/`--continue`), records PIDs/IDs privately, and tears them down at the first stop condition. (3) Preserve token/socket values only in the target hook → loopback memory registration path; launch command lines, markers, Relay text, logs, evidence, and commits contain only generated non-secret IDs. Do not inspect registries or target-process environments. (4) Preflight Paths A/B without a send: Path A requires a service-owned opaque transport invocation plus frame/receipt evidence; Path B requires the exact installed `--channels`/approved plugin and no external credential or config mutation. (5) Only if one path passes every preflight gate, exercise that path on the two disposable sessions with one non-secret marker at a time and capture sanitized evidence for exact targeting, idle distinct-turn admission, busy non-steering (or documented `unavailable` plus fallback), duplicate, closed/restart, and transport ACK distinct from admission. (6) Stop immediately on ambiguous targeting, any existing-session contact, secret exposure or persistence, missing service-owned opaque transport/frame/receipt proof, unavailable Channels gate, busy steering, permission/configuration prompt, process escaping the disposable launcher, or any destructive/runtime-configuration action. A stop yields passive-only/unknown evidence; no workaround or retry. (7) Commit only sanitized evidence and concise design 017/roadmap updates after required review.

**Verification plan:** When a candidate passes preflight and is exercised, evidence shall show an exact disposable target and separate admission outcome versus transport ACK → sanitized probe transcript and design update. When any stop condition occurs, no additional sends shall occur → launcher/process lifecycle record and Work Record evidence. When no candidate satisfies the security/admission gate, design 017 shall remain passive-only → reviewer-visible verdict. Workflow fields and final changed paths shall validate → agent-workflow/redline checks.

**Plan review:** Pending clean-context architecture review from `codex:@relayarch`.

**Approvals:** Not required at this risk level.

**Exceptions:** —

**State:** Blocked
<!-- agent-workflow:end -->

## Implementation

- 2026-08-28: Branch created from `origin/main` at `242e3120c106df254ea7e47c6e0e460c9e8d844b`; agent-workflow invoked and record initialized before edits.
- 2026-08-28: Focused discovery completed. The current secure registry lacks a safe live-send seam and local Claude help lacks `--channels`; both are explicit preflight gates, not invitations to add a workaround. Awaiting the required clean-context architecture review; no disposable session or probe has run.

## Evidence

- Installed CLI preflight: `claude --version` → 2.1.246; local `--help` has no `--channels` flag.
- [Claude Code Channels documentation](https://code.claude.com/docs/en/channels) describes a research-preview startup opt-in with plugin, sender-gating, and organization requirements; this is not an installed-runtime admission proof.
