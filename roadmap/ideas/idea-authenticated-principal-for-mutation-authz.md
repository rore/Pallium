---
id: idea-authenticated-principal-for-mutation-authz
title: Authenticated principal feeding mutation authorization (real multi-tenant security)
status: paused
priority: low
commitment: uncommitted
---

## Status

Paused and non-current. Pallium is currently an unauthenticated trusted-local service; no authenticated principal or multi-tenant authorization layer is planned for the present deployment model. Revisit only if the product becomes shared or exposed to untrusted clients.

Any future work would require a real server-verified principal for destructive mutations, with its trust boundary and deployment model designed first. The prior self-asserted scope/strict-mode approach is not a valid implementation and is intentionally not retained.
