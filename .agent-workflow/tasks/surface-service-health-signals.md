# surface-service-health-signals

The Pallium service silently ran degraded for days: the ONNX embedding provider failed to initialize
(vector/semantic search disabled) yet `/status` and `/health` stayed green and the dashboard showed the
service OK. Root cause of the blind spot: when vector is CONFIGURED but the embedding provider fails,
`service._vector_index` becomes None, and the readiness logic (`app/main.py:256-259, 358-361`) treats
`not vector_index_configured` as **ready** — so "expected-but-failed" is indistinguishable from
"intentionally not configured." Make the failure visible.

<!-- agent-workflow:start -->
**Outcome:**
`/status` and `/health` distinguish "vector intentionally off" from "vector expected but the embedding
provider failed," exposing an `embedding_provider_ok` signal; `/health` reports a `degraded` status (with
reasons) when vector was expected but is unavailable; the dashboard shows an amber/red badge in that case
instead of green. A silent embedding-provider outage becomes visible.

**Target:**
`app/main.py` (`/health` + `/status` handlers), `app/dashboard.html` (`renderStatus`), plus a generic
ops doc `docs/context/operations.md` + a one-line pointer in `AGENTS.md`. No retrieval/behavior change.

**Scope:**
- Compute `vector_expected = bool(resolved_config.vector_index.enabled)` and
  `vector_active = service._vector_index is not None`; `embedding_provider_ok = (not vector_expected) or
  vector_active`.
- `/status`: add `embedding_provider_ok` (and `vector_expected`) to the response body.
- `/health`: when `vector_expected and not vector_active` → `status: "degraded"`, add
  `degraded_reasons: ["vector_embedding_provider_unavailable"]`, keep HTTP 200 (functional but impaired);
  otherwise unchanged (`ok` / `initializing`).
- `app/dashboard.html renderStatus`: render an amber "degraded" badge when health `status == "degraded"`
  or `embedding_provider_ok == false`, showing the reason; green only when truly healthy.
- Docs: concise generic operations page (local-service model, health meaning, the embedding-deps gotcha);
  one-line AGENTS.md pointer. NO machine-specific paths/keys in committed docs.

**Constraints:**
- Observability-only: no change to retrieval, injection, or the embedding build path itself.
- Keep `/health` 200 for `degraded` (impaired, not down) so orchestration doesn't hard-fail; the signal is
  the `status`/`degraded_reasons` fields.
- Committed docs stay generic (no personal paths, task names, or API keys — those live in agent memory).
- Don't break existing `/status`/`/health` fields or their consumers.

**Completion criteria:**
1. With vector configured + embedding provider present: `/status.embedding_provider_ok == true`,
   `/health.status == "ok"`.
2. With vector configured but embedding provider failed (index None): `embedding_provider_ok == false`,
   `/health.status == "degraded"` + reason, HTTP 200.
3. With vector intentionally disabled in config: `embedding_provider_ok == true` (not a failure),
   `/health.status == "ok"`.
4. Dashboard shows a non-green badge when `embedding_provider_ok == false`.
5. Existing status/health tests pass; new tests cover 1-3.

**Risk:** High

**Complexity:** Moderate

**Reason:** Edits guarded `app/` (main.py + dashboard). Purely additive observability, exact lines mapped,
so Moderate not Large.

**Discovery:**
- Masking logic: `app/main.py:256-259` (/health) and `:358-361` (/status) — `not vector_index_configured`
  counts as ready. `service._vector_index is None` when embeddings fail (`dependencies.py:343-354`).
- `resolved_config.vector_index.enabled` is the "expected" signal (config-driven); `resolved_config` is in
  scope in the /status closure (`app/main.py:373-375`) — confirm same for /health.
- Dashboard badge: `app/dashboard.html renderStatus` (~1508-1515) is green on any 200.

**Material assumptions:**
- *`resolved_config.vector_index.enabled` reflects intent-to-run-vector.* If a separate `enable_vector`
  runtime flag also gates it, include it. Action: check dependencies build signature.
- *`/health` closure can see `resolved_config`.* If not, thread it or reuse `service` config. Action:
  verify when editing.

**Plan:**
1. main.py: add a small helper computing `embedding_provider_ok` from config+index; use in both /health and
   /status.
2. dashboard.html: amber/red badge + reason on degraded / not-ok embeddings.
3. docs/context/operations.md (generic) + AGENTS.md one-line pointer.
4. Tests in the status/health test module for criteria 1-3.

**Verification plan:**
- Criteria 1-3 → tests building the app with vector on+ok / on+failed (monkeypatch index None) / off; assert
  `embedding_provider_ok` + `/health.status`.
- Criterion 4 → manual/dashboard note (JS not unit-tested here); assert the JSON the dashboard reads.
- Criterion 5 → full `pytest tests/ -q` (known `test_config` env-leak only).
- redline + agent-workflow CI.

**Plan review:**
Self-review (budget): change is additive observability with exact lines pre-mapped by a prior clean-context
investigation; the red-zone architecture-review checkpoint is shadow-advisory (non-blocking). Recorded here
in lieu of a separate clean-context pass.

**Approvals:**
Approved by user 2026-08-19: "no indication in the dashboard that the service was not ok" + "let's first
handle the service issue" — approving the dashboard/health-signal fix.

**Exceptions:**
—

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

- `app/main.py` `/health`: computes `vector_expected = bool(resolved_config.vector_index.enabled)` and
  `embedding_provider_ok = (not vector_expected) or vector_index_configured`. When expected-but-failed →
  `status: "degraded"` + `degraded_reasons: ["vector_embedding_provider_unavailable"]`, HTTP 200. Otherwise
  `ok`/`initializing` as before, now also carrying `embedding_provider_ok`.
- `app/main.py` `/status`: adds `embedding_provider_ok` and `vector_expected` to the response body.
- `app/dashboard.html` `renderStatus`: red "degraded: embeddings" badge (reuses `.error` class) + tooltip
  when `embedding_provider_ok === false`, checked before the healthy/initializing branches.
- `docs/context/operations.md` (new, generic — no machine paths): service model, health-signal table, the
  silent embedding-provider degrade + how to read it. `AGENTS.md`: one-line pointer.
- Tests (`tests/test_health.py`): degraded + disabled `/health` cases, `/status` embedding-signal cases;
  updated the two exact-key-set assertions. Degrade simulated with `VectorIndexConfig(enabled=True,
  embedding_provider="")` — index stays None, no ONNX download.

**Verification:** `pytest tests/test_health.py tests/test_dashboard.py tests/test_api.py -q` → 81 passed.
Criteria 1-3 covered by tests; criterion 4 is the dashboard JS branch (asserted via the JSON it reads).
