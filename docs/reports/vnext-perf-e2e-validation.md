# vNext performance + end-to-end validation report

Validation of the cumulative vNext work (raw-history governance + measurement
contract, the historical-lookup vertical — `source_only` search,
`pallium_search_history`, source-context expansion — the reuse-funnel
population, and the dashboard rework) for **no performance regression** and
**end-to-end correctness**. This is a *measure-and-flag* report: it establishes
deterministic query-count baselines, times the hot paths, flags N+1 shapes, and
proves the vertical correct end to end incl. the live production service. It does
**not** change product behavior; any fix implied by a finding below is a separate
change with its own Work Record.

Re-run commands are at the bottom. All harnesses are read-only against product
code (timing/counting via external SQLAlchemy + `sqlite3` trace seams).

## 1. Performance — deterministic query counts (the gated signal)

Query/round-trip **counts** are the enforced regression signal (deterministic,
machine-independent, committed to `evals/vnext_perf_baseline.json`). Wall-clock
latency is **advisory only** — never gated, because absolute latency is
machine-dependent.

Per-path DB round-trips (corpus: 900 source items × 2 containers × 3 threads):

| Hot path | Engine queries | Note |
|---|---|---|
| `source_only` query (retrieval_limit 20) | 182 | dominated by per-candidate source fetches (see N+1 #1) |
| `source_only` query, no match | 2 | isolates the funnel event-write cost (FTS probe + 1 insert) |
| source-context expansion | 4 | anchor get + 2 bounded neighbor selects + expansion event write — **O(1)** in thread size |

Advisory latency (informational, this box only): `source_only` query median
~46 ms / p95 ~48 ms; source-context expansion median ~3.8 ms / p95 ~4.3 ms.

**No count regression** vs the committed baseline (`vnext_perf_harness` compare
mode exits 0).

## 2. DB performance — indexes + N+1 findings (report-only)

Index check (`EXPLAIN QUERY PLAN`):

- Neighbor-window query (`list_source_item_neighbors`) → **USING COVERING INDEX
  `idx_source_items_thread_lookup`**. Good; expansion is bounded and index-served.
- Loader per-exposed-id lookup → PK index on `source_items.id`. Good per-row.
- Loader consensus-rung → `idx_historical_lookup_label_event`. Good.

Two N+1 shapes measured (linear growth confirmed, report-only — **not fixed here**):

- **N+1 #1 — per-candidate source fetch in the retrieval path.** The lexical path
  fetches the same source item up to three times per hit (`matches_filters`
  gate + visibility/container check + hydration), and the FTS candidate window is
  ~4× the requested limit. Measured slope ≈ **9 engine queries per retrieval-limit
  slot** (`SELECT ... FROM source_items WHERE id=?`), i.e. O(candidates), not O(1).
  This is the shared retrieval chokepoint the vNext forgotten-source gate sits on.
- **N+1 #2 — loader per-exposed-id visibility scan.** The measurement loader issues
  one `source_items` query per exposed id per event; slope ≈ **1 query per exposed
  id**, O(exposed ids). Runs offline in the measurement/rollup path (not the request
  path).

**Flagged, report-only:** `_load_reuse_events`'s `WHERE event_type='lookup'` does a
**full table scan** of the reuse-event table — the existing composite index leads
with `container_ref`, so it can't serve an `event_type`-only predicate. Cheap while
the table is small; a candidate index if the funnel runs at volume. Each of the
above is a separate-WR fix decision, per the feature's measure-not-fix boundary.

## 3. End-to-end correctness (committed)

`tests/test_historical_lookup_funnel_e2e.py` (in the default CI gate, ~3 s) covers
the full vertical through the real TestClient with a visibility-enforcing package:
ingest → `POST /query` (source_only, agent-pull) → persisted `lookup` event →
`GET /source/{id}/context` (chained `parent_lookup_id`) → persisted `expansion`
event → measurement loader → non-empty rollup KPI. Invariants asserted:

- **Chain depth > 2 (persistence):** a genuine 3-hop chain built by reading the
  first expansion row's own id **from storage** and feeding it as the next
  `parent_lookup_id` (the HTTP surface only echoes the *input* id, so the storage
  read is required). Guards that the write accepts a chained parent id; labelled
  persistence-only (there is no chain-walking consumer today).
- **`/status.events_recorded` increments** by exactly the number of persisted
  events across the chain.
- **Redaction:** the returned source-hit surface is redacted (secret absent,
  `[REDACTED]` present) and the persisted exposed set equals the post-redaction
  result set by id (no leaked/extra id). *Limitation:* the exposed set stores ids
  only (never content), so content-redaction is asserted on the returned surface,
  not inside the stored set.
- **Adversarial 0-leak:** cross-container non-leak and forgotten-source exclusion
  (pre-existing, retained).

## 4. Live production-service validation (port 19836)

`scripts/live_funnel_smoke.py` validates the **installed, running** service after a
deploy/restart, **without polluting the real KPI**:

1. `GET /status` against `:19836` is **read-only** — asserts the funnel is armed.
2. The write chain runs against a **`VACUUM INTO` snapshot** of the live DB on a
   **short-lived scratch server** (own DB copy, vector disabled, scratch port) — so
   the search→expand→persist chain and the `events_recorded` increment are observed
   on the copy, never on the real DB.

Latest run (2026-08-14) against the live service: **OVERALL PASS** — real service
armed with `events_recorded=0` observed *after* the run (proving the smoke never
incremented the real count), while the copy went 0→2 (1 lookup + 1 expansion, the
expansion linking the lookup), 5 source hits recovered.

**Honest scope:** the scratch server runs **repo code**, so the write-chain portion
is functionally equivalent to the in-process e2e — it does **not** exercise the
*installed binary's* write path. The only signal that touches the installed service
is the read-only `/status` armed check. This smoke confirms (a) the installed
service is up + armed and (b) the chain works on production-shaped data; it is not a
write-path verification of the deployed binary.

## Re-run commands

Real interpreter + PYTHONPATH are required on the dev box (venv python stubs are
blocked); on CI/other machines use the environment's Python.

```bash
# E2E vertical (in the default gate; fast)
python -m pytest tests/test_historical_lookup_funnel_e2e.py -q

# Perf + DB-count harness: measure and compare vs the committed count baseline
python -m evals.vnext_perf_harness                 # compare (exit 2 on count regression)
python -m evals.vnext_perf_harness --baseline      # regenerate the committed baseline
python -m evals.vnext_perf_harness --vector        # opt-in vector path (slow; skips if ONNX absent)

# Harness + live-smoke guard tests (slow-marked: eval-harness / server spin-up)
python -m pytest tests/test_vnext_perf_harness.py tests/test_live_funnel_smoke_selftest.py -m slow -q

# Live production-service smoke (after a deploy/restart) — reads :19836, writes only a copy
python scripts/live_funnel_smoke.py \
  --container-ref "<a container that has data in the live DB>" \
  --query-text   "<text likely to match prior turns in that container>"
```
