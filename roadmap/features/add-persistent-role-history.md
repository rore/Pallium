---
id: add-persistent-role-history
title: Search session history by Relay name across sessions
status: active
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
- Capture each complete source turn under the Relay name validated when that turn
  started, including delayed assistant ingestion and retries. A takeover during a
  turn affects subsequent turns only; it never relabels that turn or older history.
  Duplicate ingestion preserves the first captured attribution. Confirmed unnamed,
  unavailable, and legacy unknown attribution remain distinct.
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

## Design Decisions

Keep decisions local to this feature, without another registry or memory store:

- The accepted temporal boundary is whole-turn: use the validated Relay name held
  at turn start for all source items from that turn, even if assistant capture is
  delayed until after a takeover. A delayed item may inherit the immutable user
  source snapshot only through an exact same-turn source reference validated for
  the same container, thread and user role. Never consult current ownership to
  reconstruct a prior turn; unsupported or uncorrelated capture is unavailable.
- Codex source capture uses the host's native `turn_id` on UserPromptSubmit and
  Stop. The user row stores the validated Relay name returned at turn start; Stop
  inherits only that exact same-container, same-thread user snapshot. Missing or
  malformed native keys stay unavailable. User-start retries reuse only an equal
  snapshot and reject conflicting state/name; assistant outputs remain distinct,
  and Stop retries may duplicate because the hook exposes no stable per-output key.
- Claude Code's official hook payload exposes common UUID `prompt_id` on
  UserPromptSubmit and Stop. Use it as the scoped `source_turn_id` when present
  and valid; missing or invalid keys stay unavailable. The official docs warn the
  transcript can lag at Stop and provide `last_assistant_message`; transcript-
  derived assistant text or work-trace metadata must not be attached to the
  current prompt key unless its association is proven. The docs do not state a
  host version floor or retry/compaction persistence guarantee.
- OpenCode V1 exposes native `messageID` on `chat.message` (optional in the V1
  plugin type; the persisted user message also has its native ID), and persisted
  assistant messages carry `parentID`. V2 prompt admission exposes `messageID`;
  its context hook exposes ordered native message IDs and the current adapter
  selects assistant messages after the latest user boundary. These provide a
  candidate exact source-turn key from the user message ID, with assistant
  linkage through the native parent/boundary. V1 obtains the validated alias
  from its existing `/relay/turn` call at `chat.message`; V2 currently captures
  the user before its `/relay/turn` call in the later context hook, so start-time
  alias capture needs sequencing work that preserves delivery claim and ACK
  behavior. Neither plugin version yet sends role snapshots or source-turn keys,
  and host payload behavior still requires qualification.
- Hermes remains in scope; its integration owner must confirm and implement its
  native pre/post turn linkage and coordinate shared `source_type` support before
  the feature can claim complete cross-tool coverage.
- Select the smallest durable source-attribution extension and exact MCP/search
  surface. Old rows remain unknown. Incomplete coverage may describe only unknown
  or unavailable rows in the caller's otherwise-eligible scope; it cannot infer
  turns that produced no row. Never scan transcripts per query or backfill names.
- Define rename/reuse search behavior: an exact-name search means that historical
  name, not inferred continuity of purpose. Retain source provenance when a name
  is reused for unrelated work. Do not automatically merge different names,
  relabel history or backfill earlier sessions.
- Verify naming/capture/search behavior on each supported integration; publish
  actual support and limitations rather than assuming uniform host behavior.

## Current-name Recovery After Compaction

Source inspection confirms the existing `/relay/turn` response carries a validated
`session.alias` (`api/schemas.py` and `core/relay.py`). The Codex UserPromptSubmit
hook records that response's exact alias state on the user's source row; the
existing read-only `pallium_relay_address` returns `relay_name_state` and optional
`relay_name` for current-name discovery. An explicitly present `alias: null` on a
validated session means unnamed. A missing or malformed field means unavailable.
Stop never refreshes current identity: it resolves only the immutable start row.
No new store, registry, role registration or extra normal-path request is added.

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
4. Public-surface E2E coverage covers the complete required matrix:
   - Codex UserPromptSubmit/Stop with native `turn_id` and takeover before delayed Stop.
   - Claude UserPromptSubmit/Stop with `prompt_id`; keyed Stop uses only
     `last_assistant_message`; missing current assistant text may use transcript fallback only without the prompt key, so it remains uncorrelated.
   - OpenCode V1 `chat.message`/`session.idle` linked by user `messageID` and
     assistant `parentID`; OpenCode V2 prompt/context/idle linked by native user
     message ID and the exact latest-user boundary. V2 start-time alias capture
     must preserve the existing delivery claim and ACK ordering.
   - Hermes pre/post hooks linked only by the native key confirmed by its owner.
   Each adapter exercises same-turn retry, delayed assistant capture after takeover,
   out-of-order/overlapping turns where the host supports them, missing-key
   unavailability, exact-name search, visibility and forgetting. No adapter may
   infer by current ownership, FIFO, or a shared session slot. Distinct assistant
   outputs remain distinct; duplicate retry behavior follows each host's native
   per-output identity. Fixtures prove adapter contracts only; real-host payload
   qualification is separately recorded. Exact filtering stays before limits and
   legacy unknown coverage remains explicit.
5. Run the companion's real successor exercise: durable correction -> updated
   guidance -> replacement follows it without a reminder -> finds its source by Relay name.
   Record supported hosts and limits; distinguish qualification from later natural
   adoption. Update maintained Pallium skill/API documentation with the contract.

## Notes

Active implementation is tracked under Parallel · Session History. Documentation
approval is not permission to alter live integrations.
No role-processing or background learning mechanism is requested in Pallium.
