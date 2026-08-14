"""Reuse-judge calibration runner — judge-vs-gold agreement.

Spec / ticket: roadmap/ideas/idea-reuse-judge-calibration.md
Judge:         evals/historical_lookup_judge.py

The retrospective reuse KPI rests entirely on the LLM-judge's rung-1/rung-2
verdicts. Inter-seed Cohen's kappa (already in the judge) measures the judge's
*stability*, not its *correctness*: a confidently-wrong judge can be perfectly
self-consistent. This runner closes that gap. It:

  1. Loads a small, committed, human-labelled GOLD fixture of lookups
     (``evals/fixtures/reuse_gold/gold_lookups.json``) — each record is
     before/after turns + retrieved history + the correct rung.
  2. Seeds those records into a throwaway scratch SQLite DB as
     ``historical_lookup_reuse_event`` "lookup" rows + surrounding
     ``source_items`` turns, exactly the shape the judge reads from a live DB.
  3. Runs the REAL judge (``run_judge``) over the scratch DB with
     ``gold_labels`` supplied, so the judge reports judge-vs-gold Cohen's kappa
     (consensus rung vs gold rung) alongside its usual seed-vs-seed kappa.
  4. Emits a report with the measured kappa + the ``calibrated`` verdict
     against ``GOLD_KAPPA_THRESHOLD``.

This is a thin CONSUMER of the judge — it does NOT define a second judge, and it
does NOT change the rubric, model, sampling, or consensus rule. It only measures
how well the existing judge agrees with the gold set.

HONESTY LIMITATIONS (see the fixture's ``_meta.honesty_limitations``): the gold
set is small (N=12 → wide kappa CI) and single-author synthetic (no second human
rater; hand-written scenarios that may not mirror real lookup distributions). A
below-threshold result is a valid, honest "not yet calibrated" outcome — rung
rates are then presented as uncalibrated rather than confident.

Run (dry, no LLM, no DB needed beyond a temp file):
    python -m evals.reuse_judge_calibration --dry-run

Run for real (needs a configured LLM provider):
    PALLIUM_CONFIG_FILE=pallium.local.toml PALLIUM_HAI_API_KEY=... \\
        python -m evals.reuse_judge_calibration --seeds 0,1,2 \\
        --cache-dir .local/llm-cache \\
        --output .local/research/reuse_judge_calibration.json
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import text

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from evals.historical_lookup_judge import (  # noqa: E402
    GOLD_KAPPA_THRESHOLD,
    JudgeReport,
    _NullProvider,
    run_judge,
)
from storage.sqlite import SQLiteStorageProvider  # noqa: E402

DEFAULT_FIXTURE_PATH = (
    _PROJECT_ROOT / "evals" / "fixtures" / "reuse_gold" / "gold_lookups.json"
)
DEFAULT_OUTPUT_PATH = _PROJECT_ROOT / ".local" / "research" / "reuse_judge_calibration.json"

#: Valid gold rungs. "none" is stored as a NULL rung (the judge's "none" maps to
#: the same "none" kappa category via _rung_category), so gold and judge share a
#: category space of {incorporation, influence, none}.
_GOLD_RUNGS = frozenset({"incorporation", "influence", "none"})

# Deterministic base time; each record gets its own thread so absolute times
# never collide across records — only WITHIN-thread ordering vs the pivot matters.
_HISTORY_BASE = datetime(2026, 6, 1, 0, 0, 0)
_SESSION_BASE = datetime(2026, 7, 1, 0, 0, 0)


def _ts(base: datetime, seconds: int) -> str:
    """Serialise to the same 'YYYY-MM-DD HH:MM:SS.ffffff' text the storage
    layer writes, so the judge's lexicographic pivot comparison stays
    chronological."""
    return (base + timedelta(seconds=seconds)).strftime("%Y-%m-%d %H:%M:%S.%f")


def _artifact_kind_for(role: str) -> str:
    """Map a fixture turn role to the artifact_kind the eligibility predicate
    expects: user turns are 'message'; assistant turns are 'assistant_output'
    (a work artifact, so the session counts as substantive)."""
    return "assistant_output" if role == "assistant" else "message"


def load_gold_fixture(path: Path | str = DEFAULT_FIXTURE_PATH) -> list[dict[str, Any]]:
    """Load and validate the gold fixture. Raises ValueError on a malformed or
    non-generic record so a bad fixture fails loudly rather than silently
    skewing calibration."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    lookups = data.get("lookups")
    if not isinstance(lookups, list) or not lookups:
        raise ValueError("gold fixture has no 'lookups' list")
    seen_ids: set[str] = set()
    for rec in lookups:
        rid = rec.get("id")
        if not rid or rid in seen_ids:
            raise ValueError(f"gold fixture: missing or duplicate id: {rid!r}")
        seen_ids.add(rid)
        if rec.get("gold_rung") not in _GOLD_RUNGS:
            raise ValueError(f"gold fixture {rid}: invalid gold_rung {rec.get('gold_rung')!r}")
        if not isinstance(rec.get("before_turns"), list) or not rec["before_turns"]:
            raise ValueError(f"gold fixture {rid}: before_turns must be non-empty")
        if not isinstance(rec.get("after_turns"), list) or not rec["after_turns"]:
            raise ValueError(f"gold fixture {rid}: after_turns must be non-empty")
        if not isinstance(rec.get("retrieved_history"), list):
            raise ValueError(f"gold fixture {rid}: retrieved_history must be a list")
    return lookups


def _insert_turn(
    storage: SQLiteStorageProvider,
    *,
    sid: str,
    role: str,
    content: str,
    thread: str,
    container: str,
    created: str,
) -> None:
    with storage._engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO source_items (id, source_type, source_id, content_type, "
                "content, role, artifact_kind, container_ref, thread_ref, visibility, "
                "processing_status, processing_attempts, processing_completed_at, "
                "forgotten_at, created_at) VALUES (:id,'chat_message',:sid,'text/plain',"
                ":content,:role,:ak,:c,:t,'private','completed',0,:completed,NULL,:created)"
            ),
            {
                "id": sid, "sid": sid, "content": content, "role": role,
                "ak": _artifact_kind_for(role), "c": container, "t": thread,
                "completed": created, "created": created,
            },
        )


def seed_scratch_db(gold: list[dict[str, Any]], db_path: Path | str) -> dict[str, str | None]:
    """Seed the gold lookups into a scratch DB and return an
    ``{lookup_event_id -> gold_rung_or_None}`` map for run_judge's gold_labels.

    Each record becomes: its retrieved-history turns (in a separate history
    thread), its before/after turns (in the record's own session thread), and
    one ``historical_lookup_reuse_event`` lookup row whose exposed_json points
    at the history turns. "none" gold labels are returned as None so they land
    in the judge's "none" kappa category.
    """
    storage = SQLiteStorageProvider(f"sqlite:///{db_path}")
    gold_labels: dict[str, str | None] = {}
    for rec in gold:
        rid = rec["id"]
        container = rec.get("container_ref") or "git:example.com/gold"
        hist_thread = f"t:hist:{rid}"
        sess_thread = f"t:{rid}"

        # Retrieved history turns (past excerpts the lookup surfaces).
        exposed_ids: list[str] = []
        for h, htext in enumerate(rec.get("retrieved_history") or []):
            hid = f"{rid}:hist:{h}"
            _insert_turn(
                storage, sid=hid, role="assistant", content=htext,
                thread=hist_thread, container=container,
                created=_ts(_HISTORY_BASE, h + 1),
            )
            exposed_ids.append(hid)

        # Before turns (precede the lookup pivot).
        for j, turn in enumerate(rec["before_turns"]):
            _insert_turn(
                storage, sid=f"{rid}:before:{j}", role=turn.get("role", "user"),
                content=turn.get("content", ""), thread=sess_thread,
                container=container, created=_ts(_SESSION_BASE, j + 1),
            )

        # The lookup event — its created_at is the pivot the before/after split
        # turns on (between the before turns at :01+ and after turns at :120+).
        event_id = f"ev:{rid}"
        storage.write_historical_lookup_event_row({
            "id": event_id,
            "created_at": datetime.fromisoformat(_ts(_SESSION_BASE, 60)),
            "event_type": "lookup",
            "session_id": sess_thread,
            "container_ref": container,
            "actor_ref": None,
            "trigger_origin": "agent_pull",
            "parent_lookup_id": None,
            "exposed_json": json.dumps(
                [{"source_item_id": s, "raw_rank": i + 1, "score": 0.5}
                 for i, s in enumerate(exposed_ids)]
            ),
            "visibility": "private",
        })

        # After turns (the subsequent work; created strictly after the pivot).
        for k, turn in enumerate(rec["after_turns"]):
            _insert_turn(
                storage, sid=f"{rid}:after:{k}", role=turn.get("role", "assistant"),
                content=turn.get("content", ""), thread=sess_thread,
                container=container, created=_ts(_SESSION_BASE, 120 + k + 1),
            )

        gold_rung = rec["gold_rung"]
        gold_labels[event_id] = None if gold_rung == "none" else gold_rung
    return gold_labels


def run_calibration(
    *,
    provider,
    fixture_path: Path | str = DEFAULT_FIXTURE_PATH,
    db_path: Path | str | None = None,
    seeds: list[int] | None = None,
    sample_size: int = 500,
) -> JudgeReport:
    """Load the gold fixture, seed a scratch DB, and run the real judge with
    gold_labels so the report carries judge-vs-gold agreement.

    ``db_path`` None → a fresh temp file (removed by the OS temp dir lifecycle).
    ``write_labels`` is False: this is a calibration measurement, not a labels
    write — it must never persist into any real DB.
    """
    seeds = seeds if seeds is not None else [0, 1, 2]
    gold = load_gold_fixture(fixture_path)

    owns_tmp = db_path is None
    if owns_tmp:
        tmp = tempfile.NamedTemporaryFile(prefix="reuse_gold_", suffix=".db", delete=False)
        tmp.close()
        db_path = tmp.name

    gold_labels = seed_scratch_db(gold, db_path)
    # container_ref=None → judge loads every record's container; sample_size
    # large enough to include the whole fixture; eligibility_n=0 → every
    # synthetic session is eligible.
    report = run_judge(
        db_path,
        provider=provider,
        container_ref=None,
        eligibility_n=0,
        sample_size=sample_size,
        seeds=seeds,
        write_labels=False,
        gold_labels=gold_labels,
    )
    return report


def _calibration_summary(report: JudgeReport, *, fixture_path: Path | str) -> dict[str, Any]:
    return {
        "spec": "roadmap/ideas/idea-reuse-judge-calibration.md",
        "fixture": str(fixture_path),
        "n_gold": report.gold_kappa_n,
        "seeds": report.seeds,
        "judge_vs_gold": {
            "kappa": report.gold_kappa,
            "n": report.gold_kappa_n,
            "threshold": GOLD_KAPPA_THRESHOLD,
            "calibrated": report.calibrated,
        },
        "seed_vs_seed_kappa": report.kappa,
        "n_judge_failures": report.n_judge_failures,
        "report": report.to_dict(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Reuse-judge calibration: run the existing historical-lookup reuse "
            "judge against a human-labelled gold fixture and report judge-vs-gold "
            "Cohen's kappa + a calibrated verdict against GOLD_KAPPA_THRESHOLD."
        )
    )
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE_PATH)
    parser.add_argument(
        "--seeds",
        default="0,1,2",
        help="Comma-separated rater seeds; >=3 recommended (default: 0,1,2).",
    )
    parser.add_argument("--sample-size", type=int, default=500)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Seed + run with a no-op provider (no LLM calls). Kappa is not meaningful.",
    )
    parser.add_argument("--cache-dir", type=Path, default=None)
    parser.add_argument("--no-eval-cache", action="store_true")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    args = parser.parse_args(argv)

    seeds = [int(p.strip()) for p in str(args.seeds).split(",") if p.strip()]

    if args.dry_run:
        provider = _NullProvider()
    else:
        from app.config import AppConfig
        from evals.eval_common import build_eval_providers

        config = AppConfig.from_env()
        _main_provider, provider = build_eval_providers(
            config, cache_dir=args.cache_dir, no_eval_cache=args.no_eval_cache
        )

    report = run_calibration(provider=provider, fixture_path=args.fixture, seeds=seeds)
    summary = _calibration_summary(report, fixture_path=args.fixture)

    serialised = json.dumps(summary, indent=2, sort_keys=True, default=str)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialised, encoding="utf-8")
        print(f"Wrote calibration report -> {args.output}", file=sys.stderr)
    print(serialised)

    kappa = report.gold_kappa
    verdict = (
        "CALIBRATED" if report.calibrated
        else "UNCALIBRATED" if report.calibrated is False
        else "INDETERMINATE"
    )
    print(
        f"judge-vs-gold kappa={kappa} n={report.gold_kappa_n} "
        f"threshold={GOLD_KAPPA_THRESHOLD} -> {verdict}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
