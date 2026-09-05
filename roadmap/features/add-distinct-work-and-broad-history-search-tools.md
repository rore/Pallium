---
id: add-distinct-work-and-broad-history-search-tools
title: Split work-scoped and broad Session History search
status: queued
priority: high
commitment: committed
milestone: pallium-vnext-session-history
lane: product-surface
---

## Product outcome

Agents get two explicit choices: resume one known work item by exact identity, or
search broadly across prior session history. The interface makes intent obvious
without creating another retrieval system.

## Agent-facing contract

### Work-scoped search

`pallium_search_history_by_work_ref(work_ref, query?)`

- Requires one valid structural work reference; Pallium normalizes it and then matches it exactly.
- Searches raw SourceItems carrying that reference.
- With `query` omitted or whitespace-only, returns newest eligible exact-reference items; a nonblank query (including punctuation-only text) ranks or narrows only within that reference.
- This is deliberately narrow: it can miss related work stored under another work reference or with no work reference.
- Supports branch, Agent Workflow Work Record, Jira, PR, issue, incident, and other
  structurally supplied references from the shared work-reference contract.

### Broad search

`pallium_search_history(query)`

- Searches relevant raw history by topic across eligible work items and sessions; use this when the exact work reference is unknown or related work may live under other references.
- Supports the short keyword-style queries agents use in practice.
- The existing optional work_refs argument remains only as a compatibility filter; new one-work callers should use pallium_search_history_by_work_ref.
- Shows or groups work references when present while keeping unreferenced history
  searchable.
- Uses session only as fallback grouping, never as a semantic work boundary.

## Shared implementation

- Both tools reuse the shipped source-only retrieval, lexical/vector fusion,
  visibility, redaction, forgetting, audit, deduplication, and source-context
  expansion paths.
- Enforce `QueryFilters.work_refs` for raw SourceItems before visible top-K
  selection. The current raw filter omits this check.
- Keep responses within hard result and character budgets using compact text or
  Markdown. Preserve only the source identity, recorded time, useful work/session
  cues, replacement/freshness warning, and lookup identity needed for expansion.
- Record the tool/mode and delivered results through the existing lookup telemetry.

## Out of scope

- A second retrieval stack, new ranking engine, or new expansion mechanism.
- Requiring complete natural-language questions.
- Hiding unreferenced history from broad search.
- Inferring work identity semantically when no exact work reference is supplied.

## Done when

1. Exact work-scoped search never returns a raw item without the requested
   normalized work reference; similar-looking references do not match.
2. Broad search still finds referenced and unreferenced history and handles short,
   Unicode, and punctuation-heavy queries.
3. Both MCP tools reuse the same source-only query and context-expansion surfaces,
   return bounded agent-readable output, and record exact delivered-result
   telemetry.
4. Public MCP/HTTP E2E coverage includes missing/invalid/unknown work refs,
   empty/one/max/over-max results, multiple refs, normalization variants, forgotten
   sources, visibility isolation, stale replacements, duplicate results, and
   search-to-expansion lifecycle.
5. Cross-container, actor, visibility, and lifecycle rules remain unchanged and
   fail closed where they do today.

## Dependencies

Follows `add-structural-session-work-references`. Refines the shipped
`add-agent-historical-lookup-tool` into two deliberate agent-facing operations while
reusing `add-raw-historical-search-mode` and `add-source-context-expansion`.
