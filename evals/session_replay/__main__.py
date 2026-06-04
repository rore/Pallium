"""CLI entry: ``python -m evals.session_replay``."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from evals.session_replay.runner import RunnerConfig, run


_ALL_SIGNALS = ("recall_intent", "repeated_work", "future_oracle")


def _expand_inputs(args: argparse.Namespace) -> list[str]:
    """Resolve positional ``paths`` plus ``--dir`` glob into a flat list."""
    out: list[str] = []
    for p in args.paths or []:
        path = Path(p)
        if path.is_file():
            out.append(str(path))
        elif path.is_dir():
            out.extend(str(q) for q in sorted(path.rglob("*.jsonl")))
        else:
            print(f"warning: {p} not found, skipping", file=sys.stderr)
    if args.dir:
        for d in args.dir:
            base = Path(d)
            if not base.is_dir():
                print(f"warning: --dir {d} is not a directory, skipping",
                      file=sys.stderr)
                continue
            out.extend(str(q) for q in sorted(base.rglob("*.jsonl")))
    # Deduplicate while keeping order
    seen: set[str] = set()
    deduped: list[str] = []
    for p in out:
        if p in seen:
            continue
        seen.add(p)
        deduped.append(p)
    return deduped


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="python -m evals.session_replay",
        description=(
            "Mine miss-signal cases from real Claude Code or Codex session "
            "JSONL transcripts and join them to the Pallium query_audit_log."
        ),
    )
    p.add_argument(
        "paths",
        nargs="*",
        help="One or more transcript JSONL files (or directories — non-recursive on directories given here, recursive on --dir).",
    )
    p.add_argument(
        "--dir",
        action="append",
        help="Directory to scan recursively for *.jsonl. Repeatable.",
    )
    p.add_argument(
        "--out",
        default="evals/session_replay/output",
        help="Output directory (default: evals/session_replay/output).",
    )
    p.add_argument(
        "--db",
        default=None,
        help="Override Pallium DB path (default: $PALLIUM_DB_PATH or ~/.pallium/data/pallium.db).",
    )
    p.add_argument(
        "--container-ref",
        default=None,
        help="Restrict audit-row matching to this container_ref.",
    )
    p.add_argument(
        "--signal",
        action="append",
        choices=list(_ALL_SIGNALS),
        help="Enable only these signals (repeatable). Default: all.",
    )
    args = p.parse_args(argv)

    paths = _expand_inputs(args)
    if not paths:
        p.error("no transcript files found in arguments")

    enabled = tuple(args.signal) if args.signal else _ALL_SIGNALS
    cfg = RunnerConfig(
        out_dir=Path(args.out),
        db_path=args.db,
        container_ref=args.container_ref,
        enable_signals=enabled,
    )
    result = run(paths, cfg)
    print(f"Scanned {result['n_sessions']} session(s) -> {result['n_rows']} row(s)")
    print(f"DB: {result['db_path']} ({'used' if result['db_used'] else 'unavailable'})")
    print(f"Wrote: {result['miss_cases_path']}")
    print(f"Wrote: {result['summary_path']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
