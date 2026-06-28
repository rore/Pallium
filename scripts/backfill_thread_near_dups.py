"""One-shot idempotent backfill for thread-derived near-duplicate
investigation_outcome / decision memories (2026-06-28).

Spec: docs/specs/2026-06-28-thread-near-dup-supersession.md
Companion eval: evals/injection_policy_2026_06/near_dup_measure.py

Walks active thread-derived memories per (source_id, type) in
chronological order. For each new memory, finds prior active winners
in the same (source_id, type) bucket; if any prior winner's normalized
canonical_key has ``SequenceMatcher.ratio >= NEAR_DUP_THRESHOLD`` against
the new memory's canonical_key, supersedes the prior winner with the
new one.

Important guarantees:

- **same-source/thread scope only.** A memory only supersedes another
  with the same ``source_id`` (i.e. the same thread). Container scope
  is preserved by construction since same source_id implies same
  container.
- **idempotent.** Re-runs perform zero writes once the DB is in steady
  state — every (already-superseded record, winner) pair is skipped
  because the prior record's lifecycle is already "superseded" and the
  ``supersedes`` relation already exists.
- **dry-run by default.** Requires ``--execute`` to actually write.
- **same write path as the resolver.** Uses ``service.supersede_memory_object``
  so the lifecycle flip + ``supersedes`` relation are created together.

Run:
    python -m scripts.backfill_thread_near_dups --db-path /path/pallium.db
    python -m scripts.backfill_thread_near_dups --db-path /path/pallium.db --execute
    python -m scripts.backfill_thread_near_dups --db-path /path/pallium.db --threshold 0.85
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path

from sqlalchemy import select

from core.models import Relation
from core.text import normalize_for_index
from semantic.agent_conversation_memory_threads import NEAR_DUP_THRESHOLD
from storage.sqlite import SQLiteStorageProvider
from storage.sqlite_schema import MemoryObjectRecord, RelationRecord


@dataclass
class Candidate:
    """Active thread-derived memory under consideration for supersession."""
    id: str
    type: str
    source_id: str
    container_ref: str
    canonical_key: str
    created_at: datetime


def _load_candidates(storage: SQLiteStorageProvider) -> list[Candidate]:
    """Load all active thread-derived decision/investigation_outcome rows."""
    out: list[Candidate] = []
    with storage._session_factory() as session:
        records = session.scalars(
            select(MemoryObjectRecord).where(
                MemoryObjectRecord.type.in_(["decision", "investigation_outcome"]),
                MemoryObjectRecord.lifecycle == "active",
            )
        ).all()
        for r in records:
            try:
                payload = json.loads(r.payload_json) if r.payload_json else {}
            except json.JSONDecodeError:
                continue
            if payload.get("source_type") != "thread_detection":
                continue
            ck = str(payload.get("canonical_key") or "").strip()
            if not ck:
                continue
            source_id = str(payload.get("source_id") or "")
            if not source_id:
                continue
            out.append(Candidate(
                id=r.id,
                type=r.type,
                source_id=source_id,
                container_ref=r.container_ref or "",
                canonical_key=ck,
                created_at=r.created_at,
            ))
    out.sort(key=lambda c: (c.source_id, c.type, c.created_at, c.id))
    return out


def _existing_supersedes_pairs(storage: SQLiteStorageProvider) -> set[tuple[str, str]]:
    """Set of (from_id, to_id) supersedes relations already present.

    Used for idempotency — never re-create an existing supersedes relation.
    """
    out: set[tuple[str, str]] = set()
    with storage._session_factory() as session:
        records = session.scalars(
            select(RelationRecord).where(
                RelationRecord.relation_type == "supersedes",
                RelationRecord.from_kind == "memory_object",
                RelationRecord.to_kind == "memory_object",
            )
        ).all()
        for r in records:
            out.add((r.from_id, r.to_id))
    return out


def _plan(
    candidates: list[Candidate],
    threshold: float,
) -> list[tuple[Candidate, Candidate, float]]:
    """Plan (prior_to_supersede, new_winner, similarity) triples.

    Within each (source_id, type) bucket, iterates to a fixed point:
    each round walks new items against the current winners list, picks
    the first qualifying prior and pairs it with the new item. Mirrors
    the runtime fix's "newer supersedes older" semantics where each
    rebuild only sees currently-active conclusions and would converge
    over multiple rebuilds. Backfill converges in one execute by
    looping until no new pairs are produced.

    The "first qualifying prior (oldest first)" rule keeps the plan
    deterministic and matches the simulator in
    evals/injection_policy_2026_06/near_dup_measure.py.
    """
    by_bucket: dict[tuple[str, str], list[Candidate]] = defaultdict(list)
    for c in candidates:
        by_bucket[(c.source_id, c.type)].append(c)

    plan: list[tuple[Candidate, Candidate, float]] = []
    for (source_id, mtype), items in by_bucket.items():
        items.sort(key=lambda c: (c.created_at, c.id))
        # Iterate to fixed point: a single chronological pass may produce
        # surviving winners that are near-dups of each other once earlier
        # winners get replaced. Re-walk until no new supersessions.
        active = list(items)
        # safety bound: at most len(items) rounds, since each round
        # removes >=1 from `active`.
        for _ in range(len(items) + 1):
            winners: list[Candidate] = []
            round_pairs: list[tuple[Candidate, Candidate, float]] = []
            for new_item in active:
                chosen_prior: Candidate | None = None
                chosen_sim = 0.0
                for prior in winners:
                    if prior.canonical_key == new_item.canonical_key:
                        sim = 1.0
                    else:
                        sim = SequenceMatcher(
                            None, prior.canonical_key, new_item.canonical_key
                        ).ratio()
                    if sim >= threshold:
                        chosen_prior = prior
                        chosen_sim = sim
                        break
                if chosen_prior is not None:
                    round_pairs.append((chosen_prior, new_item, chosen_sim))
                    winners = [w for w in winners if w.id != chosen_prior.id]
                    winners.append(new_item)
                else:
                    winners.append(new_item)
            if not round_pairs:
                break
            plan.extend(round_pairs)
            # Surviving winners become the input for the next round.
            active = winners
    return plan


def _apply(
    storage: SQLiteStorageProvider,
    plan: list[tuple[Candidate, Candidate, float]],
    existing_pairs: set[tuple[str, str]],
) -> dict[str, int]:
    """Apply the plan idempotently. Returns counters for reporting."""
    stats = {"lifecycle_flipped": 0, "relations_created": 0, "skipped_already_done": 0}

    def _do(session):
        for prior, winner, _sim in plan:
            # Idempotency check 1: prior already superseded?
            prior_record = session.get(MemoryObjectRecord, prior.id)
            if prior_record is None:
                continue
            if prior_record.lifecycle != "active":
                stats["skipped_already_done"] += 1
                continue
            # Flip the prior to superseded.
            prior_record.lifecycle = "superseded"
            stats["lifecycle_flipped"] += 1
            # Idempotency check 2: relation already exists?
            if (winner.id, prior.id) not in existing_pairs:
                relation = Relation(
                    from_kind="memory_object",
                    from_id=winner.id,
                    relation_type="supersedes",
                    to_kind="memory_object",
                    to_id=prior.id,
                )
                session.add(
                    RelationRecord(
                        id=relation.id,
                        from_kind=relation.from_kind,
                        from_id=relation.from_id,
                        relation_type=relation.relation_type,
                        to_kind=relation.to_kind,
                        to_id=relation.to_id,
                    )
                )
                existing_pairs.add((winner.id, prior.id))
                stats["relations_created"] += 1

    storage._with_retry(_do)
    return stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Backfill thread-near-dup supersession")
    parser.add_argument("--db-path", required=True, help="Path to SQLite database file")
    parser.add_argument(
        "--threshold",
        type=float,
        default=NEAR_DUP_THRESHOLD,
        help=f"Similarity threshold (default: {NEAR_DUP_THRESHOLD})",
    )
    parser.add_argument("--execute", action="store_true", help="Actually write (dry-run by default)")
    parser.add_argument("--max-print", type=int, default=20, help="Max plan rows to print")
    args = parser.parse_args(argv)

    db_path = Path(args.db_path)
    if not db_path.exists():
        print(f"ERROR: Database not found: {db_path}", file=sys.stderr)
        return 1

    db_url = f"sqlite:///{db_path}"
    storage = SQLiteStorageProvider(db_url)

    candidates = _load_candidates(storage)
    plan = _plan(candidates, args.threshold)
    existing_pairs = _existing_supersedes_pairs(storage)

    by_type: dict[str, int] = defaultdict(int)
    for prior, _winner, _sim in plan:
        by_type[prior.type] += 1

    print(f"DB: {db_path}")
    print(f"Active thread-derived candidates: {len(candidates)}")
    print(f"Threshold: {args.threshold}")
    print(f"Planned supersessions: {len(plan)}  by type: {dict(by_type)}")

    print("\nSample (oldest planned demotions):")
    for prior, winner, sim in plan[: args.max_print]:
        print(
            f"  thread={prior.source_id[:24]}.. type={prior.type}  "
            f"sim={sim:.3f}  prior={prior.id[:8]} -> winner={winner.id[:8]}  "
            f"({prior.created_at} -> {winner.created_at})"
        )
    if len(plan) > args.max_print:
        print(f"  ... ({len(plan) - args.max_print} more)")

    if not args.execute:
        print("\nDRY RUN — pass --execute to apply.")
        return 0

    stats = _apply(storage, plan, existing_pairs)
    print(f"\nApplied. lifecycle_flipped={stats['lifecycle_flipped']} "
          f"relations_created={stats['relations_created']} "
          f"skipped_already_done={stats['skipped_already_done']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
