"""RAW / DERIVED / HYBRID retrieval + representation eval — runner.

Offline, DATA-READ-ONLY. Replays REAL historical lookups (from ``query_audit_log``)
through the shipped retrieval stack three times at candidate level (RAW=source_item,
DERIVED=memory_object, HYBRID=mixed) and reports the two retrieval-time seams a
shadow can honestly measure — candidate-recovery (objective evidence link) and
representation-quality (LLM judge, N independent samples). No production code path is
touched; the live DB is only read. The ``SQLiteStorageProvider`` constructor performs
an idempotent schema-ensure on init (same footprint as the fidelity runner) — no rows
are written by this eval.

    python -m evals.raw_derived_hybrid --db ~/.pallium/data/pallium.db --limit 50

The representation judge needs LLM config (via the default use-case package). Without
it (or with ``--no-judge``) the runner degrades to candidate-recovery + token-budget
only.

CAVEATS stamped into every report:
- Arms are REPLAYED against the CURRENT index/config, not the point-in-time candidate
  pool that produced the historical audit row (routing/index drift is not captured).
- The default ``--trigger-origin`` filter (agent_pull/mcp_pull) may include proactive
  MCP pulls, not only reactive agent lookups.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from evals.derivation_fidelity.fidelity import derived_text_of
from evals.raw_derived_hybrid.arms import (
    DERIVED,
    HYBRID,
    KIND_MEMORY,
    KIND_SOURCE,
    RAW,
    TARGET_KIND,
    Candidate,
    DerivedObjectEvidence,
    equal_token_budget,
    evidence_link_recovery,
    partition_candidates,
)
from evals.raw_derived_hybrid.represent import (
    REPRESENTATION_SCHEMA,
    REPRESENTATION_SYSTEM_PROMPT,
    aggregate_representation,
    build_representation_prompt,
    extract_derivation_version,
    parse_representation_response,
)

# Default agent-pull trigger origins (see WR Discovery; may include proactive MCP pulls).
DEFAULT_TRIGGER_ORIGINS = ("agent_pull", "mcp_pull")

# Per-turn display cap for RAW turns rendered into the equal-token-budget axis.
_RAW_RENDER_CAP = 800


@dataclass(frozen=True)
class QueryRow:
    query_text: str
    container_ref: str | None
    thread_ref: str | None
    actor_ref: str | None
    visibility: str | None
    trigger_origin: str | None


# ---------------------------------------------------------------------------
# Read-only enumeration of historical queries (own engine; static SQL)
# ---------------------------------------------------------------------------


def load_query_rows(
    db_path: str,
    *,
    container_ref: str | None,
    thread_ref: str | None,
    actor_ref: str | None,
    trigger_origins: tuple[str, ...] | None,
) -> list[QueryRow]:
    """Load historical lookups from ``query_audit_log`` (read-only SELECT).

    A single static parameterized statement: NULL binds disable the container/thread/
    actor filters; ``trigger_origins`` (default agent_pull/mcp_pull) is applied via an
    expanding IN bind, disabled when None/empty.
    """
    from sqlalchemy import bindparam, create_engine, text

    filter_origin = 1 if trigger_origins else 0
    # Expanding IN requires a non-empty list; use a sentinel when the filter is off.
    origins = list(trigger_origins) if trigger_origins else ["__none__"]

    sql = text(
        "SELECT query_text, container_ref, thread_ref, actor_ref, visibility, "
        "trigger_origin FROM query_audit_log "
        "WHERE (:container_ref IS NULL OR container_ref = :container_ref) "
        "AND (:thread_ref IS NULL OR thread_ref = :thread_ref) "
        "AND (:actor_ref IS NULL OR actor_ref = :actor_ref) "
        "AND (:filter_origin = 0 OR trigger_origin IN :origins) "
        "ORDER BY created_at, id"  # deterministic → seeded shuffle+truncate reproducible
    ).bindparams(bindparam("origins", expanding=True))
    params = {
        "container_ref": container_ref,
        "thread_ref": thread_ref,
        "actor_ref": actor_ref,
        "filter_origin": filter_origin,
        "origins": origins,
    }
    engine = create_engine(f"sqlite:///{db_path}", future=True)
    try:
        with engine.connect() as conn:
            rows = [dict(r._mapping) for r in conn.execute(sql, params)]
    finally:
        engine.dispose()
    return [
        QueryRow(
            query_text=r["query_text"],
            container_ref=r["container_ref"],
            thread_ref=r["thread_ref"],
            actor_ref=r["actor_ref"],
            visibility=r["visibility"],
            trigger_origin=r["trigger_origin"],
        )
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Arm construction (candidate-level replay)
# ---------------------------------------------------------------------------


def _candidate_of(item, rank: int) -> Candidate:
    if item.result_kind == "source_hit" and item.source_item_id:
        return Candidate(kind=KIND_SOURCE, id=item.source_item_id, rank=rank, score=item.score)
    if item.result_kind == "memory_hit" and item.memory_object_id:
        return Candidate(kind=KIND_MEMORY, id=item.memory_object_id, rank=rank, score=item.score)
    # Defensive: unknown kind → tag by result_kind so purity checks still fire.
    other = KIND_MEMORY if item.memory_object_id else KIND_SOURCE
    return Candidate(kind=other, id=(item.result_id or ""), rank=rank, score=item.score)


def _replay_arm(retrieval, name: str, query: QueryRow, *, limit: int, require_visibility: bool):
    result = retrieval.query(
        query.query_text,
        limit,
        None,
        visibility=query.visibility,
        query_container_ref=query.container_ref,
        query_actor_ref=query.actor_ref,
        require_visibility=require_visibility,
        target_kind=TARGET_KIND[name],
    )
    candidates = [_candidate_of(it, i + 1) for i, it in enumerate(result.results)]
    return partition_candidates(name, candidates), result.results


# ---------------------------------------------------------------------------
# Evidence-link recovery universe + rendering
# ---------------------------------------------------------------------------


def _linked_source_ids(storage, memory_object_id: str) -> tuple[str, ...]:
    try:
        evidence = storage.get_evidence_for_memory_object(memory_object_id)
    except Exception:
        return ()
    return tuple(dict.fromkeys(ev.source_item_id for ev in evidence))


def build_recovery_universe(
    storage,
    raw_source_ids: set[str],
    derived_arm_ids: set[str],
) -> list[DerivedObjectEvidence]:
    """Union of episodes recoverable by EITHER arm, for a symmetric recovery signal.

    - DERIVED-arm objects → entered_derived_arm=True; resolve their linked source
      turns to check whether RAW also recovered the episode.
    - Objects linked to RAW-arm source turns but NOT in the DERIVED arm →
      entered_derived_arm=False (the RAW-only / neither cases).
    """
    universe: dict[str, DerivedObjectEvidence] = {}
    for mem_id in derived_arm_ids:
        universe[mem_id] = DerivedObjectEvidence(
            memory_object_id=mem_id,
            source_item_ids=_linked_source_ids(storage, mem_id),
            entered_derived_arm=True,
        )
    if raw_source_ids:
        try:
            # Only RETRIEVABLE objects belong in the recovery universe: a tombstoned or
            # candidate-lifecycle object can never enter the DERIVED arm, so counting it
            # as raw_only would falsely inflate RAW's recovery advantage. Restrict to the
            # visible lifecycles retrieval itself returns.
            linked = storage.list_memory_objects_for_source_items(
                list(raw_source_ids), include_candidates=False, include_soft_deleted=False
            )
        except Exception:
            linked = {}
        for mems in linked.values():
            for m in mems:
                if m.id in universe:
                    continue
                universe[m.id] = DerivedObjectEvidence(
                    memory_object_id=m.id,
                    source_item_ids=_linked_source_ids(storage, m.id),
                    entered_derived_arm=(m.id in derived_arm_ids),
                )
    return list(universe.values())


def _raw_turns_full(storage, raw_arm) -> list[str]:
    """Full retrieved RAW turn contents (for the judge + token-budget axis)."""
    turns: list[str] = []
    for c in raw_arm.candidates:
        try:
            item = storage.get_source_item(c.id)
        except Exception:
            continue
        turns.append(item.content or "")
    return turns


def _render_arm_items(storage, arm) -> list[str]:
    """Render an arm's candidates to text for the equal-token-budget axis."""
    rendered: list[str] = []
    for c in arm.candidates:
        if c.kind == KIND_SOURCE:
            try:
                item = storage.get_source_item(c.id)
                rendered.append((item.content or "")[: _RAW_RENDER_CAP])
            except Exception:
                continue
        else:
            try:
                mem = storage.get_memory_object(c.id)
                rendered.append(derived_text_of(getattr(mem, "payload", None)))
            except Exception:
                continue
    return rendered


# ---------------------------------------------------------------------------
# Representation judge (query-conditioned, sees FULL retrieved RAW turns)
# ---------------------------------------------------------------------------


def judge_representation(
    judge_provider,
    *,
    query: str,
    raw_turns: list[str],
    derived_text: str,
    samples: int,
) -> dict:
    parsed = []
    for ordinal in range(samples):
        prompt = build_representation_prompt(
            query, raw_turns, derived_text, sample_ordinal=ordinal
        )
        try:
            response = judge_provider.generate_json(
                system_prompt=REPRESENTATION_SYSTEM_PROMPT,
                user_prompt=prompt,
                schema_description=REPRESENTATION_SCHEMA,
            )
            parsed.append(parse_representation_response(getattr(response, "parsed_json", None)))
        except Exception:  # judge failure must not abort the eval
            parsed.append(parse_representation_response(None))
    return aggregate_representation(parsed)


# ---------------------------------------------------------------------------
# Per-query orchestration
# ---------------------------------------------------------------------------


def run_query(
    storage,
    retrieval,
    judge_provider,
    query: QueryRow,
    *,
    retrieval_limit: int,
    judge_samples: int,
    represent_limit: int,
    token_budgets: list[int],
    require_visibility: bool,
) -> dict:
    raw_arm, _raw_results = _replay_arm(
        retrieval, RAW, query, limit=retrieval_limit, require_visibility=require_visibility
    )
    derived_arm, _derived_results = _replay_arm(
        retrieval, DERIVED, query, limit=retrieval_limit, require_visibility=require_visibility
    )
    hybrid_arm, _hybrid_results = _replay_arm(
        retrieval, HYBRID, query, limit=retrieval_limit, require_visibility=require_visibility
    )

    raw_source_ids = raw_arm.ids_of_kind(KIND_SOURCE)
    derived_arm_ids = derived_arm.ids_of_kind(KIND_MEMORY)

    universe = build_recovery_universe(storage, raw_source_ids, derived_arm_ids)
    recovery = evidence_link_recovery(raw_source_ids, universe)

    # Equal-token-budget context-cost axis (SEPARATE — never fed to the judge).
    raw_turns_full = _raw_turns_full(storage, raw_arm)  # judge input only (uncapped)
    # Render RAW turns through the SAME per-turn cap HYBRID uses, so a source turn counts
    # identically in RAW and HYBRID — otherwise the "equal budget" the axis exists to
    # guarantee is skewed for turns longer than the cap.
    arm_rendered = {
        RAW: _render_arm_items(storage, raw_arm),
        DERIVED: _render_arm_items(storage, derived_arm),
        HYBRID: _render_arm_items(storage, hybrid_arm),
    }
    token_budget = {
        str(budget): {
            arm: equal_token_budget(items, budget) for arm, items in arm_rendered.items()
        }
        for budget in token_budgets
    }

    # Representation-quality seam: judge each DERIVED-arm object vs FULL retrieved RAW.
    represent_objects: list[dict] = []
    derived_candidates = [c for c in derived_arm.candidates if c.kind == KIND_MEMORY]
    if represent_limit > 0:
        derived_candidates = derived_candidates[:represent_limit]
    for c in derived_candidates:
        try:
            mem = storage.get_memory_object(c.id)
        except Exception:
            continue
        derived_text = derived_text_of(getattr(mem, "payload", None))
        entry: dict[str, Any] = {
            "memory_object_id": c.id,
            "rank": c.rank,
            "version": extract_derivation_version(mem),
            "representation": None,
        }
        if judge_provider is not None:
            entry["representation"] = judge_representation(
                judge_provider,
                query=query.query_text,
                raw_turns=raw_turns_full,
                derived_text=derived_text,
                samples=judge_samples,
            )
        represent_objects.append(entry)

    return {
        "query_text": query.query_text,
        "trigger_origin": query.trigger_origin,
        "arms": {
            RAW: raw_arm.to_dict(),
            DERIVED: derived_arm.to_dict(),
            HYBRID: hybrid_arm.to_dict(),
        },
        "candidate_recovery": recovery,
        "representation_quality": {
            "seam": "representation_quality",
            "judged_object_count": len(represent_objects),
            "objects": represent_objects,
        },
        "context_cost_equal_token_budget": {
            "seam": "context_cost",
            "note": "Separate axis; NOT fed to the representation judge (which sees full RAW turns).",
            "raw_turn_count": len(raw_turns_full),
            "by_budget": token_budget,
        },
    }


def run_eval(
    *,
    db_path: str | None,
    storage,
    retrieval,
    judge_provider,
    report_time_model: str | None,
    limit: int,
    seed: int,
    container_ref: str | None,
    thread_ref: str | None,
    actor_ref: str | None,
    trigger_origins: tuple[str, ...] | None,
    retrieval_limit: int,
    judge_samples: int,
    represent_limit: int,
    token_budgets: list[int],
    queries: list[QueryRow] | None = None,
    require_visibility: bool = False,
) -> dict:
    if queries is None:
        if db_path is None:
            raise ValueError("run_eval needs either db_path or an explicit queries list")
        queries = load_query_rows(
            db_path,
            container_ref=container_ref,
            thread_ref=thread_ref,
            actor_ref=actor_ref,
            trigger_origins=trigger_origins,
        )
    rng = random.Random(seed)
    rng.shuffle(queries)
    if limit > 0:
        queries = queries[:limit]

    per_query = [
        run_query(
            storage, retrieval, judge_provider, q,
            retrieval_limit=retrieval_limit, judge_samples=judge_samples,
            represent_limit=represent_limit, token_budgets=token_budgets,
            require_visibility=require_visibility,
        )
        for q in queries
    ]

    # Aggregate the OBJECTIVE candidate-recovery seam across queries (judge-free).
    recovery_counts = {"both": 0, "raw_only": 0, "derived_only": 0, "neither": 0}
    n_recovery_objects = 0
    for pq in per_query:
        for k, v in pq["candidate_recovery"]["counts"].items():
            recovery_counts[k] += v
        n_recovery_objects += pq["candidate_recovery"]["n_objects"]

    return {
        "eval": "raw_derived_hybrid.v1",
        "seam_note": (
            "RETRIEVAL-SIDE seams only. Two seams reported, NEVER blended: "
            "candidate_recovery (objective evidence link, judge-free) and "
            "representation_quality (query-conditioned LLM judge). context_cost is a "
            "separate equal-token-budget control. Downstream/consumption is OUT (a "
            "shadow arm is never shown to the agent). Source-fidelity is NOT "
            "re-published here — it lives in evals/derivation_fidelity. No blended "
            "'derived is better' number is emitted."
        ),
        "caveats": {
            "current_index_replay": (
                "Arms were REPLAYED against the CURRENT index/config, NOT the "
                "point-in-time candidate pool of the historical audit row. Routing "
                "and index drift since the query are not captured; point-in-time "
                "replay would require a live seam."
            ),
            "trigger_origin_filter": (
                "The default agent_pull/mcp_pull filter may include proactive MCP "
                "pulls, not only reactive agent lookups."
            ),
            "token_budget_estimate": (
                "Token budget uses the ceil(len/4) estimate (no tiktoken); the "
                "comparison is relative, not an absolute token count."
            ),
        },
        "report_time_model": report_time_model,
        "report_time_model_caveat": (
            "Concrete model id is resolved from current config, NOT recorded per "
            "object (only logical model_role is). Historical objects may have been "
            "derived under a different model."
        ),
        "params": {
            "db": db_path, "limit": limit, "seed": seed,
            "retrieval_limit": retrieval_limit, "judge_samples": judge_samples,
            "represent_limit": represent_limit, "token_budgets": token_budgets,
            "container_ref": container_ref, "thread_ref": thread_ref,
            "actor_ref": actor_ref,
            "trigger_origins": list(trigger_origins) if trigger_origins else None,
        },
        "candidate_recovery_aggregate": {
            "seam": "candidate_recovery",
            "n_objects": n_recovery_objects,
            "counts": recovery_counts,
        },
        "query_count": len(per_query),
        "queries": per_query,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="RAW/DERIVED/HYBRID retrieval + representation eval (offline replay)"
    )
    p.add_argument("--db", default=None, help="SQLite DB path (default ~/.pallium/data/pallium.db)")
    p.add_argument("--limit", type=int, default=50, help="max historical queries to sample (0 = all)")
    p.add_argument("--seed", type=int, default=17, help="sampling seed (reproducibility)")
    p.add_argument("--container", default=None, help="filter to a container_ref")
    p.add_argument("--thread", default=None, help="filter to a thread_ref")
    p.add_argument("--actor", default=None, help="filter to an actor_ref")
    p.add_argument(
        "--trigger-origin", default=",".join(DEFAULT_TRIGGER_ORIGINS),
        help="comma-separated trigger_origin filter, or 'all' for no filter "
        f"(default {','.join(DEFAULT_TRIGGER_ORIGINS)})",
    )
    p.add_argument("--retrieval-limit", type=int, default=10, help="candidates per arm replay")
    p.add_argument("--judge-samples", type=int, default=3, help="independent judge draws per object")
    p.add_argument("--represent-limit", type=int, default=5, help="max DERIVED objects judged per query (0 = all)")
    p.add_argument("--token-budgets", default="512,1024", help="comma-separated equal-token budgets")
    p.add_argument("--cache-dir", default=None, help="LLM response cache dir (reproducibility)")
    p.add_argument("--no-eval-cache", action="store_true", help="disable the LLM cache")
    p.add_argument("--no-judge", action="store_true", help="skip the representation judge")
    p.add_argument("--out", default=None, help="output JSON path (default under .local/research/)")
    return p


def _parse_trigger_origins(raw: str) -> tuple[str, ...] | None:
    if raw.strip().lower() == "all":
        return None
    origins = tuple(o.strip() for o in raw.split(",") if o.strip())
    return origins or None


def _parse_budgets(raw: str) -> list[int]:
    budgets = []
    for tok in raw.split(","):
        tok = tok.strip()
        if tok:
            budgets.append(int(tok))
    return budgets or [1024]


def _build_judge(args) -> tuple[Any, str | None]:
    """Build the judge provider directly (control the cache key, avoid default-package
    coupling). Returns (provider|None, model). Degrades to no-judge on any error."""
    if args.no_judge:
        return None, None
    try:
        from app.config import AppConfig
        from app.dependencies import build_llm_provider
        config = AppConfig.from_env()
        pkg = config.package_config(config.default_use_case)
        if not pkg.llm_provider or not pkg.model:
            print("No LLM package config; running without the representation judge.", file=sys.stderr)
            return None, None
        provider = build_llm_provider(config, provider_name=pkg.llm_provider, model=pkg.model)
        if args.cache_dir and not args.no_eval_cache:
            from providers.llm.cached import CachedLLMProvider
            provider = CachedLLMProvider(provider, Path(args.cache_dir), model_tag=pkg.model)
        return provider, pkg.model
    except Exception as exc:  # config/provider errors → no-judge, not a crash
        print(f"Judge unavailable ({type(exc).__name__}: {exc}); running without judge.", file=sys.stderr)
        return None, None


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    db_path = args.db or str(Path.home() / ".pallium" / "data" / "pallium.db")
    if not Path(db_path).exists():
        print(f"DB not found at {db_path}, pass --db", file=sys.stderr)
        return 1

    import dataclasses

    from app.config import AppConfig
    from app.dependencies import build_retrieval_provider, build_storage_provider

    # Build storage against the requested DB; retrieval on top of it (lexical only —
    # vector is not constructed here; offline replay deliberately avoids build_service
    # to stay off guarded wiring). AppConfig is frozen, so point it at --db via replace.
    config = dataclasses.replace(
        AppConfig.from_env(), storage_backend="sqlite", sqlite_url=f"sqlite:///{db_path}"
    )
    storage = build_storage_provider(config)
    retrieval = build_retrieval_provider(storage)
    judge_provider, report_model = _build_judge(args)

    try:
        report = run_eval(
            db_path=db_path, storage=storage, retrieval=retrieval,
            judge_provider=judge_provider, report_time_model=report_model,
            limit=args.limit, seed=args.seed,
            container_ref=args.container, thread_ref=args.thread, actor_ref=args.actor,
            trigger_origins=_parse_trigger_origins(args.trigger_origin),
            retrieval_limit=args.retrieval_limit, judge_samples=args.judge_samples,
            represent_limit=args.represent_limit,
            token_budgets=_parse_budgets(args.token_budgets),
        )
    finally:
        # Best-effort release of the storage provider's engine (tidy-up at exit).
        engine = getattr(storage, "_engine", None)
        if engine is not None:
            try:
                engine.dispose()
            except Exception:
                pass

    out = args.out or str(Path(".local") / "research" / "raw_derived_hybrid_report.json")
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    agg = report["candidate_recovery_aggregate"]
    print(f"Wrote {out}")
    print(f"queries={report['query_count']}")
    print(f"candidate_recovery counts={agg['counts']} (n_objects={agg['n_objects']})")
    print(f"judge={'on' if judge_provider is not None else 'off'} model={report_model}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
