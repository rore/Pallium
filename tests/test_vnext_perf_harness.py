"""Fast guard test for the vNext perf + DB round-trip harness.

Runs the harness in tiny/fast mode (``--small``) and asserts the structural
invariants that make it a usable measurement tool:

- both counting seams are wired (request-path engine counts + raw-sqlite3
  loader counts are populated and NON-ZERO),
- both N+1 shapes are visible (counts grow with the candidate window / with the
  number of exposed ids),
- the index check names the expected index for the neighbor-window query.

Marked slow: it builds a TestClient + seeds a small corpus (polling-free, but a
full pipeline spin-up), per docs/testing-conventions.md.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.slow

from evals.vnext_perf_harness import run_measurements


def test_harness_small_mode_reports_both_seams_and_n1s():
    report = run_measurements(small=True)

    # Request-path seam (SQLAlchemy listener) produced non-zero counts.
    counts = report["counts"]
    assert counts["source_only_query"]["engine_queries"] > 0
    # The no-match source_only path still writes exactly the funnel event
    # (+ the FTS probe) -> a small, bounded, non-zero count.
    assert 0 < counts["source_only_query_no_match"]["engine_queries"] <= 5
    # Source-context expansion is a BOUNDED window (anchor + 2 neighbor selects
    # + event write), independent of thread size.
    assert 0 < counts["source_context_expansion"]["engine_queries"] <= 8

    # Loader seam (raw sqlite3 set_trace_callback) is NON-ZERO -- proves the
    # second seam is wired (the SQLAlchemy listener would report zero here).
    loader = report["loader"]
    assert loader["load_events_loader_queries"] > 0
    assert loader["visibility_loader_queries"] > 0

    # N+1 #1: DB round-trips grow with the candidate window (not O(1)).
    n1a = report["n1_double_get_source_item"]
    assert len(n1a) >= 2
    assert n1a[-1]["engine_queries"] > n1a[0]["engine_queries"]

    # N+1 #2: loader per-exposed-id queries grow with the exposed-id count.
    n1b = report["n1_loader_per_exposed_id"]
    assert len(n1b) >= 2
    assert n1b[-1]["exposed_ids_checked"] > n1b[0]["exposed_ids_checked"]
    assert n1b[-1]["visibility_loader_queries"] > n1b[0]["visibility_loader_queries"]

    # Index check names the neighbor-window index and does not full-scan it.
    neighbor = next(c for c in report["index_check"] if c["path"].startswith("neighbor_window"))
    assert neighbor["index_used"] == "idx_source_items_thread_lookup"
    assert neighbor["full_scan"] is False
