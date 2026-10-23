---
id: add-persistent-role-history
title: Search session history by Relay name across sessions
status: planned
priority: medium
commitment: committed
milestone: pallium-relay
lane: product-surface
---

## Summary

Look up Session History for an exact Relay name across successive sessions that
held it. Preserve the name held when each conversation happened. Reuse existing
name bindings; no additional role identity, registration or association is needed.

Companion: [Collection role skill](https://github.com/rore/rore-collection/blob/main/plans/feature-persistent-agent-roles.md).
Collection discovers role guidance from the existing Relay name and owns upkeep
and handoff instructions. Pallium owns name-based history lookup and attribution;
it does not know whether a role file exists. Keep this feature ID and URL stable.

## Why

A replacement developer can find earlier discussions behind working expectations.
This also benefits ordinary named sessions without roles. Current ownership alone
cannot identify which historical turns were recorded under a name.

## In Scope

- Inspect and reuse current Relay naming, session registry, history capture and
  exact-reference search. Agree a small public contract with the collection skill
  before implementation; document necessary schema/API changes and compatibility.
- Existing naming, rename/release and authorized takeover supply the attribution
  information. No extra agent-maintained field or adoption/departure call; names
  without role files behave identically. Preserve occupied-name authorization.
- Capture eligible history under the Relay name held at the source event, including
  delayed ingestion. Name changes and takeover affect future attribution only;
  never relabel older turns using current ownership. Resume/retries must not
  duplicate results.
- Exact Relay-name search spans successive holders while retaining source session,
  turn and lookup provenance. Default to the caller's authorized project/container;
  broader search requires explicit permitted scope. A global Relay address grants
  no global history access. Existing redaction, deletion and access checks apply.
- Keep historical Relay names distinct from user/assistant speaker roles, actor
  identity and task participation. Naming operations must not remove work refs;
  task completion must not remove the Relay name.
- Expose actionable partial/unsupported outcomes when historical binding evidence,
  capture or search is unavailable. Never invent historical attribution or present
  incomplete capture as proof that nothing happened.
- Preserve existing routing semantics: takeover redirects future sends, not queued
  messages, task associations, permissions or completed actions. No new wake or
  exactly-once processing guarantee is implied.

## Design Decisions to Resolve

Keep decisions local to this feature, without another registry or memory store:

- Inspect what binding history already exists; select the smallest capture extension and exact MCP/search
  surface. Document temporal boundaries, retention, bounds/indexing and migration
  for old records without historical name evidence. Never scan all transcripts per query.
- Define rename/reuse search behavior: an exact-name search means that historical
  name, not inferred continuity of purpose. Retain source provenance when a name
  is reused for unrelated work. Do not automatically merge different names,
  relabel history or backfill earlier sessions.
- Verify naming/capture/search behavior on each supported integration; publish
  actual support and limitations rather than assuming uniform host behavior.

## Current-name Recovery After Compaction

Source inspection on 2026-10-22 found that the existing Relay turn response includes
`session.alias` (`storage/sqlite_relay.py`), and takeover clears the former holder's
alias. Codex and Claude turn-start hooks already call `relay_turn`, but their
`format_injection` scope omits the name. Revalidate these findings on pickup.

Prefer exposing that validated current name through the existing injected context:
no new store, role registration or extra request on the normal hook path. Represent
confirmed name, confirmed unnamed, and unavailable distinctly. Never substitute a
cached name after lookup failure or interpret a missing field from an older
integration as confirmed loss. Keep output bounded and identity checks intact.

Test next-turn injection after compaction and compaction within an ongoing turn
separately: do not assume both invoke the same hook. Where injection cannot restore
fresh identity, inspect existing supported read-only self-discovery before adding
anything. The current naming mutation with no name clears it; it is NOT a lookup.
Publish host-specific recovery limits rather than promise uniform behavior or
instantaneous notification of takeover during a running turn. Collection owns
the small durable instruction connecting current name to role-file discovery.

## Out of Scope

Role files, role identity/registry or adoption/departure APIs, learning implementation, background reviewers/schedulers,
new orchestration or agent creation, new Minimap/Workflow role features, automatic
historical backfill, and changes to delivery reliability unrelated to this contract.

## Done When

1. A holds a Relay name and records a conversation. B takes the same name through
   existing authorized takeover and retrieves both sessions' eligible history
   with original source provenance. Neither session registers a role. Repeat with
   no role file: behavior is identical.
2. Turns before naming or after name release/change are not attributed to the
   former name. Resume, repeated calls, delayed ingestion and concurrent takeover
   preserve source-time attribution without affecting unrelated work refs.
   Explicitly test B taking A's name while A is inactive, then A resuming without
   a local rename: existing name discovery reports A no longer holds it; A's new
   turns are not attributed to that name, while A's earlier history remains.
   Collection tests stopping the old role guidance; Pallium adds no role state.
   Repeat recovery after compaction with retained ownership and external takeover;
   verify named/unnamed/unavailable outputs, source identity validation, and that
   recovery never renames, clears or reclaims the name. Cover both next-turn and
   within-turn compaction on supported hosts, reporting unsupported paths explicitly.
3. Missing identity, conflicting holder, unavailable capture, unsupported host,
   empty results and partial coverage have honest, actionable outcomes. Scoped
   search and expansion cannot expose unauthorized containers or deleted content.
4. Public-surface E2E coverage includes the complete lifecycle, boundaries,
   concurrency/takeover, error paths and existing routing/search regressions.
   Tests exercise actual integration surfaces, not only fabricated metadata.
5. Run the companion's real successor exercise: durable correction -> updated
   guidance -> replacement follows it without a reminder -> finds its source by Relay name.
   Record supported hosts and limits; distinguish qualification from later natural
   adoption. Update maintained Pallium skill/API documentation with the contract.

## Notes

Planned after current reliability work; placement does not reprioritize active
assignments. Documentation approval is not permission to alter live integrations.
No role-processing or background learning mechanism is requested in Pallium.
