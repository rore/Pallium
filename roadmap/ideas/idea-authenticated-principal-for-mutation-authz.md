---
id: idea-authenticated-principal-for-mutation-authz
title: Authenticated principal feeding mutation authorization (real multi-tenant security)
status: queued
priority: high
commitment: uncommitted
---

## Summary

Raw-turn forget authorization (shipped in `fix-source-forget-scope-authorization`) enforces a
container-scoped check, but the caller's scope (`caller_container_ref`, `actor_ref`) is **self-asserted
request data** over HTTP. That closes the id-only IDOR and builds the enforcement SEAM, but in strict
multi-user mode a remote caller can still assert the target's container and pass the check. Real
multi-tenant security requires the caller's identity/scope to come from an **authenticated,
server-side-verified principal** — not the request body.

## Why

Flagged by CodeRabbit on PR #38 (Critical) and anticipated in the forget-authz clean-context review and
`docs/context/decisions.md` (2026-08-17): "strict mode still trusts client-supplied identity — this
builds the seam; real authentication feeding it is a later piece." Today Pallium has no authentication
or container-membership layer (`app/config.py` has no auth config; identity is env/context-supplied).
Until this lands, `single_user_trusted_mode=false` (strict) is NOT a real security boundary — it is only
sound behind a trusted transport. The loopback-bind guard is the current compensating control.

## In Scope

- An authenticated principal for mutating/destructive operations: derive the caller's actor + container
  scope from a verified identity (token / mTLS / trusted header from a gateway), not from request body
  fields. Validate server-side container membership before authorizing.
- Apply the verified principal to the existing forget authorization seam (single + bulk) and any other
  scope-sensitive mutation.
- Define the trust boundary explicitly: which transport/headers are trusted, how identity is verified,
  what happens on unauthenticated calls in strict mode (fail closed).

## Out of Scope

- Single-user local (trusted) mode — unchanged; the loopback guard remains its control.
- A full user-management / RBAC product (only the authenticated-scope seam needed for correct authz).

## Done When

1. In strict mode, the caller actor and container scope for forget (and other scope-sensitive
   mutations) are derived from a server-verified principal; request-body values cannot override
   either identity or scope.
2. Unauthenticated strict-mode mutation fails closed with a defined error.
3. E2E: a remote caller asserting a foreign actor or container in the request body is denied (the
   PR #38 exploit path is closed under strict mode).
4. `decisions.md` threat-model note updated from "seam only" to "authenticated boundary."

## Notes

Gates real multi-tenant deployment; prerequisite for P3 · Shared Knowledge (cross-user raw sharing).
Related: `fix-source-forget-scope-authorization` (built the seam), `fix-lookup-and-expansion-active-attribution`
(the analogous "identity from client context, not the source" telemetry problem),
`add-privacy-aware-memory-scope-and-sharing-foundation`.
