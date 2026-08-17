# source-expansion-visibility-enforcement

`get_source_context` (pallium_expand_source) enforces neighbor/anchor visibility via `is_visible(...)`
but never passes `query_visibility` — and the MCP client drops the caller's visibility entirely
(`app/mcp/client.py` get_source_context sends only container_ref + query_actor_ref). So a caller who
queried with visibility="public" falls through `is_visible`'s container/private branch and receives
PRIVATE same-container neighbor turns. The advertised `visibility` control is a no-op on expansion. This
threads the caller's visibility through client → route → service → every `is_visible` call, mirroring
the `/query` scope handling, so a public query cannot surface private neighbors.

<!-- agent-workflow:start -->
**Outcome:**
`get_source_context` authorizes the anchor, every neighbor, and supported memories against the CALLER's
resolved `query_visibility` (threaded from the MCP/HTTP boundary), identical to how `/query` scopes
results. A public-context query never returns private same-container turns as anchor or neighbor; a
private/container-context query is unchanged (its own container stays visible). Invalid visibility values
are rejected. No change to redaction, forgotten-skip, window/order, or the private-context read behavior.

**Target:**
`core/service.py` (`get_source_context`: add `query_visibility` param; pass into all 3 `is_visible`
calls), `app/mcp/client.py` (send caller visibility on get_source_context), `api/routes.py`
(`/source/{id}/context` GET: add a `query_visibility: Visibility | None = None` route param — query
param, NOT a body; the `Visibility` literal gives 422-on-invalid for free), tests (E2E visibility matrix
HTTP + MCP), `docs/context/decisions.md`. NOTE: no new Pydantic request model — the route is GET/query
params (`SourceContextResponse` is response-only).

**Scope:**
- `core/service.py` `get_source_context`: add `query_visibility: str | None = None`; pass
  `query_visibility=query_visibility` into the anchor gate (`:1554`), the neighbor `_keep` (`:1582`), and
  the supported-memories `is_visible` call. Do NOT change the `effective_container`/`effective_actor_ref`
  anchor-inheritance (that matches get_memory_expand); the leak is the missing visibility, not the
  inheritance.
- Missing visibility → treat as the `/query` path does (container/private context = current read
  behavior; NOT deny-all, which would break normal single-user reads). Invalid (unknown) value → reject
  with a defined error. (Confirm exact policy in clean-context review.)
- Thread visibility: MCP client `get_source_context` sends the resolved `visibility`; HTTP route +
  schema accept `query_visibility` and forward it.
- Tests: E2E visibility matrix over an ordered public/private/actor-A/actor-B sequence, both surfaces;
  lifecycle neighbors; window/order preserved after unauthorized drops.

**Constraints:**
- Touches red `core/service.py` — no new red passthrough; only add a param to the existing method +
  thread it.
- MUST NOT change private/container-context read behavior (single-user local default) — only stop the
  public-query private-neighbor leak.
- Redaction, forgotten-skip, bounded window, nearest-first fill, anchor-always-included: all unchanged.
- No internal/product names. No query/ingest correctness change.

**Completion criteria:**
A public-context expansion never returns a private neighbor or a private anchor; an actor-A private
query never returns actor-B private turns; a private/container-context query returns the same neighbors
as today; invalid visibility rejected; identical behavior on HTTP and MCP; window size/order correct
after unauthorized neighbors removed; full suite + redline + workflow checks green.

**Risk:** High

**Complexity:** Moderate

**Reason:** Redline: `core/service.py` + `api/routes.py` guarded/red; this is a privacy/authorization
fix (private-data exposure) → High. Multi-file (service + client + route + schema + tests) → Moderate.
Expanded shape; clean-context plan review required.

**Discovery:**
- `core/service.py:1554-1558` anchor gate, `:1582-1586` neighbor `_keep`, and the supported-memories
  block all call `is_visible(...)` WITHOUT `query_visibility` (defaults None).
- `is_visible` (`core/visibility.py:24-31`): `query_visibility="public"` → candidate must be public +
  actor_ref null (`:42-43`); with `query_visibility=None` and a set container it falls to the
  container/private branch (same-container visible) — the leak for public-intent queries.
- `effective_container = container_ref or anchor.container_ref` (`:1552`), `effective_actor_ref =
  query_actor_ref or anchor.actor_ref` (`:1553`) — anchor-scope inheritance mirrors get_memory_expand.
- MCP client `get_source_context` (`app/mcp/client.py:138-178`) sends only container_ref + query_actor_ref;
  visibility dropped. `pallium_expand_source` resolves `visibility` into context (per earlier review).

**Material assumptions:**
- ASSUMPTION: threading `query_visibility` into the 3 is_visible calls fixes the leak without changing
  private-context reads. DISPROVED BY: a private/container-context test that previously returned a
  neighbor now doesn't. ACTION: confirm missing→container-context default matches /query.
- ASSUMPTION: `pallium_expand_source`/context already resolves `visibility`; only forwarding is missing.
  DISPROVED BY: no resolved visibility on the context. ACTION: resolve it like the /query MCP path.

**Plan:**
1. Clean-context plan review (redline zones + missing-vs-invalid visibility policy + confirm no private-
   context read regression + anchor-inheritance is not itself a leak).
2. `core/service.py`: add `query_visibility` param; pass into all 3 `is_visible` calls; reject invalid.
3. `app/mcp/client.py`: send resolved `visibility` on get_source_context.
4. `api/schemas.py` + `api/routes.py`: accept + forward `query_visibility` on the context route.
5. Tests: E2E visibility matrix (HTTP + MCP), lifecycle neighbors, window/order.
6. docs/context/decisions.md: record the visibility-threading fix + missing/invalid policy.
7. PR → CI green → resolve threads → merge.

**Verification plan:**
- Public-query leak closed → E2E: public-context expansion of a public anchor with private same-container neighbors returns NO private neighbor. → maps to Completion "public never returns private".
- Actor isolation → actor-A private query never returns actor-B private turns. → maps to "actor-A never returns actor-B".
- No read regression → private/container-context query returns the same neighbor set as pre-change. → maps to "private/container-context unchanged".
- Invalid visibility → rejected with defined error. → maps to "invalid rejected".
- Surface parity → identical on HTTP + MCP. → maps to "identical on HTTP and MCP".
- Window/order preserved after drops. → maps to "window/order correct".
- Zones clean; no red passthrough → clean-context redline verdict under Plan review.
- CI: full suite, agent-workflow, redline.

**Plan review:**
<!-- Clean-context review DONE (Explore agent). Verdict: sound, minimal, no new red passthrough.
CONFIRMED: None→private-context mirrors /query exactly (deny-all would break green source-context tests +
single-user reads); "public" closes the leak because is_visible's branch order short-circuits before the
permissive same-container fallthrough; anchor-scope inheritance is NOT a leak once visibility is threaded
— leave it. CRITICAL: reject invalid visibility at the BOUNDARY (type route param as Visibility literal →
422); do NOT rely on is_visible (it treats unknown strings as private-context). Route is GET/query-params
— no new Pydantic model. Fix ALL THREE is_visible calls (anchor :1554, neighbor :1582, supported :1630).
MCP client must add query_visibility from ctx.visibility (server already resolves it). Sibling defect:
get_memory_expand/pallium_expand has the identical leak — tracked as a separate follow-up. Full report
under ## Plan review. -->

**Approvals:** High task — clean-context plan review required; will record human approval before merge
per the red-zone architecture-review checkpoint.

**Exceptions:** —

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

- `core/service.py` `get_source_context`: added `query_visibility: str | None =
  None` param. Threaded `query_visibility=query_visibility` into all THREE
  `is_visible(...)` calls — anchor gate, neighbor `_keep`, and the
  supported-memories block. Added a defensive boundary guard: if
  `query_visibility` is not None and not one of `public/container/private/global`
  it raises `ValueError`. Did NOT change `effective_container` /
  `effective_actor_ref` anchor inheritance.
- `api/routes.py` `GET /source/{source_item_id}/context`: added
  `query_visibility: Visibility | None = None` route/query param (imported
  `Visibility` from `core.visibility`) — typing it as the literal gives 422 on
  unknown values for free. Forwarded it to `service.get_source_context(...)` and
  added a `ValueError -> HTTPException(400)` handler alongside the existing
  `KeyError -> 404`.
- `app/mcp/client.py` `get_source_context`: forward the caller's resolved
  visibility — `if self._ctx.visibility: params["query_visibility"] =
  self._ctx.visibility`. Server-side `pallium_expand_source` already resolves
  visibility into ctx; unchanged.
- `tests/test_source_context_visibility.py` (new): E2E visibility matrix over an
  ordered same-container thread (public / actor-A private / public anchor /
  actor-B private / public) plus MCP client payload assertions.
- `docs/context/decisions.md`: added 2026-08-17 entry.

## Evidence

- `pytest tests/test_source_context_visibility.py tests/test_source_context.py
  tests/test_visibility_scope.py -x -q` -> 35 passed, 1 skipped (the skip was the
  mcp[cli] importorskip, since removed — see below).
- `pytest tests/test_source_context_visibility.py -q` -> 10 passed (includes both
  MCP client payload tests; importorskip removed because `PalliumMcpClient`
  depends only on httpx + PalliumContext, not the `mcp` package).
- `pytest tests/test_source_context_visibility.py tests/test_source_context.py
  tests/test_visibility_scope.py tests/test_source_forget_authorization.py
  tests/test_mcp_client.py tests/test_search_history_tool.py -q` -> 74 passed,
  1 skipped.
- `pytest tests/ -q -k "source or visib or query or expand or retriev or route
  or mcp"` -> 680 passed, 3 skipped.

Invalid-value rejection is wired at the boundary: the route param is typed as the
`Visibility` literal (FastAPI 422 on unknown value), backed by a defensive
`ValueError` guard in the service method (mapped to 400 in the route). `is_visible`
is NOT relied on to reject unknown strings.
