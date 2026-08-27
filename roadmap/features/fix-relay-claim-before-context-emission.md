---
id: fix-relay-claim-before-context-emission
title: Prevent claimed Relay messages disappearing during hook timeouts
status: active
priority: high
commitment: committed
milestone: pallium-relay
lane: defect
---

## Summary

Fix the natural-turn integrations so a Relay delivery cannot be claimed, hidden
behind its lease, and then omitted from the model context when later memory work or
the hook process fails. This is a blocking correctness fix before wake-first Relay.

## Observed Failure

In a live cross-runtime review exchange, two replies were claimed by the Codex
session in one `/relay/turn` call. The user started two natural turns, but neither
message appeared and neither claim was acknowledged. Both were recoverable only
after the 60-second claim lease expired.

The Claude Code and Codex hooks currently claim Relay before calling the slower
`/item-and-query` memory path, then emit combined context and acknowledge Relay at
the end. An 8-second hook timeout or process failure in that interval produces the
observed invisible-lease window. OpenCode has a related claim-to-model-transform
window whose restart/failure behavior must also be verified.

## Contract

Explicit Relay delivery must not depend on memory retrieval succeeding or
finishing within the hook deadline. After a natural-turn attempt, every selected
delivery must be either visibly attached and acknowledged exactly once, or remain
immediately eligible for a later claim. It must not become temporarily invisible
because unrelated enrichment failed.

Fix the shared ordering/lifecycle boundary rather than increasing timeouts. Keep
Relay attribution, complete-message rendering, character budgets, scope isolation,
and existing claim-token authorization intact.

## In Scope

- Claude Code and Codex claim, render, emission, memory retrieval, and ack ordering
- the analogous OpenCode claim-to-model-transform and restart window
- safe handling of emission failure, acknowledgement failure, timeout, and process
  interruption without silent loss or duplicate visible delivery
- local integration installers if deployed hook files or configuration change
- operational evidence that distinguishes pending, claimed, delivered, and lease
  recovery during this failure class

## Out of Scope

- wake-first delivery or runtime activation adapters
- changing the claim lease merely to hide the race
- weakening acknowledgement to mean transport acceptance
- coupling Relay success to memory-query success

## Required E2E

Drive the same hook/plugin and HTTP surfaces used by callers and verify state
through Relay status or storage-backed public reads. Cover:

- delayed, failed, and timed-out `/item-and-query` after Relay is available
- interruption at each claim-to-emission and emission-to-ack boundary
- one and multiple deliveries near the rendering budget
- acknowledgement failure followed by exactly-once visible recovery
- claim response consumed but its token lost before rendering or acknowledgement;
  after lease recovery the delivery becomes model-visible and is acknowledged once
- Unicode payloads and malformed/non-renderable delivery handling
- expired delivery, lease expiry, and an immediate following natural turn
- Claude Code, Codex, and OpenCode lifecycle behavior

## Field incident ledger

This is the canonical ledger for defects discovered while using Relay across real
agent sessions. Give every new incident the next `RF-*` identifier before fixing
it. An incident closes only with a reproducible contract, a caller-surface E2E
regression, and a live smoke check where the runtime is available. Do not close an
incident from a unit test or a successful retry alone.

| ID | Observed incident | Disposition | Required evidence |
|---|---|---|---|
| `RF-001` | A reply was sent with the receiving Claude identity instead of the active Codex identity, producing a self-addressed duplicate acknowledgement. | Fixed in R1 acceptance hardening: replies derive both endpoints from the received `delivery_id`; agents do not reconstruct sender identity. | `test_delivery_derived_reply_is_attributed_scoped_and_idempotent` plus the live Claude↔Codex round trip. |
| `RF-002` | Agents could not reliably address or reuse a human-friendly alias when an older session held it. | Fixed in R1 acceptance hardening: alias conflict is explicit and deliberate `replace_existing=true` transfers the alias while preserving scope isolation. | `test_full_broadcast_snapshot_alias_transfer_reply_and_lifecycle`, `test_aliases_are_actor_scoped_and_replacement_cannot_clear_another_actor`, and the live two-Codex alias transfer. |
| `RF-003` | A deliberate change to another Git project did not update Relay container scope, so a valid alias in the target project appeared missing. | Fixed in R1 hardening: Claude/Codex follow deliberate Git-project transitions, best-effort close the old scoped session, and ignore transient non-Git cwd drift. | Hook coverage `test_deliberate_git_project_switch_updates_pin`, `test_transient_non_git_cwd_does_not_replace_git_pin`, and `test_failed_project_close_is_retried`, plus a live cross-project smoke check. |
| `RF-004` | OpenCode could acknowledge Relay before the resumed session's model-visible history was mutated, silently losing the message. | Fixed in R1 acceptance hardening: resumed OpenCode delivery uses the model-bound message path and acknowledges only after that mutation succeeds. | OpenCode plugin cases “chat.message injects Relay as system context and acknowledges after mutation” and “Relay claim survives a transform with no model-visible text part,” plus the recorded resumed OpenCode live round trip. |
| `RF-005` | Claude/Codex hooks claimed messages before slower memory enrichment; a hook timeout left messages invisible until the 60-second lease expired, with no model context and no acknowledgement. A second live reproduction consumed a successful claim response, then failed while rendering a Unicode `→` through a Windows CP1252 console; the claimed delivery and full token were unavailable until lease recovery. The same claim-to-model-visible failure window may exist in OpenCode. | **Open — blocking.** This feature owns the fix. Relay emission must be independent of memory retrieval and interruption-safe across claim, model-visible mutation, Unicode rendering/output, and acknowledgement. Normal agent UX must not require raw `/relay/turn` or acknowledgement calls; integrations own opaque delivery IDs and claim tokens without truncating or reconstructing them. | The full Required E2E matrix above for all three integrations, including HTTP claim success followed by client render/output failure and lost token; after lease recovery the delivery becomes model-visible and is acknowledged exactly once. Update local installs and complete a live Unicode cross-session smoke check. |
| `RF-006` | A natural turn had three eligible unread messages. Two older acknowledgements consumed the 2,400-character turn budget, so the newer actionable review verdict remained pending. `/relay/turn` returned only the selected subset with no `has_more` or remaining-count signal, and the receiving agent incorrectly told the user there was nothing else to act on. | **Open — blocking unattended coordination.** Preserve deterministic bounded delivery, but make omission observable. The turn response must report whether eligible unread deliveries remain and how many were omitted by the message cap or character budget. Every integration must render a compact attributed notice that more Relay mail remains for the next applicable turn; it must acknowledge only messages actually rendered. No LLM polling or automatic conversation loop. | Caller-surface HTTP plus Claude/Codex/OpenCode hook/plugin E2E: create more messages than the count and character budgets permit; assert the returned subset, `has_more=true`, exact remaining count, omitted rows still pending, visible backlog notice, and no acknowledgement for omitted rows. Subsequent applicable turns drain every message exactly once and end with `has_more=false`. Cover a single budget-skipped message, Unicode, cap boundary, expiry, and mixed claimed/pending rows. Live smoke must reproduce old acknowledgements ahead of a newer actionable message without misleading the recipient. |
| `RF-007` | `pallium_relay_reply` returned HTTP 500 during the live exchange. The installed service log identifies `sqlite3.OperationalError: database is locked` at `BEGIN IMMEDIATE` in `relay_send` while handling `/relay/replies`; two adjacent Relay writes failed the same way. | **Open — correctness and availability.** Handle transient SQLite write contention once at the shared immediate-transaction boundary. If the lock clears within the bounded wait, complete normally; if it does not, return an explicit bounded retryable response rather than an opaque 500. A retry must create at most one message/delivery and preserve the original delivery state. | Storage and public HTTP/MCP E2E: hold a competing write lock, issue a reply, release within the allowed wait, and assert one successful reply. Hold beyond the deadline and assert the documented retryable response, no partial write, then retry and observe exactly one reply. Exercise the same shared boundary through send, turn, and acknowledgement or prove those routes inherit the centralized behavior. Add a live concurrent Claude↔Codex smoke check and verify no raw lock traceback reaches the agent. |

Wake-on-send remains a separately tracked product gap outside this incident family; see
`add-wake-first-relay-delivery`. Deterministic scope rejection across different
containers and later delivery of an explicit but semantically stale message are
expected Relay behavior, not defects.

The live workaround also showed two agent mistakes: `pallium_relay_recipients`
was used as though it were an inbox, and a displayed delivery ID was shortened
before acknowledgement, producing a 404. These are not separate storage defects.
`pallium_relay_recipients` remains an address book, not a polling surface; skill
guidance must say so explicitly. Removing the need for raw claim/ack recovery in
RF-005 and disclosing bounded backlog in RF-006 are the product fixes. Opaque
protocol identifiers must always be retained and submitted in full by integrations.

When an incident is reported, record the observable symptom first. Do not assign
root cause or mark it duplicate until storage state, integration logs, and the
recipient-visible turn agree. If a claimed message must be recovered manually,
acknowledge it exactly once after capturing the delivery and retain the incident
evidence in the owning Work Record.

## Done When

1. The live reproduction no longer produces an invisible claimed delivery.
2. Relay remains visible and exactly-once when memory retrieval is slow or fails.
3. Every supported integration passes the failure-boundary E2E matrix through its
   real caller surface.
4. Updated local integrations are installed and a cross-session smoke test passes.
5. A clean-context review finds no remaining loss, duplication, or authorization
   gap, and the roadmap item records the verified result.

## Notes

Keep this fix in its own agent-workflow task and PR. Do not mix it into the
feasibility-only wake Phase 0 PR.
