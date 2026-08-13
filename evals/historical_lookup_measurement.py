"""Historical-lookup reuse rollup — P0 measurement skeleton.

Spec: docs/specs/2026-08-13-historical-lookup-measurement-contract.md
      §§ Reuse ladder, Rollup formula, Definitions

Measures (per docs/context/lessons.md Invariant 2 — every eval states what
it measures): all three rungs are downstream-task-effect (whether retrieved
history was used downstream — not candidate-recovery, not injection-precision),
distinguished by claim strength:
  rung-1 (incorporation)   — downstream-task-effect, observational
  rung-2 (influence)       — downstream-task-effect, observational
  rung-3 (downstream)      — downstream-task-effect, controlled

P0 scope: the pure rollup function is fully testable on synthetic inputs.
P1 scope: load_events_from_storage will be populated once the dedicated
          historical-lookup path and its event/exposure tables exist.

Run (dry, no DB needed):
    python -m evals.historical_lookup_measurement --dry-run

Run against a live DB (P1 — will emit empty results today):
    python -m evals.historical_lookup_measurement --db pallium.db
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# ---------------------------------------------------------------------------
# Rung definitions — three distinct rungs, never blurred
# ---------------------------------------------------------------------------

#: Three reuse rungs per the measurement contract. Per docs/context/lessons.md,
#: every eval number states which of {candidate-recovery, injection-precision,
#: downstream-task-effect} it measures. All three rungs are in the
#: DOWNSTREAM-TASK-EFFECT family (they measure whether retrieved history was used
#: downstream — not retrieval recall, not proactive-injection precision). They are
#: distinguished by `claim`: rung-1/2 are observational proxies; rung-3 is the
#: controlled/confirmed form.
RUNGS: dict[str, dict[str, str]] = {
    "incorporation": {
        "label": "rung-1: verified incorporation",
        "measures": "downstream-task-effect",
        "claim": "observational",
        "description": (
            "Retrieved history appears in the agent's reasoning, an action, "
            "or the answer. Observational — does not imply necessity."
        ),
    },
    "influence": {
        "label": "rung-2: judged influence/necessity",
        "measures": "downstream-task-effect",
        "claim": "observational",
        "description": (
            "A retrospective judge assesses whether the retrieved history "
            "shaped the work. Observational, stronger than rung-1."
        ),
    },
    "downstream": {
        "label": "rung-3: downstream benefit",
        "measures": "downstream-task-effect",
        "claim": "controlled",
        "description": (
            "Requires controlled exposure, user confirmation, or outcome "
            "comparison — not claimable from passive logs alone."
        ),
    },
}

_VALID_RUNGS = frozenset(RUNGS)


# ---------------------------------------------------------------------------
# Wilson score interval (no external dependencies)
# ---------------------------------------------------------------------------


def _wilson_95(numerator: int, denominator: int) -> tuple[float, float]:
    """Wilson score 95% confidence interval.

    Returns (low, high) as proportions in [0.0, 1.0].

    Raises ValueError when denominator == 0 — callers must guard with
    the empty-data-safe path in compute_reuse_rollup.

    Formula (z = 1.96):
        center = (p̂ + z²/2n) / (1 + z²/n)
        margin = z · √(p̂(1-p̂)/n + z²/4n²) / (1 + z²/n)
        [low, high] = [center − margin, center + margin], clamped to [0, 1]
    """
    if denominator == 0:
        raise ValueError("denominator must be > 0; guard with empty-data check first")
    z = 1.96
    z2 = z * z
    p = numerator / denominator
    n = denominator
    denom = 1.0 + z2 / n
    center = (p + z2 / (2.0 * n)) / denom
    margin = (z * math.sqrt(p * (1.0 - p) / n + z2 / (4.0 * n * n))) / denom
    return max(0.0, center - margin), min(1.0, center + margin)


# ---------------------------------------------------------------------------
# Pure rollup — no I/O, fully unit-testable
# ---------------------------------------------------------------------------


def compute_reuse_rollup(
    eligible_sessions: list[str],
    reuse_events: list[dict[str, Any]],
    *,
    eligibility_n: int,
    window: dict[str, Any],
) -> dict[str, Any]:
    """Compute the three-rung reuse rollup from in-memory inputs.

    Parameters
    ----------
    eligible_sessions:
        List of session ids (thread_ref strings) that pass the eligibility
        filter: substantive sessions whose container held >= eligibility_n
        prior indexed source turns at the time the session ran.
        This is the **denominator** for every rung.
    reuse_events:
        List of event dicts.  Each must have at least:
          - ``session_id`` (str) — the thread_ref of the session
          - ``rung`` (str) — one of "incorporation", "influence", "downstream"
        Extra keys are ignored.  A session with multiple events at the same
        rung is counted **once** in that rung's numerator (dedup by session).
    eligibility_n:
        The N-prior-turns threshold used to build eligible_sessions; carried
        into the output for transparency.
    window:
        Arbitrary dict describing the measurement window (e.g.
        ``{"since": "...", "until": "..."}``) — serialised into the output.

    Returns
    -------
    dict
        JSON-serialisable rollup.  Per rung: numerator, denominator,
        ``reuse_per_100_eligible`` (null when denominator == 0), Wilson 95%
        interval (low/high, null when denominator == 0), label, and measures
        annotation.  Top level carries eligibility_n, window, and counts.

    Empty-data-safe
    ---------------
    When ``denominator == 0``, ``reuse_per_100_eligible`` and the Wilson
    interval are set to ``null`` with ``note: "n/a (0 eligible)"``.  No
    ZeroDivisionError is raised.
    """
    eligible_set = set(eligible_sessions)
    denominator = len(eligible_set)

    # Deduplicated per-rung session sets
    rung_sessions: dict[str, set[str]] = {r: set() for r in RUNGS}
    for event in reuse_events:
        sid = event.get("session_id", "")
        rung = event.get("rung", "")
        if sid in eligible_set and rung in _VALID_RUNGS:
            rung_sessions[rung].add(sid)

    rungs_out: dict[str, Any] = {}
    for rung_key, meta in RUNGS.items():
        numerator = len(rung_sessions[rung_key])
        entry: dict[str, Any] = {
            "label": meta["label"],
            "measures": meta["measures"],
            "claim": meta["claim"],
            "numerator": numerator,
            "denominator": denominator,
        }
        if denominator == 0:
            entry["reuse_per_100_eligible"] = None
            entry["wilson_95"] = {"low": None, "high": None}
            entry["note"] = "n/a (0 eligible)"
        else:
            low_frac, high_frac = _wilson_95(numerator, denominator)
            entry["reuse_per_100_eligible"] = 100.0 * numerator / denominator
            entry["wilson_95"] = {
                "low": 100.0 * low_frac,
                "high": 100.0 * high_frac,
            }
        rungs_out[rung_key] = entry

    return {
        "spec": "docs/specs/2026-08-13-historical-lookup-measurement-contract.md",
        "eligibility_n": eligibility_n,
        "window": window,
        "n_eligible_sessions": denominator,
        "n_reuse_events": len(reuse_events),
        "rungs": rungs_out,
    }


# ---------------------------------------------------------------------------
# P1 seam — storage loader stub
# ---------------------------------------------------------------------------


def load_events_from_storage(
    db_path: Path | str | None = None,
    *,
    container_ref: str | None = None,
    since: str | None = None,
    until: str | None = None,
    eligibility_n: int = 50,
) -> tuple[list[str], list[dict[str, Any]]]:
    """Load eligible sessions and reuse events from the Pallium DB.

    P1 SEAM — returns empty lists today.

    Once the Phase 1 vertical slice ships, this function will:

    1. Query ``source_items`` (grouped by ``thread_ref`` within
       ``container_ref``) to reconstruct eligible sessions: substantive
       sessions (>=1 user turn + >=1 assistant work turn) whose
       ``container_ref`` held >= ``eligibility_n`` prior indexed source turns
       at the time the session started.  Computed via a
       ``(container_ref, created_at)`` join — the same eval-time
       reconstruction pattern used by the subtask_selector_shadow table.

    2. Query the ``historical_lookup_reuse_event`` table (to be created in
       P1) for events with ``session_id IN <eligible_set>``.  Each row will
       carry at minimum ``session_id`` (thread_ref) and ``rung`` in
       {"incorporation", "influence", "downstream"}.

    Unconditional logging requirement (P1): the dedicated historical-lookup
    path must persist its lookup event unconditionally — NOT gated on the
    legacy ``audit_log_enabled`` flag — so this loader finds events on fresh
    DBs.  See the measurement contract for the full P1 event schema.

    Returns
    -------
    tuple[list[str], list[dict]]
        (eligible_session_ids, reuse_events) — both empty in P0.
    """
    # P0: no tables to query yet; return empty so the module runs end-to-end.
    return [], []


# ---------------------------------------------------------------------------
# CLI (dry-run or live)
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Historical-lookup reuse rollup. "
            "Pass --dry-run for a synthetic demo without a DB."
        )
    )
    parser.add_argument("--db", type=Path, default=None, help="Path to pallium.db")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run on tiny synthetic data (no DB required).",
    )
    parser.add_argument("--container-ref", default=None)
    parser.add_argument("--since", default=None)
    parser.add_argument("--until", default=None)
    parser.add_argument("--eligibility-n", type=int, default=50)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    if args.dry_run:
        sessions = [f"session-{i}" for i in range(5)]
        events = [
            {"session_id": "session-0", "rung": "incorporation"},
            {"session_id": "session-1", "rung": "incorporation"},
            {"session_id": "session-1", "rung": "influence"},
        ]
        window: dict[str, Any] = {"note": "dry-run synthetic data"}
    else:
        sessions, events = load_events_from_storage(
            args.db,
            container_ref=args.container_ref,
            since=args.since,
            until=args.until,
            eligibility_n=args.eligibility_n,
        )
        window = {
            "since": args.since,
            "until": args.until,
            "container_ref": args.container_ref,
        }

    report = compute_reuse_rollup(
        sessions,
        events,
        eligibility_n=args.eligibility_n,
        window=window,
    )

    serialised = json.dumps(report, indent=2, sort_keys=True, default=str)

    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialised)
        print(f"Wrote report -> {args.output}", file=sys.stderr)

    if args.quiet:
        sys.stdout.write(serialised + "\n")
    else:
        print("=== Historical-Lookup Reuse Rollup ===")
        print(f"eligibility_n={report['eligibility_n']}  "
              f"n_eligible={report['n_eligible_sessions']}  "
              f"n_events={report['n_reuse_events']}")
        for rung_key, rung in report["rungs"].items():
            rate = rung["reuse_per_100_eligible"]
            rate_str = f"{rate:.1f}" if rate is not None else "n/a"
            wi = rung["wilson_95"]
            if wi["low"] is not None:
                ci_str = f"[{wi['low']:.1f}, {wi['high']:.1f}]"
            else:
                ci_str = rung.get("note", "n/a")
            print(
                f"  {rung['label']:<38} "
                f"measures={rung['measures']:<22}  "
                f"n={rung['numerator']}/{rung['denominator']}  "
                f"per-100={rate_str}  95%CI={ci_str}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
