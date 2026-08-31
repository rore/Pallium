---
id: fix-relay-hook-reply-scope-resolution
title: Make hook-delivered Relay replies resolve injected scope
status: queued
priority: high
commitment: uncommitted
milestone: pallium-relay
lane: defect
---

## Summary

A hook-delivered Relay reply with only its delivery ID and message returned HTTP 422
because the MCP client omitted `container_ref` and `actor_ref`, despite the tool
contract treating them as integration-resolved optional scope. Retrying with the
injected scope succeeded. This makes the documented hook reply path unreliable.

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
## In Scope

- Trace scope resolution from the hook-delivered tool call through the MCP client
  and Relay reply endpoint.
- Qualify whether `UserPromptSubmit` exposes the same runtime-owned `turn_id`
  carried in local Codex MCP request metadata. Do not assume it from a session
  ID or synthesize one.
- Only if that correlation exists, have the hook publish an atomically replaced,
  short-lived binding keyed by `(runtime, session_ref, turn_id)` after a
  successful Relay turn registration. It must contain the hook-derived
  `container_ref` and `actor_ref`; the MCP process must never derive either
  from CWD, aliases, a delivery, or model arguments.
- Let only the configured local Codex stdio server consume an exact, fresh
  binding from its trusted request metadata. Generic factory and network paths
  remain denied. A present explicit scope must agree exactly; any absent,
  stale, malformed, conflicting, or ambiguous binding fails closed before a
  Relay HTTP call.
- Apply that resolver consistently to every Relay MCP call, including receive
  and receipt ACK, not just reply.
- Keep explicit scope validation and atomic reply/ACK behavior unchanged.

## Out of Scope

- Changing Relay routing, receive identity, queue wake behavior, service
  configuration, or raw HTTP guidance.

## Done When

1. A hook-delivered reply succeeds with delivery ID and message only when its
   exact integration-owned scope binding is present.
2. Receive, receipt ACK, reply, send, status, naming, and recipient discovery
   obtain the same bound scope; no tool relies on a process-global scope.
3. Missing, corrupted, expired, mismatched-session, mismatched-turn,
   conflicting explicit scope, and ambiguous project-switch bindings fail
   closed with no Relay HTTP call or partial ACK/reply.
4. E2E drives two concurrent sessions through their own bindings; then a
   project switch, failed old-project close, stale binding, duplicate reply,
   and normal status reads. It asserts no cross-scope delivery and the complete
   create → receive → ACK/reply → status lifecycle.
5. Generic/default and network servers reject the same metadata/binding inputs.

If the hook does not expose a matching runtime-owned turn ID, this automatic
scope plan is blocked. The honest interim contract is explicit scope only for
send/reply/status/name/recipients; installed recovery receive and ACK remain
unavailable rather than guessing scope.

## Notes

Dogfood incident 2026-08-31: the first `pallium_relay_reply` call returned 422
for missing `container_ref` and `actor_ref`; the same reply succeeded when those
injected values were supplied. This is a generic MCP scope-resolution defect, not
an identity-binding or wake qualification result.