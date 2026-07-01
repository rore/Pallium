"""operational_fact backfill — one-shot derivation over the existing
``agent_work_trace_turn`` corpus.

Usage::

    python -m app.tools.operational_fact_backfill --dry-run
    python -m app.tools.operational_fact_backfill --commit --yes-i-ran-dry-run

Two guards protect against accidental writes:

1. ``--commit`` refuses unless a same-day dry-run marker file exists
   under ``.local/backfill-YYYYMMDD-*.json`` (or the newer path resolved
   below).
2. ``--commit`` additionally requires the ``--yes-i-ran-dry-run`` flag.
3. Feature-flag gate: ``[features] operational_fact_derivation`` must
   be True for ``--commit`` to write anything.

PR 3 ships the derivation-histogram core + CLI shape. Full corpus-scale
storage iteration (batched reads across every thread) lands in a
follow-up PR once PR 4's scenarios validate the derivation output.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from semantic.operational_fact import (
    OperationalFactCandidate,
    ScopeResolver,
    TurnRecord,
    build_default_scope_resolver,
    derive_operational_facts,
)

logger = logging.getLogger(__name__)


def summarize_candidates(
    candidates: Sequence[OperationalFactCandidate],
) -> dict[str, object]:
    """Group derived candidates into a JSON-serializable histogram.

    Shape::

        {
            "total": int,
            "by_family": {family: count, ...},
            "by_scope_kind": {scope_kind: count, ...},
            "by_role": {role: count, ...},
        }

    Used by both dry-run and commit modes to produce identical
    reporting output — the goal is that ``--commit`` writes exactly
    the count ``--dry-run`` predicted.
    """
    family = Counter(c.command_family for c in candidates)
    scope = Counter(c.scope_kind for c in candidates)
    role = Counter(c.artifact_role for c in candidates)
    return {
        "total": len(candidates),
        "by_family": dict(sorted(family.items())),
        "by_scope_kind": dict(sorted(scope.items())),
        "by_role": dict(sorted(role.items())),
    }


def run_dry_run(
    turn_streams_by_container: dict[str, Sequence[TurnRecord]],
    *,
    scope_resolver: ScopeResolver | None = None,
) -> dict[str, object]:
    """Derive candidates across every container's turn stream.

    Returns a report dict with:
        - ``schema_version``: fixed literal "operational_fact_backfill.v1"
        - ``generated_at``: UTC ISO 8601 timestamp
        - ``containers_scanned``: int
        - ``summary``: aggregate histogram (as summarize_candidates)
        - ``per_container``: mapping container_ref -> summary
    """
    resolver = scope_resolver or build_default_scope_resolver()
    all_candidates: list[OperationalFactCandidate] = []
    per_container: dict[str, dict[str, object]] = {}
    for container_ref, turns in turn_streams_by_container.items():
        cands = derive_operational_facts(
            turn_stream=turns,
            container_ref=container_ref,
            scope_resolver=resolver,
        )
        all_candidates.extend(cands)
        per_container[container_ref] = summarize_candidates(cands)
    return {
        "schema_version": "operational_fact_backfill.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "containers_scanned": len(turn_streams_by_container),
        "summary": summarize_candidates(all_candidates),
        "per_container": per_container,
    }


def write_dry_run_marker(report: dict[str, object], marker_dir: Path) -> Path:
    """Persist a dry-run marker file. Returns the path written."""
    marker_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    path = marker_dir / f"backfill-{ts}.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return path


def find_today_dry_run_marker(marker_dir: Path) -> Path | None:
    """Look for a same-day dry-run marker. Returns the path or None."""
    if not marker_dir.exists():
        return None
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    matches = sorted(marker_dir.glob(f"backfill-{today}-*.json"))
    return matches[-1] if matches else None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="operational_fact_backfill",
        description=(
            "Derive operational_fact candidates from the existing "
            "agent_work_trace_turn corpus. --dry-run reports only; "
            "--commit refuses without a same-day dry-run marker AND "
            "--yes-i-ran-dry-run."
        ),
    )
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument(
        "--dry-run",
        action="store_true",
        help="Iterate + report only. No writes to memory_objects.",
    )
    action.add_argument(
        "--commit",
        action="store_true",
        help=(
            "Write derived candidates to storage. Requires a same-day "
            "dry-run marker AND --yes-i-ran-dry-run."
        ),
    )
    parser.add_argument(
        "--yes-i-ran-dry-run",
        action="store_true",
        help=(
            "Acknowledge that --dry-run was run against the same DB "
            "already. Required for --commit."
        ),
    )
    parser.add_argument(
        "--marker-dir",
        default=".local",
        help="Directory where dry-run marker JSON files are written.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    args = build_parser().parse_args(argv)
    marker_dir = Path(args.marker_dir)

    if args.commit:
        # Guard 1: same-day marker must exist.
        marker = find_today_dry_run_marker(marker_dir)
        if marker is None:
            print(
                "refusing to commit: no same-day dry-run marker found under "
                f"{marker_dir}/backfill-YYYYMMDD-*.json. run --dry-run first.",
                file=sys.stderr,
            )
            return 2
        # Guard 2: explicit ack flag must be present.
        if not args.yes_i_ran_dry_run:
            print(
                "refusing to commit: --yes-i-ran-dry-run is required. "
                "confirm you ran --dry-run and reviewed the histogram.",
                file=sys.stderr,
            )
            return 2

    # PR 3 ships the CLI + dry-run report shape. Loading real turn
    # streams from storage is intentionally deferred: the corpus scan
    # touches the sqlite_queue path and needs its own storage-review
    # pass. Until then, the CLI runs against an explicit fixture path
    # via the PALLIUM_BACKFILL_FIXTURE env var, or reports zero.
    import os

    fixture_path = os.environ.get("PALLIUM_BACKFILL_FIXTURE")
    if fixture_path:
        turn_streams = _load_fixture(Path(fixture_path))
    else:
        # No fixture and no live-DB scan yet — dry-run reports an
        # empty corpus. Commit is refused (§Guard 1 above) unless a
        # dry-run already produced a marker, which would have been
        # empty. This is by design: PR 3's CLI is scaffolding.
        turn_streams = {}
        logger.warning(
            "No PALLIUM_BACKFILL_FIXTURE set. Reporting empty corpus. "
            "Live-DB scanning lands in a follow-up PR."
        )

    report = run_dry_run(turn_streams)
    print(json.dumps(report, indent=2))

    if args.dry_run:
        marker = write_dry_run_marker(report, marker_dir)
        print(f"\ndry-run marker written: {marker}", file=sys.stderr)
        return 0

    # --commit path
    if report["summary"]["total"] == 0:
        print("\nno candidates to commit.", file=sys.stderr)
        return 0

    # Actual persistence lands in the follow-up storage-review PR.
    print(
        "\ncommit path not yet implemented. dry-run confirmed "
        f"{report['summary']['total']} candidates would be written.",
        file=sys.stderr,
    )
    return 0


def _load_fixture(path: Path) -> dict[str, list[TurnRecord]]:
    """Load a turn-stream fixture from JSON. Test-only shape."""
    from semantic.operational_fact import CommandRecord

    data = json.loads(path.read_text(encoding="utf-8"))
    result: dict[str, list[TurnRecord]] = {}
    for container_ref, turns in data.items():
        stream: list[TurnRecord] = []
        for t in turns:
            stream.append(
                TurnRecord(
                    turn_index=t["turn_index"],
                    source_item_id=t["source_item_id"],
                    timestamp=t.get("timestamp", ""),
                    commands=tuple(
                        CommandRecord(
                            cmd=c["cmd"],
                            exit_code=c.get("exit_code"),
                            output_tail=c.get("output_tail", ""),
                            failure_class=c.get("failure_class", ""),
                        )
                        for c in t.get("commands", [])
                    ),
                    files_read=tuple(t.get("files_read", [])),
                    files_modified=tuple(t.get("files_modified", [])),
                    grep_patterns=tuple(t.get("grep_patterns", [])),
                )
            )
        result[container_ref] = stream
    return result


if __name__ == "__main__":
    raise SystemExit(main())
