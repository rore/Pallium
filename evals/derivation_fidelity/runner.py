"""Source-episode derivation coverage + fidelity eval — runner.

Offline, READ-ONLY. Starts from sampled source items, measures extraction/coverage
(no LLM) segmented by producer granularity, and — where derived objects exist —
scores derivation fidelity with an offline judge (N independent samples). No
production code path is touched; the live DB is only read.

    python -m evals.derivation_fidelity --db ~/.pallium/data/pallium.db --limit 200

The judge needs LLM config (via the default use-case package). Without it, pass
``--coverage-only`` (or the runner degrades to coverage-only automatically).
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path
from typing import Any

from evals.derivation_fidelity.coverage import (
    ItemRecord,
    LinkedObject,
    aggregate_coverage,
    object_is_demoted,
)
from evals.derivation_fidelity.fidelity import (
    FIDELITY_SCHEMA,
    FIDELITY_SYSTEM_PROMPT,
    aggregate_fidelity,
    build_fidelity_prompt,
    compression_ratio,
    derived_text_of,
    extract_derivation_version,
    parse_fidelity_response,
)

_PROCESSED_STATUSES = frozenset({"completed"})


# ---------------------------------------------------------------------------
# Read-only enumeration (own engine; never reaches into StorageProvider privates)
# ---------------------------------------------------------------------------


def load_source_rows(
    db_path: str,
    *,
    container_ref: str | None,
    thread_ref: str | None,
) -> list[dict[str, Any]]:
    from sqlalchemy import create_engine, text

    engine = create_engine(f"sqlite:///{db_path}", future=True)
    # Single static parameterized query (no string-built SQL): a NULL bind disables
    # the corresponding filter. Read-only SELECT only.
    sql = text(
        "SELECT id, container_ref, thread_ref, processing_status, "
        "processing_completed_at FROM source_items "
        "WHERE (:container_ref IS NULL OR container_ref = :container_ref) "
        "AND (:thread_ref IS NULL OR thread_ref = :thread_ref)"
    )
    params = {"container_ref": container_ref, "thread_ref": thread_ref}
    try:
        with engine.connect() as conn:
            rows = [dict(r._mapping) for r in conn.execute(sql, params)]
    finally:
        engine.dispose()
    return rows


def _to_linked_object(mem) -> LinkedObject:
    env = getattr(mem, "envelope", None)
    deriv = getattr(env, "derivation", None) if env is not None else None
    return LinkedObject(
        memory_object_id=mem.id,
        memory_type=getattr(mem, "type", "unknown") or "unknown",
        producer_kind=getattr(deriv, "producer_kind", None),
        demoted=object_is_demoted(
            is_soft_deleted=getattr(mem, "is_soft_deleted", False),
            lifecycle=getattr(mem, "lifecycle", "active"),
        ),
    )


# ---------------------------------------------------------------------------
# Fidelity pass
# ---------------------------------------------------------------------------


def _thread_context_turns(storage, mem, linked_source_ids: set[str], *, max_context: int) -> tuple[list[str], list[str]]:
    """Return (linked_turns, context_turns) text for one derived object.

    Linked turns come from the object's explicit evidence; context turns are other
    turns in the same thread (bounded), so the judge doesn't false-positive a claim
    grounded in an adjacent turn.
    """
    evidence = storage.get_evidence_for_memory_object(mem.id)
    linked_turns: list[str] = []
    container = thread = None
    for ev in evidence:
        item = storage.get_source_item(ev.source_item_id)
        linked_turns.append(item.content or "")
        container = container or item.container_ref
        thread = thread or item.thread_ref
    context_turns: list[str] = []
    if container is not None and thread is not None:
        neighbors = storage.list_source_items_for_thread(container, thread)
        for it in neighbors:
            if it.id in linked_source_ids or it.forgotten:
                continue
            context_turns.append(it.content or "")
            if len(context_turns) >= max_context:
                break
    return linked_turns, context_turns


def judge_object(
    storage,
    judge_provider,
    mem,
    *,
    samples: int,
    max_context: int,
) -> dict:
    evidence = storage.get_evidence_for_memory_object(mem.id)
    linked_source_ids = {ev.source_item_id for ev in evidence}
    linked_turns, context_turns = _thread_context_turns(
        storage, mem, linked_source_ids, max_context=max_context
    )
    derived_text = derived_text_of(getattr(mem, "payload", None))
    source_chars = sum(len(t) for t in linked_turns)

    result: dict[str, Any] = {
        "memory_object_id": mem.id,
        "version": extract_derivation_version(mem),
        "linked_turn_count": len(linked_turns),
        "context_turn_count": len(context_turns),
        "compression_ratio": compression_ratio(source_chars, len(derived_text)),
    }
    if judge_provider is None:
        result["fidelity"] = None
        return result

    parsed_samples = []
    for ordinal in range(samples):
        prompt = build_fidelity_prompt(
            linked_turns=linked_turns,
            context_turns=context_turns,
            derived_text=derived_text,
            sample_ordinal=ordinal,
        )
        try:
            response = judge_provider.generate_json(
                system_prompt=FIDELITY_SYSTEM_PROMPT,
                user_prompt=prompt,
                schema_description=FIDELITY_SCHEMA,
            )
            parsed_samples.append(parse_fidelity_response(getattr(response, "parsed_json", None)))
        except Exception:  # judge failure must not abort the eval
            parsed_samples.append(parse_fidelity_response(None))
    result["fidelity"] = aggregate_fidelity(parsed_samples)
    return result


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def run_eval(
    *,
    db_path: str,
    storage,
    judge_provider,
    report_time_model: str | None,
    limit: int,
    seed: int,
    container_ref: str | None,
    thread_ref: str | None,
    judge_samples: int,
    fidelity_limit: int,
    max_context: int,
) -> dict:
    rows = load_source_rows(db_path, container_ref=container_ref, thread_ref=thread_ref)
    rng = random.Random(seed)
    rng.shuffle(rows)
    if limit > 0:
        rows = rows[:limit]

    source_ids = [r["id"] for r in rows]
    linked_map = storage.list_memory_objects_for_source_items(
        source_ids, include_candidates=True, include_soft_deleted=True
    )

    records: list[ItemRecord] = []
    active_objects: dict[str, Any] = {}
    for r in rows:
        mems = linked_map.get(r["id"], [])
        linked = tuple(_to_linked_object(m) for m in mems)
        records.append(
            ItemRecord(
                source_item_id=r["id"],
                container_ref=r["container_ref"],
                thread_ref=r["thread_ref"],
                processed=(r["processing_status"] in _PROCESSED_STATUSES),
                linked=linked,
            )
        )
        for m in mems:
            if not object_is_demoted(
                is_soft_deleted=getattr(m, "is_soft_deleted", False),
                lifecycle=getattr(m, "lifecycle", "active"),
            ):
                active_objects[m.id] = m  # dedup (thread producers linked to many items)

    coverage = aggregate_coverage(records)

    fidelity_objects = list(active_objects.values())
    rng.shuffle(fidelity_objects)
    if fidelity_limit > 0:
        fidelity_objects = fidelity_objects[:fidelity_limit]
    fidelity = [
        judge_object(storage, judge_provider, m, samples=judge_samples, max_context=max_context)
        for m in fidelity_objects
    ]

    return {
        "eval": "derivation_fidelity.v1",
        "seam_note": (
            "coverage and fidelity are the two DERIVATION-SIDE seams; retrieval and "
            "representation seams live in idea-raw-derived-hybrid-shadow-eval. No "
            "blended 'derivation quality' number is emitted."
        ),
        "params": {
            "db": db_path, "limit": limit, "seed": seed,
            "judge_samples": judge_samples, "fidelity_limit": fidelity_limit,
            "container_ref": container_ref, "thread_ref": thread_ref,
        },
        "report_time_model": report_time_model,
        "report_time_model_caveat": (
            "Concrete model id is resolved from current config, NOT recorded per "
            "object (only logical model_role is). Historical objects may have been "
            "derived under a different model."
        ),
        "coverage": coverage,
        "fidelity": {
            "judged_object_count": len(fidelity),
            "objects": fidelity,
        },
    }


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Source-episode derivation coverage + fidelity eval")
    p.add_argument("--db", default=None, help="SQLite DB path (default ~/.pallium/data/pallium.db)")
    p.add_argument("--limit", type=int, default=200, help="max source items to sample (0 = all)")
    p.add_argument("--seed", type=int, default=17, help="sampling seed (reproducibility)")
    p.add_argument("--container", default=None, help="filter to a container_ref")
    p.add_argument("--thread", default=None, help="filter to a thread_ref")
    p.add_argument("--judge-samples", type=int, default=3, help="independent judge draws per object")
    p.add_argument("--fidelity-limit", type=int, default=25, help="max derived objects to judge (0 = all)")
    p.add_argument("--max-context", type=int, default=8, help="max same-thread context turns shown to the judge")
    p.add_argument("--cache-dir", default=None, help="LLM response cache dir (reproducibility)")
    p.add_argument("--no-eval-cache", action="store_true", help="disable the LLM cache")
    p.add_argument("--coverage-only", action="store_true", help="skip the fidelity judge")
    p.add_argument("--out", default=None, help="output JSON path (default under .local/research/)")
    return p


def _build_judge(args) -> tuple[Any, str | None]:
    """Build the judge provider directly (not build_eval_providers, to control the
    cache key and avoid the default-package coupling). Returns (provider|None, model)."""
    if args.coverage_only:
        return None, None
    try:
        from app.config import AppConfig
        from app.dependencies import build_llm_provider
        config = AppConfig.from_env()
        pkg = config.package_config(config.default_use_case)
        if not pkg.llm_provider or not pkg.model:
            print("No LLM package config; running coverage-only.", file=sys.stderr)
            return None, None
        provider = build_llm_provider(config, provider_name=pkg.llm_provider, model=pkg.model)
        if args.cache_dir and not args.no_eval_cache:
            from providers.llm.cached import CachedLLMProvider
            provider = CachedLLMProvider(provider, Path(args.cache_dir), model_tag=pkg.model)
        return provider, pkg.model
    except Exception as exc:  # config/provider errors → coverage-only, not a crash
        print(f"Judge unavailable ({type(exc).__name__}: {exc}); running coverage-only.", file=sys.stderr)
        return None, None


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    db_path = args.db or str(Path.home() / ".pallium" / "data" / "pallium.db")
    if not Path(db_path).exists():
        print(f"DB not found at {db_path}, pass --db", file=sys.stderr)
        return 1

    from storage.sqlite import SQLiteStorageProvider

    storage = SQLiteStorageProvider(database_url=f"sqlite:///{db_path}")
    judge_provider, report_model = _build_judge(args)

    report = run_eval(
        db_path=db_path, storage=storage, judge_provider=judge_provider,
        report_time_model=report_model, limit=args.limit, seed=args.seed,
        container_ref=args.container, thread_ref=args.thread,
        judge_samples=args.judge_samples, fidelity_limit=args.fidelity_limit,
        max_context=args.max_context,
    )

    out = args.out or str(Path(".local") / "research" / "derivation_fidelity_report.json")
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    cov = report["coverage"]
    ie = cov["item_extraction"]
    ta = cov["thread_aggregation"]
    print(f"Wrote {out}")
    print(f"sampled={cov['sampled_items']} pending={cov['pending_items']}")
    print(f"item_extraction coverage_rate={ie['coverage_rate']} (processed={ie['processed_denominator']})")
    print(f"thread_aggregation coverage_rate={ta['coverage_rate']} (threads={ta['processed_denominator']})")
    print(f"fidelity judged={report['fidelity']['judged_object_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
