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
P1 scope: load_events_from_storage reconstructs eligible sessions and loads
          persisted historical-lookup reuse events (with a consensus rung from
          the append-only labels table). Rungs populate once the retrospective
          judge has written labels (a PR-b outcome); the loader is empty-safe
          until then.

Run (dry, no DB needed):
    python -m evals.historical_lookup_measurement --dry-run

Run against a live DB (P1 — will emit empty results today):
    python -m evals.historical_lookup_measurement --db pallium.db
"""

from __future__ import annotations

import argparse
import bisect
import json
import math
import sqlite3
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
    visibility_report: dict[str, Any] | None = None,
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
    visibility_report:
        Optional governance report from ``load_visibility_violations`` — the
        attempted-disallowed-access counts by type over the persisted exposed
        sets. Embedded verbatim under ``visibility_violations`` when provided;
        an empty-safe zeroed report is embedded otherwise so the field is
        always present and never hardcoded at the call site.

    Returns
    -------
    dict
        JSON-serialisable rollup.  Per rung: numerator, denominator,
        ``reuse_per_100_eligible`` (null when denominator == 0), Wilson 95%
        interval (low/high, null when denominator == 0), label, and measures
        annotation.  Top level carries eligibility_n, window, counts, and the
        ``visibility_violations`` governance report.

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
        "visibility_violations": visibility_report
        if visibility_report is not None
        else _empty_visibility_report(),
    }


# ---------------------------------------------------------------------------
# Storage loader
# ---------------------------------------------------------------------------

#: Assistant "work" turns for the substantive-session predicate. A raw
#: assistant message alone does not make a session substantive; a work
#: artifact does.
_ASSISTANT_WORK_ARTIFACT_KINDS = frozenset(
    {"assistant_output", "tool_use_summary", "todo_snapshot"}
)

#: Reuse ladder in ascending strength. Used for the consensus tie-break.
_RUNG_LADDER = ("incorporation", "influence", "downstream")


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone()
    return row is not None


def _count_strictly_before(sorted_values: list[str], pivot: str) -> int:
    """Count entries in ``sorted_values`` strictly less than ``pivot``."""
    return bisect.bisect_left(sorted_values, pivot)


def _normalize_ts_bound(value: str | None) -> str | None:
    """Normalize a CLI ``--since`` / ``--until`` bound so lexicographic
    comparison against the stored ``created_at`` text is chronological.

    SQLite stores a SQLAlchemy ``DateTime`` with a space separator
    (``2026-08-01 00:00:01.000000``). An ISO-8601 bound with a ``T`` separator
    would compare wrong (``' '`` sorts before ``'T'``), silently dropping a
    whole day from the denominator. We swap a single leading date/time ``T``
    for a space; other text is left unchanged.
    """
    if value is None:
        return None
    # Only the date<->time separator (position 10) matters for the comparison.
    if len(value) > 10 and value[10] == "T":
        return value[:10] + " " + value[11:]
    return value


def _reconstruct_eligible_sessions(
    conn: sqlite3.Connection,
    *,
    container_ref: str | None,
    since: str | None,
    until: str | None,
    eligibility_n: int,
) -> list[str]:
    """Reconstruct eligible session ids from ``source_items`` (pinned predicate).

    PINNED eligibility predicate (against the real nullable columns):
      - user turn        = ``role = 'user'``
      - assistant-work   = ``role = 'assistant' AND artifact_kind IN
                             {'assistant_output','tool_use_summary','todo_snapshot'}``
      - prior-indexed    = ``processing_completed_at IS NOT NULL``
      - NULL ``role`` / ``artifact_kind`` rows do NOT classify (fail-closed).
      - substantive      = >=1 user turn AND >=1 assistant-work turn.
      - eligible         = the container held >= ``eligibility_n`` prior-indexed
                           turns at session start, via a ``(container_ref,
                           created_at)`` ordering join (turns created strictly
                           before the session's earliest turn).
    Forgotten turns (``forgotten_at IS NOT NULL``) are excluded everywhere.
    """
    where = ["forgotten_at IS NULL"]
    params: list[Any] = []
    if container_ref is not None:
        where.append("container_ref = ?")
        params.append(container_ref)
    sql = (
        "SELECT container_ref, thread_ref, role, artifact_kind, created_at, "
        "processing_completed_at FROM source_items WHERE " + " AND ".join(where)
    )
    rows = conn.execute(sql, params).fetchall()

    # Per-(container, thread) session aggregation + per-container sorted list
    # of prior-indexed turn timestamps.
    sessions: dict[tuple[Any, Any], dict[str, Any]] = {}
    prior_indexed: dict[Any, list[str]] = {}
    for r in rows:
        container = r["container_ref"]
        thread = r["thread_ref"]
        role = r["role"]
        artifact_kind = r["artifact_kind"]
        created = r["created_at"]
        completed = r["processing_completed_at"]
        if completed is not None and created is not None:
            prior_indexed.setdefault(container, []).append(created)
        if thread is None:
            continue
        key = (container, thread)
        session = sessions.setdefault(
            key, {"has_user": False, "has_work": False, "start": created}
        )
        if created is not None and (
            session["start"] is None or created < session["start"]
        ):
            session["start"] = created
        if role == "user":
            session["has_user"] = True
        elif role == "assistant" and artifact_kind in _ASSISTANT_WORK_ARTIFACT_KINDS:
            session["has_work"] = True

    for values in prior_indexed.values():
        values.sort()

    eligible: list[str] = []
    for (container, thread), session in sessions.items():
        if not (session["has_user"] and session["has_work"]):
            continue
        start = session["start"]
        if since is not None and start is not None and start < since:
            continue
        if until is not None and start is not None and start > until:
            continue
        values = prior_indexed.get(container, [])
        prior = _count_strictly_before(values, start) if start is not None else len(values)
        if prior >= eligibility_n:
            eligible.append(thread)
    return eligible


def _consensus_rung(conn: sqlite3.Connection, lookup_event_id: str) -> str | None:
    """Consensus rung across all rater labels for one event.

    Consensus rule (PINNED): count only labels whose rung is a valid ladder
    rung (NULL / unknown labels are ignored). Strict plurality wins; on a tie
    for the top count, drop to the most CONSERVATIVE (lowest-ladder) rung among
    the tied set. No labels -> None (the event contributes to no rung).
    """
    rows = conn.execute(
        "SELECT rung FROM historical_lookup_reuse_label WHERE lookup_event_id = ?",
        (lookup_event_id,),
    ).fetchall()
    counts: dict[str, int] = {}
    for r in rows:
        rung = r["rung"]
        if rung in _RUNG_LADDER:
            counts[rung] = counts.get(rung, 0) + 1
    if not counts:
        return None
    top = max(counts.values())
    # Iterate the ladder in ascending order so the first tied rung is the
    # most conservative.
    for rung in _RUNG_LADDER:
        if counts.get(rung, 0) == top:
            return rung
    return None


def _load_reuse_events(
    conn: sqlite3.Connection,
    *,
    eligible_set: set[str],
    container_ref: str | None,
    since: str | None,
    until: str | None,
) -> list[dict[str, Any]]:
    if not _table_exists(conn, "historical_lookup_reuse_event"):
        return []
    where = ["event_type = 'lookup'"]
    params: list[Any] = []
    if container_ref is not None:
        where.append("container_ref = ?")
        params.append(container_ref)
    if since is not None:
        where.append("created_at >= ?")
        params.append(since)
    if until is not None:
        where.append("created_at <= ?")
        params.append(until)
    sql = (
        "SELECT id, session_id FROM historical_lookup_reuse_event WHERE "
        + " AND ".join(where)
    )
    rows = conn.execute(sql, params).fetchall()

    has_labels = _table_exists(conn, "historical_lookup_reuse_label")
    events: list[dict[str, Any]] = []
    for r in rows:
        session_id = r["session_id"]
        if session_id not in eligible_set:
            continue
        rung = _consensus_rung(conn, r["id"]) if has_labels else None
        events.append(
            {"session_id": session_id, "rung": rung, "lookup_event_id": r["id"]}
        )
    return events


def load_events_from_storage(
    db_path: Path | str | None = None,
    *,
    container_ref: str | None = None,
    since: str | None = None,
    until: str | None = None,
    eligibility_n: int = 50,
) -> tuple[list[str], list[dict[str, Any]]]:
    """Load eligible sessions and reuse events from the Pallium DB.

    Reconstructs eligible sessions from ``source_items`` (see
    ``_reconstruct_eligible_sessions`` for the pinned predicate), then loads
    persisted ``historical_lookup_reuse_event`` "lookup" rows whose
    ``session_id`` is eligible, joining the append-only
    ``historical_lookup_reuse_label`` table to compute a consensus rung per
    event (``_consensus_rung``). Events with no labels carry ``rung=None`` and
    are skipped by ``compute_reuse_rollup``.

    Lookup events are persisted UNCONDITIONALLY (not gated on the legacy
    ``audit_log_enabled`` flag), so this loader finds events on fresh DBs. Live
    non-empty rungs require the retrospective judge to have written labels (a
    PR-b outcome); this loader has no build-order dependency on the judge — it
    reads a possibly-empty labels table.

    Empty-safe: returns ``([], [])`` when ``db_path`` is None, the file does
    not exist, or the required tables are absent.

    Returns
    -------
    tuple[list[str], list[dict]]
        (eligible_session_ids, reuse_events).
    """
    if db_path is None:
        return [], []
    path = Path(db_path)
    if not path.exists():
        return [], []
    since = _normalize_ts_bound(since)
    until = _normalize_ts_bound(until)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    try:
        if not _table_exists(conn, "source_items"):
            return [], []
        eligible = _reconstruct_eligible_sessions(
            conn,
            container_ref=container_ref,
            since=since,
            until=until,
            eligibility_n=eligibility_n,
        )
        events = _load_reuse_events(
            conn,
            eligible_set=set(eligible),
            container_ref=container_ref,
            since=since,
            until=until,
        )
        return eligible, events
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Visibility / governance violation reporting
# ---------------------------------------------------------------------------

#: The concrete, unambiguous scope-violation classes checked over persisted
#: exposed sets. Both are "should never happen" — the persist hooks read
#: POST-redaction / post-gate results, so the exposed ids are already filtered.
#: The count is COMPUTED (join exposed ids to source_items), never hardcoded, so
#: a regression that leaked a forbidden id would surface here as non-zero.
_VIOLATION_TYPES = ("cross_container", "forgotten_exposed")


def _empty_visibility_report() -> dict[str, Any]:
    """Zeroed governance report — used when no DB report is supplied so the
    ``visibility_violations`` field is always present and never hardcoded to a
    literal 0 at the call site."""
    return {
        "violations": 0,
        "by_type": {t: 0 for t in _VIOLATION_TYPES},
        "events_checked": 0,
        "exposed_ids_checked": 0,
        "note": "no data (empty-safe default)",
    }


def load_visibility_violations(
    db_path: Path | str | None = None,
    *,
    container_ref: str | None = None,
    since: str | None = None,
    until: str | None = None,
) -> dict[str, Any]:
    """Count attempted-disallowed-access over persisted reuse exposed sets.

    For every persisted ``historical_lookup_reuse_event`` (lookups AND
    expansions), each exposed ``source_item_id`` is joined back to
    ``source_items`` and classified:

      - ``cross_container``  — the exposed item's ``container_ref`` differs from
        the event's ``container_ref`` (a scope escape).
      - ``forgotten_exposed`` — the exposed item is forgotten
        (``forgotten_at IS NOT NULL``) yet appears in the exposed set.

    Because the persist hooks read the already-filtered results, the expected
    count is 0 — but it is COMPUTED here, not assumed, so a leak regression is
    detectable. Empty-safe: returns the zeroed report when the DB / tables are
    absent.
    """
    report = _empty_visibility_report()
    report["note"] = "computed from persisted exposed sets"
    if db_path is None:
        report["note"] = "no db (empty-safe default)"
        return report
    path = Path(db_path)
    if not path.exists():
        report["note"] = "missing db file (empty-safe default)"
        return report
    since = _normalize_ts_bound(since)
    until = _normalize_ts_bound(until)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    try:
        if not _table_exists(conn, "historical_lookup_reuse_event") or not _table_exists(
            conn, "source_items"
        ):
            return report
        where: list[str] = []
        params: list[Any] = []
        if container_ref is not None:
            where.append("container_ref = ?")
            params.append(container_ref)
        if since is not None:
            where.append("created_at >= ?")
            params.append(since)
        if until is not None:
            where.append("created_at <= ?")
            params.append(until)
        sql = "SELECT id, container_ref, exposed_json FROM historical_lookup_reuse_event"
        if where:
            sql += " WHERE " + " AND ".join(where)
        rows = conn.execute(sql, params).fetchall()

        by_type = {t: 0 for t in _VIOLATION_TYPES}
        events_checked = 0
        exposed_checked = 0
        for row in rows:
            events_checked += 1
            try:
                exposed = json.loads(row["exposed_json"] or "[]")
            except (TypeError, json.JSONDecodeError):
                exposed = []
            if not isinstance(exposed, list):
                continue
            for entry in exposed:
                if not isinstance(entry, dict):
                    continue
                sid = entry.get("source_item_id")
                if not sid:
                    continue
                exposed_checked += 1
                item = conn.execute(
                    "SELECT container_ref, forgotten_at FROM source_items WHERE id = ?",
                    (sid,),
                ).fetchone()
                if item is None:
                    continue
                if (
                    item["container_ref"] is not None
                    and row["container_ref"] is not None
                    and item["container_ref"] != row["container_ref"]
                ):
                    by_type["cross_container"] += 1
                if item["forgotten_at"] is not None:
                    by_type["forgotten_exposed"] += 1

        report["by_type"] = by_type
        report["violations"] = sum(by_type.values())
        report["events_checked"] = events_checked
        report["exposed_ids_checked"] = exposed_checked
        return report
    finally:
        conn.close()


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
        visibility_report = _empty_visibility_report()
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
        visibility_report = load_visibility_violations(
            args.db,
            container_ref=args.container_ref,
            since=args.since,
            until=args.until,
        )

    report = compute_reuse_rollup(
        sessions,
        events,
        eligibility_n=args.eligibility_n,
        window=window,
        visibility_report=visibility_report,
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
        vv = report["visibility_violations"]
        print(
            f"  visibility violations: {vv['violations']} "
            f"(by_type={vv['by_type']}; "
            f"events={vv.get('events_checked', 0)}, "
            f"exposed_ids={vv.get('exposed_ids_checked', 0)})"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
