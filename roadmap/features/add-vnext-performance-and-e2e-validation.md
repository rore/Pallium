---
id: add-vnext-performance-and-e2e-validation
title: Performance validation + end-to-end validation of the vNext work
status: done
priority: high
commitment: committed
milestone: pallium-vnext-p1
---

## Summary

Confirm the vNext work (P0 raw-history governance + measurement contract, the P1
historical-lookup vertical — source-only search, `pallium_search_history`,
source-context expansion — the reuse-funnel population, and the dashboard rework) did
**not regress performance** (code paths + DB) and that the full historical-lookup +
measurement flow is correct **end to end**. Establish latency/DB baselines on the
paths vNext actually touched, flag any regression with evidence, and add committed
e2e coverage for the vertical so future changes can't silently break or slow it.

## Why

vNext added work on hot, shared paths — most notably the P0 **forgotten-source gate
in `matches_filters`** (the shared retrieval chokepoint, which now fetches the source
item per candidate before the `filters is None` early return), the `source_only`
retrieval path, source-context neighbor windows, and (in the reuse-funnel feature) an
unconditional per-lookup event write. The repo does **not** currently treat latency or
DB timing as formal benchmark metrics (`docs/context/validation.md`), so a regression
here would be invisible. Correctness of the vertical is covered piecewise by unit
tests, but there is no committed **end-to-end** assertion of the whole
ingest → agent-pull lookup → expand → event-persisted → KPI flow with the
visibility/redaction/forgotten invariants held throughout (only a throwaway script
was used during P1). This feature closes both gaps and is the package's final gate.

## In Scope

1. **Perf benchmark over vNext-touched paths.** A bounded, deterministic-as-possible
   local harness that times the specific hot paths vNext changed: query (lexical +
   vector fusion), ingest/processing, `source_only` search, source-context expansion,
   the `matches_filters` forgotten-source gate, and the reuse-funnel event write.
   Establish a baseline (e.g. against `main` before the vNext window, or a captured
   snapshot) and report per-path latency with a regression threshold; flag + explain
   any material regression. Reuse existing harnesses where they fit
   (`app.agent_simulation`, benchmark lanes) rather than building a general perf
   framework.
2. **DB performance check.** Verify the paths vNext queries are appropriately indexed
   and within budget on a realistically-sized local DB: the `matches_filters` per-item
   source fetch, source-context neighbor windows ordered by `(created_at, id)`, the
   reuse-funnel loader's eligible-session reconstruction + event scan, and the new
   reuse-event table. Watch specifically for N+1 patterns (per-candidate fetches,
   per-neighbor fetches, per-object evidence lookups) and missing indexes.
3. **End-to-end validation suite (committed).** A runnable scenario suite exercising
   the full vertical through the real service/TestClient: ingest a thread →
   `pallium_search_history` (agent-pull, source-only) → `pallium_expand_source`
   (chained `parent_lookup_id`) → lookup/expansion events persisted → rollup produces a
   non-empty KPI — asserting correctness AND that visibility, redaction, and
   forgotten-source invariants hold end to end (incl. adversarial cross-container /
   forgotten cases → 0 leaks).
4. **Report + thresholds.** A perf/e2e report (and a documented command to re-run it)
   that states baseline, current, delta, and pass/fail per path; e2e pass/fail with the
   invariant checks. Any regression is reported honestly (not silently absorbed).
5. **Live production-service validation (the actual running service).** In addition to
   the in-process TestClient suite, validate the **installed, running** local service
   (Windows scheduled task on port 19836): confirm `/status` reports the funnel armed,
   drive a `pallium_search_history` → `pallium_expand_source` chain against the live
   service, and confirm a lookup + expansion event actually persist and
   `events_recorded` increments — end to end on the real service, not just an in-process
   client. Use a **scratch / clearly-tagged container** (or a disposable DB copy) so the
   smoke does NOT pollute the real measurement DB / KPI. Document how to run it after a
   deploy/restart — this is the check that confirms a restart actually deployed the new
   behavior live.

## Out of Scope

- Micro-optimization for its own sake, formal SLOs, provider-cost budgeting, or
  distributed/at-scale load testing (this is local, single-user validation).
- Building a general-purpose performance-benchmark framework beyond the vNext paths.
- Changing product behavior. If a regression needs a code/DB fix (e.g. adding an
  index, memoizing a per-candidate fetch), that fix is a **separate** change with its
  own Work Record/risk (this feature measures and flags; small obvious index fixes may
  be folded in with justification).

## Done When

1. A perf report over the vNext-touched paths shows no material regression vs the
   baseline, or flags each regression with a cause and a recommended fix.
2. The hot-path DB queries are confirmed indexed and within budget on a realistic
   local DB; any N+1 or missing index is identified.
3. The committed e2e suite covering the historical-lookup + measurement vertical
   passes, including the visibility/redaction/forgotten invariant assertions
   (0 leaks under adversarial cases).
4. A documented command re-runs the perf + e2e validation, and the report is
   reproducible.
5. The live production service (port 19836) is validated end to end after a
   deploy/restart: `/status` shows the funnel armed and a search→expand chain persists
   events (verified WITHOUT polluting the real KPI — scratch container or disposable DB
   copy), with a documented re-run command.

## Notes

Runs **last** in the package — it validates the cumulative result of the reuse-funnel
+ dashboard features (and the already-merged P0/P1 vertical + Continuous evals). Feeds
confidence for turning the funnel on for a live measurement window.

**Risk: mostly blue → likely Elevated.** The harness + e2e + report live in
`evals/`/`tests/` (blue). Reading DB timings is read-only. If a regression fix is
warranted it may touch `storage/` (an index → persistence/guarded) or a hot path —
classified at that point; per the plan, fixes are separated from measurement. No RED
contract surface for the validation itself.
