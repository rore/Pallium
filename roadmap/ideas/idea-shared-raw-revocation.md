---
id: idea-shared-raw-revocation
title: Revocation of previously shared raw work
status: parked
priority: medium
commitment: uncommitted
milestone: pallium-vnext-p3
---

## Summary

Allow raw work that was shared with another user/context to be **revoked**, so it
stops being retrievable/expandable by grantees. Split out of `add-raw-history-governance`
(2026-08-13) because it has no substrate today.

## Why

Investigation (2026-08-13) found **no sharing/grant/revoke substrate** anywhere in the
codebase — cross-user visibility of raw turns is not yet a capability, so there is
nothing to revoke. Revocation is only meaningful once an explicit raw-history
sharing/grant contract exists.

## Depends on

- `idea-visibility-vocab-reconciliation` — the authorization/grant contract (consent,
  target audience, provenance, fail-closed) that revocation acts against
- `idea-cross-user-raw-history-value` — the P3 value experiment that would justify
  building sharing (and therefore revocation) at all

## Out of Scope

- the grant contract itself (that is `idea-visibility-vocab-reconciliation`)
- user-requested forgetting of one's *own* raw turns (`add-raw-history-governance`)

## Notes

P3, validation-blocked by design until a real multi-user deployment exists. Build only
if the raw cross-user sharing result requires it.
