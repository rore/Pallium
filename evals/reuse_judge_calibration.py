"""Reuse-judge calibration runner — judge-vs-reference agreement.

Spec / ticket: roadmap/ideas/idea-reuse-judge-calibration.md
Judge:         evals/historical_lookup_judge.py

The retrospective reuse KPI rests entirely on the LLM-judge's rung-1/rung-2
verdicts. Inter-seed Cohen's kappa (already in the judge) measures the judge's
*stability*, not its *correctness*: a confidently-wrong judge can be perfectly
self-consistent. This runner closes that gap. It:

  1. Loads a small, committed, single-author reference fixture of lookups
     (``evals/fixtures/reuse_gold/gold_lookups.json``) — each record is
     before/after turns + retrieved history + the maintained reference rung.
  2. Seeds those records into a throwaway scratch SQLite DB as
     ``historical_lookup_reuse_event`` "lookup" rows + surrounding
     ``source_items`` turns, exactly the shape the judge reads from a live DB.
  3. Runs the REAL judge (``run_judge``) over the scratch DB with
     ``gold_labels`` supplied, so the judge reports judge-vs-reference Cohen's kappa
     (consensus rung vs gold rung) alongside its usual seed-vs-seed kappa.
  4. Emits a report with the measured kappa + the ``calibrated`` verdict
     against ``GOLD_KAPPA_THRESHOLD``.

This is a thin CONSUMER of the judge — it does NOT define a second judge, and it
does NOT change the rubric, model, sampling, or consensus rule. It only measures
how well the existing judge agrees with the reference set.

HONESTY LIMITATIONS (see the fixture's ``_meta.honesty_limitations``): the gold
set is small (N=12 → wide kappa CI) and single-author synthetic (no second human
rater; hand-written scenarios that may not mirror real lookup distributions). A
below-threshold result is a valid, honest "not yet calibrated" outcome — rung
rates are then presented as uncalibrated rather than confident.

Run (dry, no LLM, no DB needed beyond a temp file):
    python -m evals.reuse_judge_calibration --dry-run

Run for real (needs a configured LLM provider):
    PALLIUM_CONFIG_FILE=pallium.local.toml PALLIUM_HAI_API_KEY=... \\
        python -m evals.reuse_judge_calibration --seed-groups "0,1,2;3,4,5" \\
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
    JUDGE_PROMPT_ID,
    JUDGE_PROMPT_VERSION,
    JudgeReport,
    _NullProvider,
    _rung_category,
    cohens_kappa,
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
    """Load and validate the reference fixture. Raises ValueError on a malformed or
    non-generic record so a bad fixture fails loudly rather than silently
    skewing calibration."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    lookups = data.get("lookups")
    if not isinstance(lookups, list) or not lookups:
        raise ValueError("reference fixture has no 'lookups' list")
    seen_ids: set[str] = set()
    for rec in lookups:
        rid = rec.get("id")
        if not rid or rid in seen_ids:
            raise ValueError(f"reference fixture: missing or duplicate id: {rid!r}")
        seen_ids.add(rid)
        if rec.get("gold_rung") not in _GOLD_RUNGS:
            raise ValueError(f"reference fixture {rid}: invalid gold_rung {rec.get('gold_rung')!r}")
        if not isinstance(rec.get("before_turns"), list) or not rec["before_turns"]:
            raise ValueError(f"reference fixture {rid}: before_turns must be non-empty")
        if not isinstance(rec.get("after_turns"), list) or not rec["after_turns"]:
            raise ValueError(f"reference fixture {rid}: after_turns must be non-empty")
        if not isinstance(rec.get("retrieved_history"), list):
            raise ValueError(f"reference fixture {rid}: retrieved_history must be a list")
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
    """Load the reference fixture, seed a scratch DB, and run the real judge with
    gold_labels so the report carries judge-vs-reference agreement.

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

    try:
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
    finally:
        # Remove the scratch DB we created; never touch a caller-supplied path.
        if owns_tmp:
            try:
                Path(db_path).unlink(missing_ok=True)
            except OSError:
                pass
    return report


def _event_status(
    report: JudgeReport, event_ids: list[str]
) -> tuple[set[str], list[str], list[str], list[str]]:
    expected = set(event_ids)
    sampled = set(report.consensus_rung)
    successful = {label.lookup_event_id for label in report.labels}
    successful_counts: dict[str, int] = {}
    for label in report.labels:
        successful_counts[label.lookup_event_id] = (
            successful_counts.get(label.lookup_event_id, 0) + 1
        )
    return (
        successful,
        [event_id for event_id in event_ids if event_id not in sampled],
        [
            event_id for event_id in event_ids
            if event_id in sampled
            and successful_counts.get(event_id, 0) < len(report.seeds)
        ],
        sorted(sampled - expected),
    )


def build_reference_validation_summary(
    group_a: JudgeReport,
    group_b: JudgeReport,
    *,
    event_ids: list[str],
    fixture_path: Path | str,
) -> dict[str, Any]:
    """Combine two disjoint seed groups over one ordered reference set."""
    success_a, missing_a, failed_a, extra_a = _event_status(group_a, event_ids)
    success_b, missing_b, failed_b, extra_b = _event_status(group_b, event_ids)
    common = [event_id for event_id in event_ids if event_id in success_a and event_id in success_b]
    vector_a = [_rung_category(group_a.consensus_rung[event_id]) for event_id in common]
    vector_b = [_rung_category(group_b.consensus_rung[event_id]) for event_id in common]
    mutual_kappa = cohens_kappa(vector_a, vector_b)
    passed = (
        group_a.calibrated is True
        and group_b.calibrated is True
        and not missing_a
        and not missing_b
        and not failed_a
        and not failed_b
        and not extra_a
        and not extra_b
        and group_a.gold_kappa_n == len(event_ids)
        and group_b.gold_kappa_n == len(event_ids)
        and len(common) == len(event_ids)
        and mutual_kappa is not None
        and mutual_kappa >= GOLD_KAPPA_THRESHOLD
    )
    combined_kappa = (
        min(group_a.gold_kappa, group_b.gold_kappa)
        if group_a.gold_kappa is not None and group_b.gold_kappa is not None
        else None
    )
    combined_n = min(group_a.gold_kappa_n, group_b.gold_kappa_n)
    return {
        "spec": "roadmap/ideas/idea-reuse-judge-calibration.md",
        "fixture": str(fixture_path),
        "evidence_kind": "single_author_reference_set",
        "judge_prompt": {"id": JUDGE_PROMPT_ID, "version": JUDGE_PROMPT_VERSION},
        "threshold": GOLD_KAPPA_THRESHOLD,
        "reference_set_passed": passed,
        "judge_vs_gold": {
            "kappa": combined_kappa,
            "n": combined_n,
            "calibrated": passed,
            "threshold": GOLD_KAPPA_THRESHOLD,
            "evidence_kind": "single_author_reference_set",
        },
        "groups": {
            "a": _calibration_summary(group_a, fixture_path=fixture_path),
            "b": _calibration_summary(group_b, fixture_path=fixture_path),
        },
        "mutual_agreement": {
            "kappa": mutual_kappa,
            "n": len(common),
            "expected_n": len(event_ids),
            "missing_events": {"a": missing_a, "b": missing_b},
            "extra_events": {"a": extra_a, "b": extra_b},
            "failed_events": {"a": failed_a, "b": failed_b},
        },
    }


def run_reference_validation(
    *,
    provider,
    fixture_path: Path | str = DEFAULT_FIXTURE_PATH,
    seed_groups: tuple[tuple[int, ...], ...] = ((0, 1, 2), (3, 4, 5)),
    sample_size: int = 500,
) -> dict[str, Any]:
    """Run two disjoint seed groups against the same reference cases."""
    if len(seed_groups) != 2:
        raise ValueError("exactly two seed groups are required")
    if any(len(group) < 3 for group in seed_groups):
        raise ValueError("each seed group must contain at least three seeds")
    if any(len(set(group)) != len(group) for group in seed_groups):
        raise ValueError("seeds within each group must be distinct")
    if set(seed_groups[0]) & set(seed_groups[1]):
        raise ValueError("seed groups must be disjoint")
    gold = load_gold_fixture(fixture_path)
    event_ids = [f"ev:{record['id']}" for record in gold]
    group_a = run_calibration(
        provider=provider,
        fixture_path=fixture_path,
        seeds=list(seed_groups[0]),
        sample_size=sample_size,
    )
    group_b = run_calibration(
        provider=provider,
        fixture_path=fixture_path,
        seeds=list(seed_groups[1]),
        sample_size=sample_size,
    )
    return build_reference_validation_summary(
        group_a, group_b, event_ids=event_ids, fixture_path=fixture_path
    )


def _calibration_summary(report: JudgeReport, *, fixture_path: Path | str) -> dict[str, Any]:
    return {
        "spec": "roadmap/ideas/idea-reuse-judge-calibration.md",
        "fixture": str(fixture_path),
        "n_gold": report.gold_kappa_n,
        "evidence_kind": "single_author_reference_set",
        "judge_prompt": {"id": JUDGE_PROMPT_ID, "version": JUDGE_PROMPT_VERSION},
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
            "judge against a maintained single-author reference fixture and report judge-vs-reference "
            "Cohen's kappa + a reference-set verdict against GOLD_KAPPA_THRESHOLD."
        )
    )
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE_PATH)
    parser.add_argument(
        "--seed-groups",
        default="0,1,2;3,4,5",
        help="Two semicolon-separated seed groups (default: 0,1,2;3,4,5).",
    )
    parser.add_argument("--sample-size", type=int, default=500)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Seed + run with a no-op provider (no LLM calls). Kappa is not meaningful.",
    )
    parser.add_argument("--cache-dir", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    args = parser.parse_args(argv)

    try:
        seed_groups = [
            [int(p.strip()) for p in group.split(",") if p.strip()]
            for group in str(args.seed_groups).split(";")
        ]
    except ValueError:
        parser.error("--seed-groups must contain integers")
    if len(seed_groups) != 2 or any(len(group) < 3 for group in seed_groups):
        parser.error("--seed-groups requires two groups of at least three seeds")
    if any(len(set(group)) != len(group) for group in seed_groups):
        parser.error("seeds within each group must be distinct")
    if set(seed_groups[0]) & set(seed_groups[1]):
        parser.error("--seed-groups must be disjoint")

    if args.dry_run:
        provider = _NullProvider()
    else:
        from app.config import AppConfig
        from evals.eval_common import build_eval_providers

        config = AppConfig.from_env()
        _main_provider, provider = build_eval_providers(
            config, cache_dir=args.cache_dir, no_eval_cache=True
        )

    summary = run_reference_validation(
        provider=provider,
        fixture_path=args.fixture,
        seed_groups=(tuple(seed_groups[0]), tuple(seed_groups[1])),
        sample_size=args.sample_size,
    )

    serialised = json.dumps(summary, indent=2, sort_keys=True, default=str)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialised, encoding="utf-8")
        print(f"Wrote calibration report -> {args.output}", file=sys.stderr)
    print(serialised)

    verdict = "PASSED" if summary["reference_set_passed"] else "FAILED"
    mutual = summary["mutual_agreement"]
    print(
        f"reference-set validation mutual_kappa={mutual['kappa']} "
        f"n={mutual['n']} threshold={GOLD_KAPPA_THRESHOLD} -> {verdict}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
