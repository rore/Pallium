# surface-retrieval-fail-closed-reason

When a retrieval call reaches Pallium without a visibility context (`container_ref` +
`visibility`), the shared query guard fails closed and returns **zero results labelled
`decision_reason: "no_relevant_memory"`** — indistinguishable from "searched, found nothing."
The true reason (`fail_closed_reason: "query_visibility_context_required"`) only appears in the
`/query/debug` trace, never in the normal `/query` response. An agent (or a human debugging via
curl/MCP) sees an empty result and misdiagnoses it as broken retrieval or an empty index. The MCP
retrieval tools also don't document that the visibility context is required. Make the "why nothing
came back" legible in the normal response, and document the contract on the tools.

<!-- agent-workflow:start -->
**Outcome:**
A retrieval call that fails closed on a missing visibility context reports a distinct, self-explaining
`decision_reason` (not `no_relevant_memory`) in the **normal** `/query` response — so callers see *why*
without needing `/query/debug`. The retrieval MCP tools' docstrings state that `container_ref` +
`visibility` are required and what happens without them.

**Target:**
`core/query.py` (the shared fail-closed guard, ~L88-116) and `app/mcp/server.py` (docstrings for the
retrieval tools: `pallium_query`, `pallium_search_history`, `pallium_expand`, `pallium_expand_source`).
No change to the auto-injection hooks (already pass full context) or to the visibility enforcement itself.

**Scope:**
- `core/query.py`: at the visibility fail-closed guard, set `decision_reason` to a distinct value
  (e.g. `"visibility_context_required"`) instead of `"no_relevant_memory"`. Keep `should_inject=False`,
  empty results, and the existing `trace.visibility.fail_closed_reason`. This single guard covers both
  `pallium_query` and `pallium_search_history` (source mode runs *after* it) and `/item-and-query` (wraps
  the same query path).
- `app/mcp/server.py`: one line per retrieval tool docstring — needs `container_ref` + `visibility`;
  omitting them returns no results with `decision_reason: visibility_context_required`.
- Verify the by-ID expansion endpoints (`/memory/{id}/expand`, `/source/{id}/context`) already fail
  legibly (not-found / forbidden are distinct from empty). Only widen scope to them if they silently
  conflate — report before doing so.

**Constraints:**
- Observability/contract-legibility only: no change to *what* is retrieved, the visibility enforcement,
  or the injection policy. Same inputs still fail closed — only the reported reason changes.
- `decision_reason` is a free-text `String` column (`storage/sqlite_schema.py:193`) with no enum
  constraint — the new value needs no schema migration. Confirm no consumer switches on the exact string
  `"no_relevant_memory"` for the missing-context case.
- Don't force `PALLIUM_CONTAINER_REF`/`PALLIUM_VISIBILITY` env defaults on the shared MCP server — it
  serves any repo, so a fixed env context would be wrong. Explicit-or-surfaced-error is the design.

**Completion criteria:**
1. `POST /query` with no `container_ref`/`visibility` (visibility-requiring plugin) →
   `decision_reason == "visibility_context_required"`, `results == []`, `should_inject == false`.
2. `POST /query` with both present → unchanged behavior (real results / genuine `no_relevant_memory`).
3. `/query/debug` still carries `fail_closed_reason` (unchanged).
4. Retrieval MCP tool docstrings state the requirement.
5. Existing query/routing/visibility tests pass; a test asserts criterion 1's new reason.

**Risk:** High

**Complexity:** Moderate

**Reason:** Edits guarded `core/` (retrieval decision path) and `app/`. Changes an observable
`decision_reason` value — a downstream-visible contract — so High despite the small diff. Single-point
change + docstrings + tests → Moderate.

**Discovery:**
- Single shared guard: `core/query.py:88-116`. `plugin.requires_visibility_context and (container_ref is
  None or visibility is None)` → returns empty `QueryResult` with `fail_closed_reason=
  "query_visibility_context_required"` (L103) but `decision_reason="no_relevant_memory"` (L111). The
  conflation is exactly these two adjacent lines.
- Both retrieval MCP tools hit `/query`: `app/mcp/client.py:37` (query) and `:70` (search_history).
  `source_only` branch is `core/query.py:126`, *after* the guard → covered by the one fix.
- `resolve_context` (`app/mcp/context.py:32-49`) fills `container_ref`/`visibility` from explicit args or
  `PALLIUM_*` env, else None → shared server has no per-repo env, so the agent must pass them.
- Auto-injection path already correct: `integrations/claude-code/hooks/user_prompt_submit.py:55-72` and
  `post_tool_use.py:175` pass `visibility:"private"` + resolved `container_ref`. Out of scope.
- Funnel writers (`core/service.py:733` lookup, `:1631` expansion) are downstream of the guard;
  unaffected by a reason-string change.

**Material assumptions:**
- *No consumer branches on the literal `"no_relevant_memory"` specifically for the missing-context case.*
  `decision_reason` is free String; `query_stats.skip_reasons` just tallies whatever string it gets (a new
  bucket is a feature, not a break). Action: grep tests + consumers for the literal before finalizing;
  if a live consumer keys on it, reconsider naming.
- *The by-ID expansion endpoints don't share this silent-conflation shape.* They fetch a specific object
  with visibility enforcement, so "not found"/"forbidden" already differ from "empty." Action: verify at
  implement; report before widening scope if wrong.

**Plan:**
1. `core/query.py`: change the guard's `decision_reason` to `"visibility_context_required"`. One line;
   leave `fail_closed_reason` and everything else intact.
2. Grep tests + non-test consumers for `"no_relevant_memory"`; update any test that asserts it for the
   missing-context path; confirm no behavioral consumer keys on it.
3. `app/mcp/server.py`: add the one-line contract note to the four retrieval tool docstrings.
4. Verify expansion endpoints fail legibly (read + a quick check); note finding.
5. Tests: assert criterion 1 (new reason) and criterion 2 (unchanged with context).

**Verification plan:**
- Criteria 1-2 → unit/integration test in the query/visibility test module: build a visibility-requiring
  plugin, call query without context (assert new reason) and with context (assert unchanged).
- Criterion 3 → existing `/query/debug` trace test still green.
- Criterion 4 → docstring inspection (not unit-tested).
- Criterion 5 → `pytest tests/ -q` on the affected slices (query, routing, visibility, mcp).
- redline + agent-workflow CI.

**Plan review:**
Self-review (budget): single-point change on a pre-mapped guard; the red-zone architecture-review
checkpoint is shadow-advisory (non-blocking). The one genuine risk (a consumer keying on the old string)
is discharged by the grep in Plan step 2 before finalizing.

**Approvals:**
Approved by user 2026-08-19: "we should make sure every search or query endpoint is handled so an agent
always knows how to call it and why it doesn't return results" + "go".

**Exceptions:**
—

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

- `core/query.py` (guard ~L107): changed the fail-closed `decision_reason` from `"no_relevant_memory"` to
  `"visibility_context_required"`. `fail_closed_reason`, empty results, `should_inject=False` all unchanged.
- Grep confirmed (Plan step 2): the other `no_relevant_memory` sites are the *genuine* retrieval-ran-nothing-
  matched path (`semantic/agent_conversation_memory_routing_selection.py`) — untouched. No behavioral consumer
  keys on the literal for the missing-context case; `query_stats.skip_reasons` just tallies whatever string it
  gets (new bucket = feature). The three tests that exercise the guard assert `fail_closed_reason` / `results
  == []` / skip counts, none the old `decision_reason` — so none broke.
- `app/mcp/server.py`: added the visibility-context requirement to `pallium_query` and `pallium_search_history`
  docstrings (the two tools that route through `/query`).
- Expansion endpoints (WR step 4): verified they already fail **legibly** — `get_memory_expand` → 404 "memory
  object not found"; `get_source_context` → 404/400 with explicit detail. No silent conflation, so left
  untouched (scope stays narrow). `pallium_expand`/`pallium_expand_source` docstrings unchanged.
- Docs: added `visibility_context_required` to the decision_reason tables in `docs/http-api.md` and
  `docs/how-it-works.md`.
- Tests: `tests/test_visibility_scope.py::test_missing_container_ref_fails_closed` now also asserts
  `decision_reason == "visibility_context_required"` (criterion 1).

**Verification:** `pytest tests/test_visibility_scope.py tests/test_source_only_search.py tests/test_query_stats.py
tests/test_query_policy.py tests/test_mcp_server.py tests/test_mcp_client.py -q` → 70 passed, 2 skipped.
Criteria 1-4 covered; criterion 5 = the passing slices above (broader run at PR CI).
