---
id: add-persistent-role-history
title: Preserve role history across replacement sessions
status: planned
priority: medium
commitment: committed
milestone: pallium-relay
lane: product-surface
---

## Summary

Let successive sessions holding the same role retrieve earlier role conversations.
The Relay name IS the role identity; do not add another role identifier or a name
mapping. The current session binding changes, while captured history remains.

Companion: [Collection role skill](https://github.com/rore/rore-collection/blob/main/plans/feature-persistent-agent-roles.md).
Collection owns guidance, foreground self-improvement, adoption and handoff recipes.
Pallium owns explicit role association, capture and scoped history search.

## Why

A replacement developer should inherit working expectations and be able to find
the original discussion behind them. A current Relay alias alone cannot identify
which earlier turns belonged to that role, especially after takeover or switching.

## In Scope

- Inspect and reuse current Relay naming, session registry, history capture and
  exact-reference search. Agree a small public contract with the collection skill
  before implementation; document necessary schema/API changes and compatibility.
- Start with one active role per session and one current holder of its Relay name.
  Explicit adoption verifies the intended binding; ordinary alias naming alone
  must not silently assign historical role membership. Occupied-name takeover
  retains existing authorization requirements.
- Associate eligible history with the adopted name as work happens. Adoption,
  switching and departure affect future capture only, including delayed ingestion:
  use membership at the source event, not whichever session owns the name at ingest
  or search time. Resume/adopt retries must not duplicate membership or results.
- Exact role-name search spans successive holders while retaining source session,
  turn and lookup provenance. Default to the caller's authorized project/container;
  broader search requires explicit permitted scope. A global Relay address grants
  no global history access. Existing redaction, deletion and access checks apply.
- Keep role membership distinct from user/assistant speaker roles, actor identity
  and task participation. Role departure must not remove task or structural refs;
  ending a task must not automatically leave an enduring role.
- Expose actionable partial/unsupported outcomes when association, capture or
  search is unavailable. Do not report empty history as proof that nothing happened.
- Preserve existing routing semantics: takeover redirects future sends, not queued
  messages, task associations, permissions or completed actions. No new wake or
  exactly-once processing guarantee is implied.

## Design Decisions to Resolve

Keep decisions local to this feature, without another registry or memory store:

- Select the smallest existing association/capture extension and exact MCP/search
  surface. Document temporal boundaries, retention, bounds/indexing and migration
  for old records with no role metadata. Never scan all transcripts per query.
- Define explicit rename behavior because the name is identity. No automatic
  merging of unrelated reused names, historical relabeling or automatic backfill.
  Earlier-session backfill is outside the initial slice.
- Verify capture/adoption/search behavior on each supported integration; publish
  actual support and limitations rather than assuming uniform host behavior.

## Out of Scope

Role-guidance storage or learning implementation, background reviewers/schedulers,
new orchestration or agent creation, new Minimap/Workflow role features, automatic
historical backfill, and changes to delivery reliability unrelated to this contract.

## Done When

1. Session A explicitly adopts a role, records a relevant discussion, and leaves.
   Session B adopts the same name with authorized takeover and retrieves that
   discussion with original source provenance. Current ownership does not rewrite
   the historical association.
2. Turns before adoption and after departure are excluded; role switching,
   same-session resume, repeated calls and delayed ingestion preserve correct
   membership without affecting unrelated work refs.
3. Missing identity, conflicting holder, unavailable capture, unsupported host,
   empty results and partial coverage have honest, actionable outcomes. Scoped
   search and expansion cannot expose unauthorized containers or deleted content.
4. Public-surface E2E coverage includes the complete lifecycle, boundaries,
   concurrency/takeover, error paths and existing routing/search regressions.
   Tests exercise actual integration surfaces, not only fabricated metadata.
5. Run the companion's real successor exercise: durable correction -> updated
   guidance -> replacement follows it without a reminder -> finds its source.
   Record supported hosts and limits; distinguish qualification from later natural
   adoption. Update maintained Pallium skill/API documentation with the contract.

## Notes

Planned after current reliability work; placement does not reprioritize active
assignments. Documentation approval is not permission to alter live integrations.
No background learning process is requested: upkeep belongs to the active role.
