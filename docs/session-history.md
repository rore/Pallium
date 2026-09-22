# Session History

Session History records selected user and agent turns so later agent sessions can
search earlier work. Search only returns history visible to the requesting
session. Pallium can redact sensitive text from results, and stored turns can be
explicitly forgotten.

It is useful when the important context is not in the current checkout: why a
decision was made, what an earlier investigation found, which constraint shaped
the work, or why an approach was rejected.

## Basic use

Ask the agent to search earlier work in plain language:

> Search Pallium Session History for why we rejected the queue approach.

The agent uses `pallium_search_history` with a query such as:

```text
why did we reject the queue approach?
```

If the exact work reference is known, use
`pallium_search_history_by_work_ref(work_ref, query?)`. Omitting the query returns
the newest eligible items carrying that exact normalized reference. This search is
deliberately narrow and can miss related work stored under another reference or no
reference; use the broad topic search in that case.

Current integrations may provide one ready-to-copy current work reference in the
agent's Pallium context. Pass it unchanged to exact-reference search. If no current
work reference is provided, use broad search rather than guessing one.

Search returns concise matches with source identifiers. When a match looks
relevant, the agent uses `pallium_expand_source` to open a bounded number of
turns around it, passing that match's `source_item_id` and the search response's
`lookup_event_id` as `parent_lookup_id`. Search labels are response-local:
`current` is the requesting session, repeated known foreign sessions share an
`other-N` label, and `unknown` never asserts shared identity. Regenerate the
Codex Relay profile after upgrading to make these read-only History tools
available in Relay-woken tasks.

Both search tools accept an optional `source_thread_ref` for exact historical
thread filtering. Omit it for broad cross-session History; the active requesting
session is tracked independently for telemetry and response grouping.

Search answers “where did we discuss this?” Expansion answers “what was the
surrounding reasoning?” The bounds keep one match from turning into an entire
transcript replay.

When the anchor itself is larger than the expansion response budget, the response
reports `effective_max_chars`, `content_offset`, `content_total_chars`,
`content_revision`, `has_more`, and `next_offset`. Continue by passing the returned
`next_offset` as `content_offset` together with the same `content_revision` and
`parent_lookup_id`. A nonzero offset without the revision is rejected. If the visible,
redacted source changes between calls, the revision becomes stale and the caller must
restart at offset zero. Offsets count Unicode code points; `next_offset: null` marks the
terminal page. Requests above the MCP maximum report the effective 4,000-character cap.
Every page refetches the source so forgetting and caller scope are enforced again.

### Paging search results

Both search tools accept `limit` from 1 through 50. Responses report `total_count`, zero-based `result_offset`, `next_offset`, `has_more`, `effective_max_chars`, and a `result_revision`. Continue with `next_offset` and the unchanged revision; nonzero offsets require it, and limits outside 1–50 are rejected. The revision binds the request and complete ordered candidate window. If that window or its visible representation changes, restart at offset zero. Paging does not change candidate membership, ordering, ranking, accessibility, visibility, redaction, or forgetting.

Each page has its own `lookup_event_id`; use the ID from the page containing a hit as `parent_lookup_id` for `pallium_expand_source`. Successful pages finalize only delivered IDs. Exact-end and over-end offsets return an empty terminal page with `next_offset: null`. A hit has a recognizable preview or `preview_unavailable: true` with a stable expansion path. Mandatory navigation or safety fields that cannot fit produce an error without finalizing or skipping the candidate.
## Historical evidence is not live state

Session History reports what an earlier session said or did. It cannot prove
that an external fact is still true.

For example, an earlier turn saying “the pull request is approved” does not
prove that the pull request is approved now. Check the live system for current
status. Pallium labels history results accordingly and identifies known
superseded guidance.

## Scope and governance

History search and expansion enforce the requesting session's container and
visibility scope before returning content. The active session is attribution,
not a candidate filter. An explicitly supplied `source_thread_ref` narrows
candidates exactly and never broadens; exact-work search intersects it.
`actor_ref` is stored attribution metadata: omit it to search every
otherwise-eligible actor, or supply it as an exact
metadata filter. Expansion applies the same checks to every surrounding turn.

Pallium records lookup and expansion telemetry, supports raw-turn forgetting,
and applies redaction on both search and expansion.

The current scope model is intended for one local operator. It is not a
cross-user sharing or authorization system.

## Available now

- broad topic search across accessible earlier sessions with `pallium_search_history`
- exact-reference search with `pallium_search_history_by_work_ref`
- bounded, revision-checked result paging for both search tools
- bounded surrounding-turn expansion and same-source continuation with `pallium_expand_source`
- linked lookup and expansion telemetry
- redaction, visibility checks, and forgetting
- safeguards that distinguish outdated guidance from current replacements
- structural references from supported integrations, including a non-base Git
  branch, an exact Agent Workflow Work Record when safely resolved, and
  explicitly supplied references
- Session History recording and search without an LLM provider

## Package behavior

Semantic packages are optional and disabled by default. A derived package needs
explicit `enabled = true`; provider-backed packages also need `llm_provider` and
`model`. Disabling a package preserves stored derived data but prevents new
processing. Source-only queries continue to work without an active package;
normal derived queries return `decision_reason: "semantic_package_unavailable"`.

Additional navigation and temporary on-demand compression options remain planned.

Agent Workflow is not required to use Session History. Its Work Record is one
optional structural reference when an integration can resolve it safely.

## What Session History is not

- a record of every tool call forever
- a complete machine audit log
- proof that old external state remains current
- generated summaries by default
- cross-user sharing without an explicit authorization contract

For API details, see [HTTP API](http-api.md). For the direction and validation
plan, see the [Session History vNext strategy](context/strategy-vnext.md).
