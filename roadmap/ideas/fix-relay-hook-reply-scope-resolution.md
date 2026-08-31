---
id: fix-relay-hook-reply-scope-resolution
title: Make Relay MCP scope explicit and fail closed
status: queued
priority: high
commitment: uncommitted
milestone: pallium-relay
lane: defect
---

## Summary

A hook-delivered Relay reply with only its delivery ID and message returned HTTP
422 because the MCP client omitted `container_ref` and `actor_ref`, despite the
tool contract treating them as integration-resolved optional scope. Retrying
with the injected scope succeeded. This affects every Relay MCP call, not only
reply.

## Diagnosis (2026-08-31)

Every Relay client call uses `_relay_scope_params()`: recipients, naming, send,
reply, status, receive, and receipt ACK all require `container_ref` plus
`actor_ref`. The installed Codex MCP configuration supplies only static
base-URL/runtime values. It has no task scope.

No existing safe automatic binding can fill that gap. The Codex hook pin is
per-session but stores only `container_ref` and a timestamp; it has neither the
actor nor a turn correlation. The persisted Relay session row does store both
scope fields, but rows are keyed by `(container_ref, runtime, session_ref)`:
one session can have multiple rows after a project switch, including an old
active row when best-effort close fails. Its `last_seen_at` cannot be matched to
the MCP request's `turn_id`, so selecting a latest row would make stale scope an
authorization source. CWD, aliases, and a delivery ID are not safe substitutes.

## Reviewed bounded candidate (2026-08-31)

Do not build a scope store. Add optional `container_ref` and `actor_ref` to MCP
receive and receipt ACK, matching the existing reply/send/status selectors.
They are explicit scope selectors copied from the current injected Pallium
scope, never runtime/session identity or authentication. Preserve the existing
environment fallback; reject missing, blank, partial, or environment-conflicting
explicit scope before any Relay HTTP call. Reply already has these selectors, so
correct its tool/skill wording instead of promising automatic resolution.

## In Scope

- Add optional `container_ref` plus `actor_ref` selectors to receive and receipt
  ACK, resolving both together against configured environment scope.
- Preserve runtime/session binding: receive still accepts neither model runtime
  nor model session; local Codex metadata only supplies its existing trusted
  request-local session identity. Receipt binding and atomic reply semantics do
  not change.
- Update reply guidance to require the exact injected scope selectors when the
  MCP process has no configured scope; do not claim delivery-ID-only routing.
- Add the focused E2E coverage below through the same HTTP/MCP surfaces callers
  use.

## Out of Scope

- Hook or storage scope state, Relay routing, receive identity, queue wake,
  service/configuration changes, API changes, raw HTTP guidance, and G2/G3.

## Done When

1. A local-Codex metadata-bound receive with explicit scope reaches only its
   exact project/actor; receipt ACK, reply, and status then complete through
   their normal surfaces.
2. Missing, blank, partial, or environment-conflicting explicit scope fails
   before HTTP. No delivery is claimed and no receipt ACK/reply is partial.
3. Cross-scope receipts cannot ACK or reply, and one runtime/session registered
   in two project scopes remains separated.
4. The E2E matrix drives create → receive → ACK/reply → status, concurrent
   sessions, duplicate reply/idempotence, missing scope, environment conflict,
   and cross-project misuse through HTTP plus real in-memory MCP.
5. Generic/default and network servers retain current metadata denial; no hook,
   storage, API, service, or wake behavior changes.

## Notes

Dogfood incident 2026-08-31: the first `pallium_relay_reply` call returned 422
for missing `container_ref` and `actor_ref`; the same reply succeeded when those
injected values were supplied. This is a generic MCP scope-resolution defect,
not an identity-binding or wake qualification result. The per-turn binding
candidate was diagnosed and deliberately rejected as larger and unsafe without
turn correlation.