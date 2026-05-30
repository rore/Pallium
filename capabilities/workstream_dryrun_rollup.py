"""Daily roll-up for workstream dry-run metrics (Phase 4A, design 014).

Reads the metrics store for the last 24h of
``consolidation.workstream_aware_dryrun`` and
``consolidation.workstream_homogeneity`` events, aggregates by
``(kind, strategy, container_ref)``, and writes a summary JSON to
``.local/observability/workstream_dryrun/<YYYY-MM-DD>.json``.

Run as:

    python -m capabilities.workstream_dryrun_rollup

or import :func:`write_daily_rollup` and call it from a scheduled
maintenance task.
"""
from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from storage.metrics import MetricsStore


_logger = logging.getLogger(__name__)


def write_daily_rollup(
    metrics_store: MetricsStore,
    *,
    output_dir: Path | str = ".local/observability/workstream_dryrun",
    now: datetime | None = None,
) -> Path:
    """Aggregate the last 24h of workstream dry-run metrics into a JSON file."""
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(hours=24)

    rows = list(
        metrics_store.query(
            category="consolidation",
            event_type="workstream_aware_dryrun",
            since=since,
            until=now,
            limit=100000,
        )
    )
    rows.extend(
        metrics_store.query(
            category="consolidation",
            event_type="workstream_homogeneity",
            since=since,
            until=now,
            limit=100000,
        )
    )

    aggregates: dict[str, dict[tuple[str, str, str], int]] = {
        "workstream_aware_dryrun": defaultdict(int),
        "workstream_homogeneity": defaultdict(int),
    }
    for row in rows:
        payload = row.payload or {}
        kind = str(payload.get("kind") or "unknown")
        strategy = str(payload.get("strategy") or "unknown")
        container_ref = str(row.container_ref or payload.get("container_ref") or "")
        aggregates[row.event_type][(kind, strategy, container_ref)] += 1

    summary = {
        "generated_at": now.isoformat(),
        "window_start": since.isoformat(),
        "window_end": now.isoformat(),
        "events": {
            event_type: [
                {
                    "kind": kind,
                    "strategy": strategy,
                    "container_ref": container_ref,
                    "count": count,
                }
                for (kind, strategy, container_ref), count in sorted(buckets.items())
            ]
            for event_type, buckets in aggregates.items()
        },
    }

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{now.strftime('%Y-%m-%d')}.json"
    output_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    return output_path


def main() -> None:
    """CLI entry: build a metrics store from the default DB and write rollup."""
    import argparse
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    parser = argparse.ArgumentParser(description="Workstream dry-run metric daily rollup")
    parser.add_argument("--db", default="sqlite:///./pallium.db", help="SQLite URL")
    parser.add_argument("--output", default=".local/observability/workstream_dryrun")
    args = parser.parse_args()

    engine = create_engine(args.db, future=True)
    session_factory = sessionmaker(engine, expire_on_commit=False)
    store = MetricsStore(session_factory)
    path = write_daily_rollup(store, output_dir=args.output)
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
