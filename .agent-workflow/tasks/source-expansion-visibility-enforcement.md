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
calls), `app/mcp/client.py` (send caller visibility), `api/routes.py` + `api/schemas.py` (accept/forward
`query_visibility` on `/source/{id}/context`), `app/mcp/server.py` (pallium_expand_source already
resolves `visibility` in context — forward it), tests (E2E visibility matrix HTTP + MCP),
`docs/context/decisions.md`.

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
<!-- Clean-context review pending. -->

**Approvals:** High task — clean-context plan review required; will record human approval before merge
per the red-zone architecture-review checkpoint.

**Exceptions:** —

**State:** Ready to implement
<!-- agent-workflow:end -->
