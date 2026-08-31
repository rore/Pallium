# Codex Relay G1/G2/G3 qualification plan

Status: planning only (2026-08-31). This is the next gate after the accepted B2 candidate; it neither enables passive batch delivery nor wake.

## Scope and decision boundary

Use the installed local Codex CLI, its existing `UserPromptSubmit` inbox hook, and `codex queue --thread <exact-session> --message <notification>` only. The queue message is a bounded notification with an opaque activation ID: it carries no batch text, receipt, claim token, or second delivery path. The queued and ordinary turns must enter the same hook and storage-owned inbox claim path.

Do not run live probes under this documentation-only plan. Disposable sessions may establish isolation and preliminary evidence, but milestone acceptance must use the actual existing architect/developer sessions as required by the roadmap; disposable CLI substitutes alone cannot qualify desktop dogfood. Any temporary per-session hook/profile change requires a separately reviewed isolation/restore plan. No production database, managed replacement App Server, installation, migration, runtime edit, activation, or surrogate app/agent ping is authorized here.

## Current read-only evidence

- Local `codex-cli 0.149.1` exposes `codex queue --thread ... --message ...`.
- The local configuration has `codex_hooks = true`, Pallium stdio MCP, and the installed SessionStart, UserPromptSubmit, and Stop hook registrations.
- The repository hook emits UserPromptSubmit additional context after its Relay turn/publication sequence. It has no immutable full-envelope context-commit witness, and its legacy acknowledgement is not one.
- This desktop task received a queue-style notification without an injected Relay envelope; supported MCP recovery was required. That is not a failed G1 probe, but it prevents treating this desktop session as proof that the installed CLI hook fires for queued turns.
- A read-only Pallium status request did not complete in the check window. Treat service responsiveness as unproven until the isolated environment has a bounded health check; do not restart or repair the installed service here.
- The official Codex hook reference is version-sensitive: its default additional-context limit is approximate, and unlimited additional context applies only when the installed runtime supports it. It also declares `transcript_path` unstable, so a transcript alone cannot be the G2 witness.

Therefore the queue command and hook registration are available prerequisites, not G1/G2/G3 evidence. G2 and G3 remain unproven. An absent witness in the Pallium hook is not proof that the runtime lacks a usable readback interface; investigate the installed runtime interfaces below before declaring technical infeasibility.

## Isolation and rollback preflight

1. An operator names two disposable sessions on this exact CLI/hook build and confirms neither is a normal work session. Record their immutable session IDs, Codex version, hook file hashes, config-profile hash, and local time.
2. Use a separately provisioned disposable Pallium database and endpoint with no production records. The profile must register the same hook executable and stdio MCP shape as the installed configuration. If that parity cannot be demonstrated, stop: a synthetic hook is not a qualification result.
3. Snapshot the disposable database, profile, hook registration, and session transcripts before each probe. Rollback means stop queueing, close the two sessions, restore or discard only that disposable database/profile, and retain transcripts and Relay audit IDs. Never roll back by running an unaware binary over batch-format rows.
4. Predeclare generic payload fixtures, exact expected envelope digest/length, and the single allowed notification text. Do not put content or private capability material in the queue message.

## G1 — same-hook queue delivery

### Idle probe

1. Commit one bounded generic batch to the target's isolated inbox and record delivery ID, claim generation, exact full envelope, digest, and byte/code point lengths.
2. Queue one notification to the exact target session while it is idle.
3. Capture the queue result, target hook invocation, and the target's pre-model context artifact. Verify the hook selected the committed delivery once and emitted the exact attributed envelope, ordered parts, count, and terminal marker.
4. Open a normal user turn after the queued turn. It must share the inbox path: no duplicate injection, no second claim, no fabricated reply, and truthful empty/backlog status.

### Busy, restart, and fallback probes

1. With the target demonstrably in an active turn, queue the same notification once. Capture whether it is accepted, deferred, or refused; do not issue a second notification to compensate.
2. At the next supported turn boundary, require the same hook and one generation-bound claim. A busy refusal or unsupported hook leaves the batch pending for an ordinary user turn; it does not create a second payload path.
3. Restart only the disposable target/session harness between reservation and publication. Prove an unpublished expired generation is reclaimed once; a started publication is visible as `uncertain`.
4. Repeat with queue unavailable/disabled. A normal user turn must drain the same pending inbox, with no silent gap and no app/agent ping used as delivery.

G1 passes only when both idle and busy evidence identify the installed UserPromptSubmit hook and the same storage owner. Queue acceptance alone, notification display, or a model response is insufficient.

## G2 — full-envelope admission and stale publication

1. Define the witness before any probe: an immutable runtime artifact must show the complete `hookSpecificOutput.additionalContext` at the pre-model boundary, tied to exact session, queued turn, delivery, generation, digest, ordered parts, count, and terminal marker. A partial transcript, tool receipt, model paraphrase, or queue response fails this criterion.
2. Run the idle and busy G1 probes with the witness enabled. Recompute the envelope digest and both lengths from the captured artifact; require exact equality with the storage claim. Record actual admission time separately from witness-observation time.
3. Exercise stale pre-publication ownership in the isolated harness: replace or expire generation A before output, then attempt A's publication. It must be rejected before emission; only generation B can proceed.
4. Interrupt after publication-start but before the witness. Preserve the delivery as `uncertain`. Release it only on a trusted proof of both non-admission and impossible late publication; lease expiry, missing history, or timeout alone is not proof. A later positive witness records admission and does not replay the batch.

The current hook does not expose the required witness. A `transcript_path` is explicitly not a stable hook interface, so it cannot substitute for one. If the exact runtime cannot expose a witness without a separately reviewed change, G2 is a genuine blocker: leave candidate delivery and wake disabled rather than substituting an ACK.

## G3 — 64-delivery headroom

1. Load 64 durable, valid, worst-case generic batches into the isolated target inbox. Include escaped Unicode, maximum ordered-part shape, attribution, backlog metadata, and a late arrival after the first drain. Measure full rendered envelope code points and UTF-8 bytes, not payload length or tokens.
2. Drain strictly FIFO across as many turns as the configured complete-batch bounds require. For every turn capture actual injected context bytes/chars, runtime context capacity and remaining headroom before/after injection, claimed IDs/generations, and backlog state.
3. Repeat once with the target busy at notification time and once after a disposable-session restart. Verify no skipped oldest batch, truncation, duplicate admission, or silent post-restart gap.
4. Set a lower provisional capability only if the measured minimum safe headroom supports it. If any accepted envelope cannot fit an empty measured budget, keep it visibly blocked; never truncate or silently lower an already-accepted contract.

G3 passes only with raw per-turn measurements and a documented safe drain limit. The durable 64-item capacity is not a promise that all 64 fit one turn.

## Gate record and next decision

| Gate | Current status | Evidence required to close | Failure outcome |
|---|---|---|---|
| G1 | Unproven | Idle + busy queued turns invoking the same installed inbox hook | Wake remains passive; ordinary-turn fallback only |
| G2 | Unproven; runtime readback candidate identified | Immutable full-envelope pre-model artifact plus stale-publication result | Keep published attempts uncertain; no automatic replay |
| G3 | Unproven | 64-item, multi-turn headroom measurements with FIFO/restart/fallback coverage | Retain/visible-block work; do not enable candidate or wake |

Only a separate review of completed evidence may authorize the next action. The later rollout decision remains separate: inspect live schema and backup/restore only then; deploy compatible readers and explicit migrations before any new writer or capability is enabled.

## Manager review and immediate next task — 2026-08-31

Accept the bounded test matrix with the corrections above. Do not require a human
to select substitute sessions, and do not equate a missing hook-owned witness with
an unavailable runtime capability. No live probe was authorized or performed.

A read-only schema export from the installed `codex-cli 0.149.1` using
`codex app-server generate-json-schema --experimental --out <temporary-directory>`
identified:

- `v2/ThreadReadResponse.json`: `ThreadItem` includes `hookPrompt`, whose fragments
  contain `hookRunId` and `text`; `ThreadReadParams.includeTurns=true` requests
  persisted turn items. This is a candidate full-text readback, not yet proof of
  model admission, completeness, immutability or support in the desktop host.
- `v2/HookCompletedNotification.json`: hook run IDs, entries with kind `context`,
  status and timing. Completion/output alone is not model admission.
- `v2/ThreadTokenUsageUpdatedNotification.json`: exact thread/turn IDs, token usage
  and optional `modelContextWindow`. This may support G3 measurements but does not
  promise remaining headroom or safe automatic compaction.
- `codex debug prompt-input --help` describes a model-visible prompt renderer, but
  exposes no exact-existing-thread selector; do not treat it as that thread's
  immutable history or use it to launch a substitute runtime.

Next task is a bounded, read-only witness feasibility probe against the existing
runtime: establish whether supported existing-host access exposes complete
`hookPrompt` fragments and their admission semantics, with version-pinned evidence
and no new server, turn, config change or delivery mutation. If existing-host
access is unavailable, state the exact missing connection/API rather than calling
all Codex wake impossible. Then review the smallest isolated live probe separately.

Official reference checked: https://learn.chatgpt.com/docs/hooks. It documents the
2,500-token default additional-context threshold and warns transcript format is
unstable. Version qualification is required; the warning does not itself prohibit
verified readback through a runtime-owned structured history API.

## Existing desktop witness feasibility — read-only result

The supported desktop `read_thread` surface was queried for this active task with
turn/output inclusion. It returns thread metadata and turn summaries, but not a
hook run ID, `hookPrompt.fragments`, hook-completion context entries, or a model
context-window update. It therefore cannot read back the proposed witness from
the existing desktop-owned runtime.

The installed CLI exposes an offline app-server schema generator and an
app-server proxy command, but this task has no supported, authenticated
app-server connection bound to the desktop host. Starting or attaching a new
transport would be the prohibited transport scaffolding, not read-only
qualification. The schema's `ThreadItem.hookPrompt` and related notifications
are candidates only: even complete fragments would still need a runtime semantic
that proves pre-model context commitment.

This is not evidence that G2 is runtime-infeasible. The exact missing capability
is a supported desktop-bound read operation or subscription that returns persisted
`ThreadReadResponse` hook-prompt fragments with their hook-run/session/turn
identity, plus hook-completion and token-window semantics for the same turn. It
must establish whether the full fragment was committed before model execution;
raw transcript files remain excluded because their format is not stable. Until
that connection exists, G2 remains blocked and G3 cannot measure actual desktop
headroom. No server, turn, configuration, or delivery probe was created.

### Manager connection check

The prohibition is against a replacement managed runtime or ad hoc transport
scaffolding, not a supported read-only client attaching to the existing host.
A bounded `codex app-server proxy` invocation with only an `initialize` request
failed before connection: `failed to connect to socket ... app-server-control.sock`,
Windows `os error 10050` (socket operation encountered a dead network). No server,
turn or runtime configuration was created/changed. The local path is intentionally
omitted from this public record.

Thus the app task tool lacks the required detail and the CLI's default existing-
host connection is unavailable on this machine. Do not infer from this error that
all runtime transports or OSs are unsupported. Qualification is currently blocked
on a usable supported existing-desktop readback connection (or separately reviewed
alternative evidence), not on another revision of the batch storage algorithm.
Do not silently weaken the agreed admission contract or activate to work around it.
