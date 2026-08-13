# Task: add-agent-historical-lookup-tool

Pallium vNext P1. Execution context: `docs/designs/015-vnext-historical-work-execution.md` (Phase 1).
Part of the overnight P1 run (auto-merge when green; resolve blockers with best judgment).

<!-- agent-workflow:start -->
**Outcome:**
An agent can explicitly search its own prior raw work via a new MCP tool (`pallium_search_history`) that invokes the source-only retrieval mode. Each result is a raw source turn (excerpt + timestamp + thread/actor + stable `source_item_id` + `raw_rank`), attributed as an agent pull, and carrying the `lookup_event_id` for the measurement event chain. Guidance tells the agent WHEN to reach for it.

**Target:**
pallium

**Scope:**
`app/mcp/client.py` (new `search_history` method: POST `/query` with `source_only=True`, `trigger_origin="agent_pull"`, scope from ctx + optional filters); `app/mcp/server.py` (new `@server.tool() pallium_search_history`); `integrations/claude-code/claude_md_block.py` (+ `integrations/codex/AGENTS.md`) — a "when to search prior work" bullet (Done-When #3); `tests/test_mcp_integration.py`. NOT: `api/`, `core/`, `schemas.py` (the backend contract — `source_only`, `agent_pull`, `raw_rank`, `lookup_event_id` — already shipped in PR #11 and the P0 telemetry). NOT source-context expansion (next P1 item).

**Constraints:**
Tool is dead-simple by default (query + limit; scope from context; advanced filters optional). Hardcode `trigger_origin="agent_pull"` in the client method (not agent-settable) so every call is unambiguously attributed in `query_audit_log`. Reuse the existing scope (`container_ref`/`thread_ref`/`actor_ref`/`visibility`) — no new scope concept. `source_item_id` must round-trip so it can later feed source-context expansion + `pallium_forget_source`. Tool docstring and CLAUDE.md guidance are independently tunable surfaces (Experiment 1 variables) — don't duplicate heavy "when to search" prompting in both. No internal/external product names in committed docs/tests.

**Completion criteria:**
1. Calling `pallium_search_history(query, ...)` returns raw source turns (source-only), each with `source_item_id` + `raw_rank`, scoped to the agent's context → MCP integration test asserts `source_only`/`trigger_origin` reach the API and results are `source_hit`s.
2. The call is attributed as an agent pull (`trigger_origin="agent_pull"`) and surfaces `lookup_event_id` when audit logging is enabled → test with audit logging on.
3. Agent guidance (CLAUDE.md/AGENTS.md block) tells the agent when to search prior work → doc bullet present.
4. `source_item_id` round-trips through the tool (usable by expansion/forget) → asserted in the test.

**Risk:** Elevated

**Complexity:** Simple

**Reason:**
No guarded RED paths (`app/mcp/` is not `api/`/`core/`); the backend contract already shipped and is tested. Elevated (not Routine) because it adds a new agent-facing capability + attribution semantics that Experiment 1 depends on. Simple: ~4 files, additive, thin surface. Redline pre-edit verdict runs as the first step to confirm (may raise).

**Discovery:**
(from a read-only MCP-surface investigation, 2026-08-13 — file:line cited)
- Tools are registered only via `@server.tool()` in `create_server()` (`app/mcp/server.py:32-383`); FastMCP auto-discovers — NO separate manifest. Uniform pattern: async fn + typed params (scope defaults None) + docstring; `ctx = resolve_context(...)`; `if not ctx.is_configured: return NOT_CONFIGURED_MSG`; `client = PalliumMcpClient(ctx)`; `return json.dumps(result, indent=2, default=str)`.
- `pallium_query` (`server.py:35-54`) passes only query/limit + 4 scope params; does NOT pass `source_only`/`trigger_origin` → the new tool needs its own client method.
- `PalliumMcpClient.query` (`client.py:34-37`) posts `{text,limit}` + `_scope_params()` (`client.py:25-32`, pulls container/thread/actor/visibility off ctx, omits None). Optional-field passthrough pattern: `remember_memory` (`client.py:195-218`), `forget_source` (`client.py:271-294`).
- `/query` already accepts `source_only` (`api/routes.py:415` region, shipped PR #11), validates `trigger_origin` with `agent_pull`/`mcp_pull` whitelisted + deliberately NOT in the abstention-bypass set (`api/routes.py:242-260`), and returns `lookup_event_id` (`schemas.py` QueryResponse) when `audit_log_enabled`.
- `QueryResultResponse` carries `source_item_id`, `excerpt`, `occurred_at`, `actor_ref`, `thread_ref`, `raw_rank`, etc. — the source-block shape is already serialized. Returning raw `/query` JSON is sufficient.
- MCP test harness: `tests/test_mcp_integration.py` — `pallium_asgi_app` fixture (vector disabled), `mcp_client` fixture monkeypatches `client._post` with an ASGITransport poster; `TestMcpClientPassthrough` asserts on returned dict. A `search_history` built on `self._post("/query", ...)` works with that monkeypatch.
- Guidance copy: `integrations/claude-code/claude_md_block.py` `CLAUDE_MD_BLOCK` (~:22-31 "reach for these when you need them"); parallel `integrations/codex/AGENTS.md`. Human-facing tool lists in README/docs are optional refresh.

**Material assumptions:**
1. Tool name `pallium_search_history` (distinct from `pallium_query`/`pallium_forget_source`). Disproof: reviewer prefers another name. Action: rename (mechanical).
2. Returning the raw `/query` JSON is acceptable output (consistent with `pallium_query`). Disproof: payloads too token-heavy / need trimming to the source-block fields. Action: add a compact projection in the tool.
3. `trigger_origin="agent_pull"` hardcoded is the right attribution (roadmap names both agent_pull/mcp_pull; pick one). Disproof: measurement wants `mcp_pull`. Action: switch the constant.
4. `lookup_event_id` is None unless `audit_log_enabled` — tests that assert it must enable audit logging. (Confirmed risk; handle in tests.)

**Plan:**
1. Redline pre-edit verdict (via `/agent-workflow`).
2. `app/mcp/client.py`: `async def search_history(self, text, *, limit=5, source_type=None, role=None, artifact_kind=None, work_refs=None) -> dict` — payload `{text, limit, source_only: True, trigger_origin: "agent_pull"}` + `_scope_params()` + optional filters when non-None; `await self._post("/query", payload)`.
3. `app/mcp/server.py`: `@server.tool() async def pallium_search_history(query, limit=5, container_ref=None, thread_ref=None, actor_ref=None, visibility=None, source_type=None, role=None, artifact_kind=None, work_refs=None) -> str` — standard resolve_context/is_configured/json.dumps; concise docstring describing WHAT + WHEN (raw prior work; distinct from pallium_query proactive recall).
4. `integrations/claude-code/claude_md_block.py` (+ `integrations/codex/AGENTS.md`): one bullet on when to search prior work.
5. Tests (`tests/test_mcp_integration.py`): assert `search_history` posts `source_only=True` + `trigger_origin="agent_pull"`; end-to-end returns `source_hit`s with `source_item_id` + `raw_rank`; with audit logging enabled, `lookup_event_id` present; scope from ctx applied.
Stop conditions: if attribution (`trigger_origin`) can't be set without an API change → reconsider (investigation says it can). If the tool would need reshaping beyond raw JSON to be usable → note + minimal projection.

**Verification plan:**
1. `search_history` client posts the right payload (source_only + agent_pull + scope) → unit/passthrough test.
2. End-to-end tool returns raw source turns with stable ids + raw_rank; forgotten/visibility inherited from the mode → integration test.
3. `lookup_event_id` surfaced with audit logging on → test.
4. Guidance bullet present → doc check.
5. Full suite green → `python -m pytest tests/ -q` (real interpreter).

**Plan review:**
Clean-context agent review completed (2026-08-13) — reviewed the implemented branch. Verdict: sound; no SEV-1 correctness/attribution breaks. Confirmed: client POSTs `/query` with `source_only=True` + hardcoded `trigger_origin="agent_pull"` (in `_VALID_TRIGGER_ORIGINS`, NOT in the bypass set — normal routing path), no tool↔client param drift, `pallium_query`/proactive path untouched, docstring vs CLAUDE.md guidance not duplicated. Findings adopted:
- SEV-2: `lookup_event_id` was only asserted present (key), never non-None, because the test app didn't enable audit logging → completion criterion #2 (the measurement event chain) was unverified. FIXED: test fixture now sets `observability=ObservabilityConfig(query_audit_log=True)` and asserts `result["lookup_event_id"] is not None`. (Same as CodeRabbit's comment #2 on PR #12.)
- SEV-3 (accepted, note only): the `@server.tool()` wrapper itself has no automated coverage because `test_mcp_integration.py` is `importorskip("mcp")` and mcp isn't installed in CI; the client method (the real logic) is covered. Manual verification confirmed all 10 tool params forward correctly. Acceptable given the CI constraint.

**Approvals:**
Approved by user 2026-08-13: "yes, auto merge if all green" — overnight mandate to complete all P1 work, auto-merging each PR when CI + review are fully green. Blocker policy: "try to resolve blockers if you can, only break if you really need me."

**Exceptions:**
—

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

Shipped (branch `feat/add-agent-historical-lookup-tool`):
- `app/mcp/client.py`: `search_history(text, *, limit, source_type, role, artifact_kind, work_refs)` — POSTs `/query` with `source_only=True` + `trigger_origin="agent_pull"` hardcoded, scope from ctx, optional filters when non-None.
- `app/mcp/server.py`: `@server.tool() pallium_search_history(...)` — standard resolve_context/is_configured/json.dumps; docstring frames it as raw prior-work lookup distinct from `pallium_query`.
- `integrations/claude-code/claude_md_block.py` + `integrations/codex/AGENTS.md`: a "when to search prior work" bullet.
- `tests/test_search_history_tool.py`: 3 tests (attribution payload, e2e source hits with stable id + raw_rank + lookup_event_id key, unset-filter omission). Placed OUTSIDE `test_mcp_integration.py` because that file is `importorskip("mcp")` — skipped in CI too, so tool tests there would never run. The client method carries the real logic and needs no `mcp`.

Verification: `pytest tests/test_search_history_tool.py` → 3 passed. Full `pytest tests/` → 3398 passed, 1 pre-existing failure (`test_config.py::test_prompt_variants_legacy_fallback_unaffected`, fails on main, unrelated), 15 skipped, 2 xfailed.

Note: no `api/`/`core/`/`schemas.py` changes — `source_only`, `agent_pull`, `raw_rank`, `lookup_event_id` all shipped in PR #11 + P0 telemetry.

(previously: in progress — overnight P1 run)
