---
id: add-budgeted-long-relay-messages
title: Support long Relay messages with budgeted injection
status: queued
priority: high
commitment: committed
milestone: pallium-relay
lane: stabilization-usability
---

## Summary

Let an agent send one useful Relay message up to 16,000 Unicode code points while
keeping automatic recipient context within the existing 2,400-character turn
budget. Persist the complete redacted message, inject an attributed head with an
explicit omitted-character count, and let the recipient read the full body only
on demand.

Do not chunk one logical message into several messages or reassemble batches.

## Why

The current 1,500-character limit conflates two separate constraints:

- an accepted-content bound for validation, redaction work, and SQLite growth
- an automatic context-injection budget for the recipient's turn

Real Relay handoffs and reviews already exceed 1,500 characters and force callers
to split one message into several sends. Moving that split into the server would
remove sender work but would still flood the recipient's turn and add batch
lifecycle machinery.

Raising only the accepted-content cap is also insufficient. The shared Relay turn
selection loop currently measures the complete rendered payload and skips a row
that cannot fit, so a long persisted message could remain pending without ever
becoming model-visible.

The request field cap is not an HTTP pre-buffer OOM defense: FastAPI has already
read the JSON body before Pydantic validates the field. This slice retains a
bounded persisted/redacted payload; transport-level request-size enforcement is a
separate concern if measurements show it is needed.

## Existing Capability to Reuse

`GET /relay/messages/{message_id}` already returns the scoped stored payload, and
`pallium_relay_status` already calls it. Do not add
`GET /relay/deliveries/{delivery_id}` unless architecture review finds that
recipient-bound authorization cannot be expressed safely through the existing
message read.

The MCP status renderer currently rejects responses above its 2,000-character
budget, so the existing tool is not yet a usable full-body path for a 16,000-
character message. Prefer the smallest explicit read/expand behavior that reuses
the existing message endpoint and makes the deliberate context cost visible.

## In Scope

- raise the send and reply accepted/stored payload cap from 1,500 to 16,000
  Unicode code points while keeping API-schema and core validation aligned
- preserve validation for blank payloads and unsafe control characters
- run redaction before persistence and keep redaction-overflow handling bounded by
  the new stored-message cap
- keep the existing automatic Relay output budget at 2,400 characters
- make the shared turn selection path return a safe attributed preview when a
  complete message does not fit, including the exact number of omitted characters
  and the identifier/instruction needed for deliberate full-body retrieval
- preserve the complete redacted payload in storage; previewing must not mutate it
- ensure Codex, Claude Code, OpenCode, and MCP receive cannot claim a long message
  and then lose it because their formatter or tool response exceeds its budget
- provide a scoped, read-only on-demand path for the recipient to retrieve the
  complete stored body; reuse the existing message read and add only the minimum
  MCP exposure required
- update Relay tool descriptions and docs to remove the 1,500-character and
  multipart-continuation guidance
- keep `has_more`, `remaining_count`, lease recovery, ACK, reply, idempotency,
  expiry, redaction, and scope behavior truthful for previewed deliveries

## Out of Scope

- automatic chunking, multipart ordering, or batch reassembly
- injecting the complete long body automatically
- attachments, blobs, searchable Relay archives, or semantic indexing
- changing Relay retention or expiry policy
- adding transport-level streaming or a general request-body limiter
- changing the 2,400-character automatic turn budget without measurements

## Risk and Sequencing

This changes the public Relay request and delivery-response contracts and touches
API/red-zone code. Before any implementation edit:

1. Invoke `/agent-workflow` to create the Work Record and classify risk.
2. Complete the required architect shaping and API review.
3. Confirm the full-body access contract and the preview representation before
   changing guarded files.

The likely implementation surfaces are `core/relay.py`, `api/schemas.py`, the
shared selection path in `storage/sqlite_relay.py`, MCP response/tool handling,
integration formatters, public Relay docs, and their focused tests. Keep the final
diff smaller by generating the preview once at the shared selection boundary
rather than independently truncating in each integration.

## Done When

1. HTTP and MCP send/reply coverage accepts the exact 16,000-code-point boundary
   and rejects empty, unsafe, and over-limit payloads, including non-ASCII text.
2. One message between 1,501 and 16,000 code points is stored completely, appears
   once as an attributed preview within the caller surface's output budget, and
   exposes an exact omitted-character count.
3. The recipient can deliberately retrieve the complete redacted body through a
   scoped read path; another container or actor cannot read it.
4. Codex, Claude Code, OpenCode, and MCP receive cover preview → full read → reply
   or ACK through their real caller surfaces, with no invisible claim or duplicate
   delivery after lease recovery.
5. A long first message cannot starve later safe messages indefinitely, and
   `has_more`/`remaining_count` remain accurate across mixed long/short backlogs.
6. Redaction expansion, idempotent retry, expiry, restart, malformed legacy rows,
   and create → receive/read → reply/ACK lifecycle paths have public-surface E2E
   coverage.

## Origin

Observed during a live cross-runtime architecture handoff on 2026-09-07: one
feature proposal required three manual Relay sends solely because of the 1,500-
character cap. The generalized failure class is accepted-content and automatic-
injection budgets being represented by one limit.
