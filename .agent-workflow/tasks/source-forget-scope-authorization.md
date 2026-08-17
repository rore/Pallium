# source-forget-scope-authorization

Single-item raw-turn forget currently mutates by primary-key `source_item_id` with no ownership check
(`core/service.py:1101-1104` → `storage/sqlite.py:616-643`); `actor_ref` is written to `forgotten_by`
as audit only, never compared. Any caller holding an id can soft-delete any turn in any container (IDOR
on a destructive mutation). This adds a service-layer authorization gate: load the target source item,
authorize the caller's scope against it, deny on mismatch. The container-bounded scope-forget branch
(`forget_source_scope`) already models the trust boundary; the single-item branch just lacks the gate.

<!-- agent-workflow:start -->
**Outcome:**
Single-item `forget_source` authorizes the caller before mutating: a caller may forget a raw turn only
when it is in the caller's container scope and (for actor-owned turns) the caller is that actor. Cross-
actor / cross-container forget by raw `source_id` is denied through both HTTP and MCP with a defined
error, no `forgotten_at` written on denial. Legitimate owner-forgets-own still works. Scope-forget
behavior unchanged. No query/ingest correctness change.

**Target:**
`core/service.py` (forget_source single-item branch: compute authorization + missing-identity policy),
`storage/sqlite.py` (`forget_source_item` gains optional `expected_container_ref`/`expected_actor_ref`
enforced atomically in its existing `_with_retry` txn), `storage/base.py` (signature), `api/schemas.py`
(`ForgetSourceRequest` gains `caller_container_ref` — Pydantic drops unknown fields otherwise),
`api/routes.py` (forward caller scope + map deny→403), `app/mcp/client.py` (inject ctx container as
caller scope on single-item forget), `app/config.py` (new trust flag), `tests` (E2E HTTP + MCP),
`docs/context/decisions.md`. Existing E2E `tests/test_raw_turn_forgetting.py:221` (forgets with no
identity) must be updated or covered by the local-trust default.

**Scope:**
- Enforce the SAME workspace/container-scoped authorization on BOTH delete paths — single-item
  (`forget_source_item`) AND bulk (`forget_source_scope`) — so bulk is not a bypass. Enforced atomically
  inside the storage `_do(session)` closures via optional `expected_container_ref`/`expected_actor_ref`.
- Trust-mode policy (computed in `core/service.py.forget_source`): container match required when caller
  identity/scope is present; MISSING caller identity is allowed ONLY in single-user compatibility mode
  (default), denied in strict multi-user mode; supplied-but-mismatched identity/scope is ALWAYS denied,
  even in compatibility mode.
- New config setting named to mean "trusted single-user compatibility" (not "auth optional"), default =
  compatibility ON. Strict mode = require scoped identity.
- Startup/loopback guard: warn — preferably refuse startup — if the service binds beyond loopback while
  compatibility mode is enabled.
- Thread caller scope to the single-item path: MCP client sends ctx container as a caller-scope field
  (distinct from scope-mode `container_ref`); HTTP route + `api/schemas.py` accept/forward it.
- Preserve idempotency + KeyError-on-missing for authorized calls. Untagged (NULL-container) turns:
  deletable in compatibility mode; denied in strict mode (admin migration path deferred/documented).
- Tests: HTTP + MCP E2E permission matrix (production-shaped identity); single==bulk parity; loopback
  guard; observable allow/deny state; audit distinguishes denied vs successful.

**Constraints:**
- Touches red `core/service.py` — no new red passthrough beyond the existing forget method. Policy is
  computed in the service; storage enforces the predicate atomically (no TOCTOU double-read).
- Bulk and single-item MUST enforce identical scope rules (bulk is not exempt).
- Compatibility mode relaxes ONLY missing identity — never a supplied-but-wrong identity, never a blanket
  auth-optional.
- Deny must be observable (defined error on HTTP + MCP) and must write no `forgotten_at`.
- Honest boundary: strict mode still trusts client-supplied identity — this builds the authorization
  SEAM; real authentication feeding it is a later piece. Record this in decisions.md.
- No internal/product names. No query/ingest behavior change.

**Completion criteria:**
Owner's workspace can delete its turn; different workspace denied; supplied-wrong-workspace denied even
in compatibility mode; no-identity allowed only in compatibility mode and denied in strict mode; untagged
legacy turns deletable in compatibility, denied in strict; single AND bulk enforce identical scope rules;
unauthorized attempts mutate nothing and are audited distinctly from successes; successful delete
disappears from search + expansion; repeat delete idempotent; non-loopback + compatibility mode produces
a prominent warning or startup failure; HTTP + MCP E2E use production-shaped identity; full suite +
redline + workflow checks green.

**Risk:** High

**Complexity:** Moderate

**Reason:** Redline: `core/service.py` and `api/routes.py` are in guarded/red paths, and this is an
authorization change on a destructive mutation (security-sensitive) — High. Multi-file (service + MCP
client + route + tests) and an authorization-policy decision → Moderate. Expanded shape; clean-context
plan review required (both redline zones and the soundness of the authorization policy).

**Discovery:**
- Single-item branch: `core/service.py:1101-1104` calls `storage.forget_source_item(id, reason, actor_ref)` with no scope check.
- Storage: `storage/sqlite.py:616-643` loads by PK, writes `forgotten_by=actor_ref` (audit only), idempotent on `forgotten_at`, KeyError if missing.
- Scope-forget (the bounded model to mirror): `storage/sqlite.py:645-676` requires `container_ref` and filters `WHERE container_ref==`.
- MCP client single-item path: `app/mcp/client.py:346-369` sends `source_item_id`+`reason`+`actor_ref` (audit), deliberately NOT container (`:361-365` "never widen a single-item forget into a scope forget").
- `SourceItemRecord` has `container_ref`, `actor_ref`, `visibility` (default "private") — `sqlite_schema.py:33,35,39`; `storage.get_source_item(id)` returns a `SourceItem` (`storage/sqlite.py:288-293`).
- Read authorization policy lives in `core/visibility.py` `is_visible(...)` — candidate visible in same container when query visibility unset; cross-container only public+actor-null.

**Material assumptions:**
- ASSUMPTION: caller authorization scope = (actor_ref, container_ref) available in the MCP/HTTP invocation context. DISPROVED BY: the context cannot supply a container in the default local install (we know actor_ref/container_ref often land NULL). ACTION: define the missing-identity policy explicitly (see open decision) rather than silently allowing.
- ASSUMPTION: forgetting should be OWNERSHIP-gated, not merely read-visibility-gated (a public turn is readable by many but not forgettable by all). DISPROVED BY: reviewer/user preferring visibility-only. ACTION: fall back to is_visible-only gate.
- ASSUMPTION: `get_source_item` is safe to call in the service before mutation (no lock/txn conflict with the subsequent `forget_source_item` retry). DISPROVED BY: a session/txn error. ACTION: fold the load+authorize+mutate into one storage call taking the authorization predicate.

**Plan:**
1. Clean-context plan review — DONE (see ## Plan review). Adopted: (a) add `api/schemas.py`; (b) enforce
   authorization ATOMICALLY inside `forget_source_item` via optional `expected_*` params (no TOCTOU
   double-read); (c) CONTAINER is the load-bearing gate (matches `is_visible` + `forget_source_scope`),
   actor gate is an optional documented overlay; (d) missing identity → explicit trust flag, not
   `NULL==NULL`; (e) document the self-asserted-field residual threat model.
2. `app/config.py`: add `require_scoped_identity` (default False = local-trust). Default preserves the
   live single-user install behavior; True = multi-tenant fail-closed.
3. `storage/sqlite.py` `forget_source_item`: optional `expected_container_ref`/`expected_actor_ref`;
   inside `_do(session)`, after loading the record, if an expectation is set and mismatches → raise a
   defined `PermissionError` (before writing forgotten_at). Defaults None ⇒ no check (keeps direct-storage tests green).
4. `core/service.py` `forget_source`: compute the caller's authorization scope + apply the trust-flag
   missing-identity policy, then call `forget_source_item` with the resolved `expected_*`. Map deny to a
   defined domain error.
5. `api/schemas.py` + `api/routes.py`: `caller_container_ref` on the request; forward it; map deny→403.
6. `app/mcp/client.py`: inject `self._ctx.container_ref` as `caller_container_ref` on single-item forget
   (distinct from scope-mode `container_ref`); MCP server surfaces the deny as a defined tool error.
7. Tests: E2E permission matrix over HTTP + MCP; observable allow/deny; idempotency + nonexistent
   preserved; update the no-identity happy-path test for the chosen trust default.
8. docs/context/decisions.md: record the policy, the trust flag, and the residual threat model.
9. PR → CI green → review threads resolved → merge.

**Verification plan:**
- Deny E2E: actor B (or wrong container) attempts single-item forget of actor A's turn via HTTP → 403; via MCP → defined error; assert no `forgotten_at` written and the turn still returns in owner's source-only search. → maps to Completion "cross-actor/cross-container denied".
- Allow E2E: owner forgets own private and own public turn → success; turn gone from source-only search + expansion. → maps to "owner-forgets-own succeeds".
- Wrong-container-with-correct-id → denied. → maps to "wrong-container denied".
- Lifecycle: nonexistent id (unchanged), already-forgotten (idempotent), concurrent double-forget, forget during in-flight lookup. → maps to "idempotent + nonexistent preserved".
- Audit distinguishes denied vs successful. → maps to "audit distinguishes".
- No red passthrough added; zones clean → clean-context redline verdict under Plan review.
- CI: full suite, agent-workflow, redline.

**Plan review:**
<!-- Clean-context review DONE (Explore agent). Verdict: service layer is the correct boundary; no red
passthrough. Load-bearing fixes adopted: add api/schemas.py; enforce auth atomically inside
forget_source_item (avoid TOCTOU); container-primary gate (actor overlay optional); missing-identity via
explicit trust flag not NULL-equality; document self-asserted-field residual threat model. Full report
under ## Plan review. -->

**Approvals:** Clean-context plan review done. Product decision RESOLVED by user (relayed reviewer
guidance): option 1 — container-scoped auth on BOTH paths + off-by-default single-user compatibility
setting + loopback guard; no author-only overlay; wrong-identity always denied; honest seam caveat.

**Exceptions:** —

**State:** Ready for review
<!-- Implemented: container-scoped auth on both forget paths, atomic in storage;
single_user_trusted_mode flag (default True); loopback refuse-startup guard;
E2E permission-matrix + parity + MCP-client + guard tests green. See
## Implementation and ## Evidence. -->
<!-- agent-workflow:end -->

## Plan review

Clean-context agent review (redline + SQLite correctness + authorization-policy soundness). Read the
WR + `core/service.py` forget path, `storage/sqlite.py` forget methods + `get_source_item`,
`app/mcp/{client,server}.py`, `api/routes.py`, `core/visibility.py`, and `sqlite_schema.py` fresh.

**Verdict: sound boundary, three load-bearing corrections before coding.**

1. **Zone/boundary — OK.** Service is the right authorization layer (mirrors `is_visible` calls in
   `get_memory_expand`/`get_source_context`; storage stays policy-free). No new red passthrough — just a
   param on the existing red `forget_source` + one DTO field. BUT the plan must add `api/schemas.py`
   (`ForgetSourceRequest`, ~:650-654) or the route silently drops `caller_container_ref` (Pydantic
   ignores unknown fields).

2. **TOCTOU — restructure.** Two separate txns (`get_source_item` then `forget_source_item`'s own
   `_with_retry` session) decide against a snapshot the mutation never re-checks. Push the predicate into
   `forget_source_item` via optional `expected_container_ref`/`expected_actor_ref`, compared inside the
   existing `_do(session)` before setting `forgotten_at`. Policy stays computed in the service; storage
   enforces atomically. SQLite serializes writes → clean, removes the double read.

3. **Policy consistency — container-primary.** The proposed actor-ownership gate is stricter than both
   `is_visible` (same-container reads ignore actor) AND `forget_source_scope` (container-only, actor-
   blind). Because scope-forget is actor-blind, the single-item actor gate is trivially bypassable (deny
   single-forget of B's turn → just scope-forget B's container). Recommend: CONTAINER match is the
   load-bearing boundary (consistent with both); actor gate is an OPTIONAL documented overlay. Public
   turns: readable cross-container but not forgettable cross-container — reasonable, matches expand gate.
   Residual threat model to document: over HTTP `actor_ref`/`caller_container_ref` are self-asserted body
   fields, so this closes the "id-only" IDOR but is NOT an authenticated boundary; MCP is stronger (ctx
   from env).

4. **Missing-identity — the open decision.** The bare equality rule is simultaneously too strict and too
   loose: the existing green E2E `tests/test_raw_turn_forgetting.py:221` forgets with NO identity against
   a `container_ref="chat:room-a"` item and asserts success → `None != "chat:room-a"` DENIES it (breaks a
   legitimate local forget); meanwhile a target ingested with `container_ref=NULL` (default local install,
   `PALLIUM_CONTAINER_REF` unset) gives `None == None` → SILENT ALLOW, reproducing the IDOR and violating
   the "never silent allow" constraint. Fix: explicit branch on a deployment trust signal — local-trust
   (default) allows when caller identity is absent (the only way single-user-local forget works; matches
   the expand-source `container_ref or anchor.container_ref` fallback), multi-tenant fails closed. No such
   flag exists today (`app/config.py` has none; the only single/multi tokens are eval taxonomy labels), so
   this introduces a config flag, recorded in decisions.md.

5. **Missed surfaces — none breaking.** No CLI forget path. Direct-storage tests bypass the service gate
   and stay green IF `expected_*` params default None (no check). The service-level both-targets test is
   unaffected. Only the HTTP no-identity happy-path (`:221-224`) must be updated for the trust default.

### Open decision (for the user)
How strict should single-item forget be, given local-trust vs multi-tenant tension? See the AskUserQuestion
posed alongside this review. Recommended: container-primary gate + `require_scoped_identity` flag
(default False = local-trust, no change to the live box; True = multi-tenant fail-closed) + actor overlay
deferred/documented.

## Implementation

Container-scoped authorization on BOTH raw-turn forget paths, enforced atomically in storage. Per-file:

- `core/errors.py`: added `ForgetAuthorizationError(PermissionError)` — the defined domain error for a
  denied forget. Subclasses `PermissionError` so a storage-raised `PermissionError` is caught uniformly.
- `app/config.py`: added top-level `AppConfig.single_user_trusted_mode: bool = True` (env
  `PALLIUM_SINGLE_USER_TRUSTED_MODE`, standard `_resolve_bool_value` pattern). Named for "trusted
  single-user compatibility", NOT "auth optional". True (default) relaxes ONLY the missing-caller-scope
  case; False = strict multi-user.
- `storage/sqlite.py`: `forget_source_item` and `forget_source_scope` each gain optional
  `expected_container_ref` (default None ⇒ no check, keeps direct-storage tests green). Enforced inside the
  existing `_with_retry` `_do(session)`: for single-item, the freshly-loaded record's `container_ref` must
  equal `expected_container_ref` or `PermissionError` is raised BEFORE `forgotten_at` is written; for bulk,
  `expected_container_ref` must equal the requested `container_ref` (the scope is already `WHERE
  container_ref == …`, so this is the parity guard) before any row is mutated. No TOCTOU double-read.
- `core/service.py`: `PalliumService.__init__` gains `single_user_trusted_mode: bool = True` (stored on
  `self._single_user_trusted_mode`). `forget_source` gains `caller_container_ref`. New helper
  `_resolve_forget_scope` computes the trust-mode policy: missing scope → allowed (return None) in trusted
  mode, else raise `ForgetAuthorizationError`; present scope → returned as the storage expectation (the
  mismatch verdict is deferred to storage for atomicity). Both branches wrap the storage call and re-raise
  a storage `PermissionError` as `ForgetAuthorizationError`.
- `app/dependencies.py`: threads `single_user_trusted_mode=resolved_config.single_user_trusted_mode` into
  the `PalliumService(...)` build (no new red passthrough — one existing call site).
- `api/schemas.py`: `ForgetSourceRequest` gains `caller_container_ref: str | None = None` (Pydantic would
  otherwise drop it).
- `api/routes.py`: `/source/forget` forwards `caller_container_ref`; maps `ForgetAuthorizationError` → HTTP
  403. Denied calls write no `forgotten_at`.
- `app/mcp/client.py`: `forget_source` injects `self._ctx.container_ref` as `caller_container_ref` on BOTH
  paths (distinct from the scope-mode `container_ref`). Single-item still never widens into a scope forget.
- `app/mcp/server.py`: `pallium_forget_source` detects the 403 error dict from the client and raises
  `ToolError` (imported from `mcp.server.fastmcp.exceptions`) — deny surfaced as a defined tool error.
- `app/run.py`: added `_is_loopback_host` + `_guard_loopback_bind`. CHOSE REFUSE-STARTUP (exit code 2 with
  a clear message) when `single_user_trusted_mode` is on AND the bind host is non-loopback. Guard runs in
  the `serve` branch AND the default `all`/supervisor branch (which spawns `app.run serve --host`), so it
  fires before any off-box bind.
- `docs/context/decisions.md`: recorded the policy, the trust flag, the refuse-startup guard, and the
  self-asserted-field residual threat model (2026-08-17 entry).
- `tests/test_source_forget_authorization.py`: new E2E permission-matrix + parity + MCP-client-threading +
  loopback-guard suite (see Evidence).

Deviations from the plan (noted, not scope expansion):
- Config flag NAMED `single_user_trusted_mode` (default True) per the manager's directive, instead of the
  plan's `require_scoped_identity` (default False). Same semantics, inverted polarity; the chosen name
  reads as "compatibility", not "auth optional".
- `storage/base.py` was listed in Target, but `StorageProvider` (ABC) does NOT declare
  `forget_source_item`/`forget_source_scope` (they exist only on the SQLite impl; `soft_delete_memory` is
  the same). No abstract signature to update, so `storage/base.py` was left untouched. Reduction, not
  expansion.

## Evidence

Sanctioned Python invocation (SAP-IT ASR blocks Scripts\python.exe stubs):
`PYTHONPATH=".local/test-env/site-packages;." "C:/Users/I347041/AppData/Roaming/uv/python/cpython-3.13-windows-x86_64-none/python.exe" -m pytest …`

- `pytest tests/test_source_forget_authorization.py -x -q` → **26 passed** (permission matrix: owner/
  different-workspace/no-identity/untagged for both trusted & strict; single==bulk parity; denied-writes-
  nothing + audit-distinct; idempotent + nonexistent-404 + search/expansion exclusion; MCP client threads
  caller scope on both paths & omits when ctx has none; loopback guard refuse/allow/strict).
- `pytest tests/test_raw_turn_forgetting.py -x -q` → **11 passed** (existing suite incl. the no-identity
  happy-path formerly at :221 — still green under the compatibility default, unchanged).
- `pytest tests/test_raw_turn_forgetting.py tests/test_source_forget_authorization.py
  tests/test_retrieval_forget_revalidation.py tests/test_source_context.py tests/test_source_only_search.py
  tests/test_historical_lookup_funnel_e2e.py -q` → **61 passed**.
- `pytest tests/test_mcp_client.py -q` → 1 skipped (skips because the MCP server import needs `pywintypes`,
  absent in the test env — pre-existing environment limitation, not this change).
- `pytest tests/test_config.py -q` → 29 passed, **1 failed**: `test_prompt_variants_legacy_fallback_unaffected`.
  Confirmed PRE-EXISTING via `git stash` (fails identically without this change): the test doesn't override
  `PALLIUM_CONFIG_FILE`, so the developer's local `pallium.local.toml` (which sets `prompt_variants`) leaks
  into `AppConfig.from_env`. Unrelated to this task and out of scope.
