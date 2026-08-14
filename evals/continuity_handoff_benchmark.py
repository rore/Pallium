"""Experiment 2 — cross-context work-continuity handoff measurement harness.

Measurement only (design 015 Phase 2 / idea-cross-context-work-continuity):
does a *pointer+pull* handoff — an identified source session, plus the shipped
``source_only`` search and ``GET /source/{id}/context`` expansion — let a
receiving session continue prior work as correctly as the manual baselines
(read-the-transcript / paste-a-summary), at lower user-orchestration cost?

This does NOT build any continuity mechanism (no session correlation, no
``agent_ref`` routing, no continuation packaging). It only *measures* four
context-source arms feeding one shared continuation-generation path.

The four arms differ ONLY in the context handed to the receiving session; the
continuation generation and rubric scoring are reused verbatim from
``work_resumption_benchmark`` so the comparison is apples-to-apples:

- ``no_memory``       — current-thread context only (nothing routed in).
- ``pull_backed``     — Pallium P1: ``source_only`` search -> top-K source hits
                        -> ``/source/{id}/context`` expansion, assembled from the
                        ACTUAL API response surface (redacted excerpts + returned
                        neighbor turns), not an idealized transcript.
- ``manual_transcript`` — the whole prior-session transcript pasted in.
- ``manual_summary``    — a human-authored handoff summary pasted in.

Orchestration cost is proxied by the deterministic token count of the context a
*user* must route into the receiving session per arm (pull's raw context is
pulled agent-side and does not count as user cost).
"""
from __future__ import annotations

import argparse
import json
import statistics
from collections import Counter
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from fastapi.testclient import TestClient

from app.config import AppConfig
from app.dependencies import build_llm_provider
from app.main import create_app
from providers.llm.base import LLMProvider
from providers.llm.cached import CachedLLMProvider
from evals.work_resumption_benchmark import (
    DIMENSION_ORDER,
    _compare_continuations,
    _generate_continuation,
    _score_continuation,
)

DEFAULT_SCENARIO_FILE = Path("evals/continuity_handoff/scenarios.json")
DEFAULT_OUTPUT_DIR = Path("evals/continuity_handoff/output")
DEFAULT_SEEDS = 3
DEFAULT_TOP_K = 3

# Arm identifiers double as the ``branch`` label passed to the reused
# _generate_continuation (used only inside the prompt + stub keying).
ARM_NO_MEMORY = "no_memory"
ARM_PULL_BACKED = "pull_backed"
ARM_MANUAL_TRANSCRIPT = "manual_transcript"
ARM_MANUAL_SUMMARY = "manual_summary"
ARMS = (ARM_NO_MEMORY, ARM_PULL_BACKED, ARM_MANUAL_TRANSCRIPT, ARM_MANUAL_SUMMARY)
MANUAL_ARMS = (ARM_MANUAL_TRANSCRIPT, ARM_MANUAL_SUMMARY)


def _estimate_tokens(text: str) -> int:
    """Deterministic ~token count (chars/4). No tokenizer dependency, so the
    orchestration-cost proxy is stable across machines and CI."""
    if not text:
        return 0
    return max(1, len(text) // 4)


def _with_private_default(payload: dict[str, Any]) -> dict[str, Any]:
    """Cross-session continuity is inherently private + container-scoped: raw
    turns carry an actor_ref, and public retrieval requires actor_ref is None,
    so these scenarios ingest and query under private visibility."""
    updated = dict(payload)
    updated.setdefault("visibility", "private")
    return updated


def _sample_provider(base: LLMProvider, *, sample_index: int, cache_dir: Path | None, model_tag: str) -> LLMProvider:
    """Return the provider for one repeatability sample.

    Samples send the **identical** prompt (a genuine repeatability control): the
    Anthropic API exposes no seed parameter, so any cross-sample variation
    reflects only the provider's own sampling. When a cache dir is given, each
    sample gets its own subdirectory so the N draws stay distinct API calls yet
    reproducible on re-run; the underlying ``CachedLLMProvider`` scopes its key by
    ``model_tag`` (provider/model identity), so a reused cache dir cannot serve a
    different model's response.
    """
    if cache_dir is None:
        return base
    return CachedLLMProvider(base, cache_dir / f"sample-{sample_index}", model_tag=model_tag)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the cross-context continuity-handoff experiment (Experiment 2).")
    parser.add_argument("--scenario-file", type=Path, default=DEFAULT_SCENARIO_FILE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--run-name", default=None)
    parser.add_argument("--seeds", type=int, default=DEFAULT_SEEDS)
    parser.add_argument("--top-k", type=int, default=DEFAULT_TOP_K)
    parser.add_argument("--cache-dir", type=Path, default=None)
    args = parser.parse_args()

    run_dir = run_continuity_handoff_benchmark(
        scenario_file=args.scenario_file,
        output_root=args.output_dir,
        config=AppConfig.from_env(),
        run_name=args.run_name,
        seeds=args.seeds,
        top_k=args.top_k,
        cache_dir=args.cache_dir,
    )
    print(run_dir)
    return 0


def run_continuity_handoff_benchmark(
    *,
    scenario_file: Path,
    output_root: Path,
    config: AppConfig,
    run_name: str | None = None,
    answer_provider: LLMProvider | None = None,
    seeds: int = DEFAULT_SEEDS,
    top_k: int = DEFAULT_TOP_K,
    cache_dir: Path | None = None,
) -> Path:
    if seeds < 1:
        raise ValueError("seeds must be >= 1")
    scenarios = json.loads(scenario_file.read_text(encoding="utf-8"))

    if answer_provider is None:
        default_package = config.package_config(config.default_use_case)
        if not default_package.llm_provider or not default_package.model:
            raise ValueError(f"Default use case '{config.default_use_case}' is missing LLM package config")
        base_provider = build_llm_provider(config, provider_name=default_package.llm_provider, model=default_package.model)
    else:
        base_provider = answer_provider

    # Non-secret provider/model identity, scoped into the response cache key so a
    # reused cache dir cannot serve a different model's response.
    model_tag = f"{config.llm_provider_for_default_use_case or 'provider'}:{config.llm_model_for_default_use_case or 'model'}"

    run_id = run_name or _build_run_id(config, seeds)
    run_dir = output_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    results_path = run_dir / "results.jsonl"

    results: list[dict[str, Any]] = []
    with results_path.open("w", encoding="utf-8") as results_file:
        for scenario in scenarios:
            result = _run_scenario(
                scenario=scenario,
                config=config,
                base_provider=base_provider,
                seeds=seeds,
                top_k=top_k,
                cache_dir=cache_dir,
                model_tag=model_tag,
            )
            results.append(result)
            results_file.write(json.dumps(result) + "\n")

    summary = _build_summary(results=results, scenario_file=scenario_file, config=config, run_id=run_id, seeds=seeds, top_k=top_k)
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (run_dir / "report.md").write_text(_build_report(summary=summary, results=results), encoding="utf-8")
    return run_dir


def _run_scenario(
    *,
    scenario: dict[str, Any],
    config: AppConfig,
    base_provider: LLMProvider,
    seeds: int,
    top_k: int,
    cache_dir: Path | None,
    model_tag: str,
) -> dict[str, Any]:
    should_help = bool(scenario.get("should_memory_help", True))
    arm_context = _build_arm_contexts(scenario=scenario, config=config, top_k=top_k)

    # Orchestration-cost proxy: tokens a USER must route into the receiving
    # session per arm. The pull arm's raw context is pulled agent-side, so the
    # user only supplies the pointer+ask (the query text).
    orchestration_cost = {
        ARM_NO_MEMORY: 0,
        ARM_PULL_BACKED: _estimate_tokens(str((scenario.get("current_query") or {}).get("text", ""))),
        ARM_MANUAL_TRANSCRIPT: _estimate_tokens(arm_context[ARM_MANUAL_TRANSCRIPT]["user_supplied_text"]),
        ARM_MANUAL_SUMMARY: _estimate_tokens(arm_context[ARM_MANUAL_SUMMARY]["user_supplied_text"]),
    }

    # Per-arm, per-sample continuation + rubric. The rubric scorer is
    # deterministic; only generation is stochastic. Every sample sends the
    # identical prompt (repeatability control), so the observed spread reflects
    # the provider's own sampling — zero spread means it was deterministic here.
    per_arm_seed_scores: dict[str, list[int]] = {arm: [] for arm in ARMS}
    per_arm_seed_rubrics: dict[str, list[dict[str, Any]]] = {arm: [] for arm in ARMS}
    per_arm_seed_continuations: dict[str, list[dict[str, Any]]] = {arm: [] for arm in ARMS}
    per_seed_winners: list[str] = []

    for seed in range(seeds):
        provider = _sample_provider(base_provider, sample_index=seed, cache_dir=cache_dir, model_tag=model_tag)
        seed_rubrics: dict[str, dict[str, Any]] = {}
        for arm in ARMS:
            continuation = _generate_continuation(
                answer_provider=provider,
                scenario_id=scenario["scenario_id"],
                target_question=scenario["target_question"],
                current_thread_context=scenario.get("current_thread_context", []),
                memory_backed_results=arm_context[arm]["results"],
                branch=arm,
            )
            rubric = _score_continuation(
                continuation=continuation,
                expected_dimensions=scenario.get("expected_dimensions", {}),
                must_preserve=scenario.get("must_preserve", []),
                forbidden_terms=scenario.get("forbidden_terms", []),
            )
            per_arm_seed_scores[arm].append(int(rubric["total"]))
            per_arm_seed_rubrics[arm].append(rubric)
            per_arm_seed_continuations[arm].append(continuation)
            seed_rubrics[arm] = rubric
        per_seed_winners.append(_seed_winner(seed_rubrics, orchestration_cost))

    consensus_winner, winner_votes = _consensus(per_seed_winners)

    arm_summaries = {
        arm: {
            "mean_correctness": round(statistics.fmean(per_arm_seed_scores[arm]), 3),
            "correctness_spread": (round(statistics.pstdev(per_arm_seed_scores[arm]), 3) if seeds > 1 else 0.0),
            "min_correctness": min(per_arm_seed_scores[arm]),
            "max_correctness": max(per_arm_seed_scores[arm]),
            "per_seed_correctness": per_arm_seed_scores[arm],
            "orchestration_cost_tokens": orchestration_cost[arm],
            "overreach_any_seed": any(r["overreach"] for r in per_arm_seed_rubrics[arm]),
        }
        for arm in ARMS
    }

    # Pairwise consensus: pull vs each manual/no-memory baseline, using the
    # reused _compare_continuations verdict, with the explicit majority/tie
    # policy (same policy as the per-scenario consensus winner).
    pairwise = {}
    for other in (ARM_NO_MEMORY, ARM_MANUAL_TRANSCRIPT, ARM_MANUAL_SUMMARY):
        verdicts = [
            _compare_continuations(
                should_memory_help=should_help,
                baseline_rubric=per_arm_seed_rubrics[other][seed],
                memory_rubric=per_arm_seed_rubrics[ARM_PULL_BACKED][seed],
            )["winner"]
            for seed in range(seeds)
        ]
        # Map _compare_continuations vocabulary (memory_backed==pull, baseline==other).
        mapped = [{"memory_backed": ARM_PULL_BACKED, "baseline": other, "tie": "tie"}[v] for v in verdicts]
        consensus, _ = _majority(mapped)
        pairwise[f"pull_vs_{other}"] = {
            "per_seed": mapped,
            "consensus": consensus,
        }

    return {
        "scenario_id": scenario["scenario_id"],
        "scenario_family": scenario.get("scenario_family", "cross_context_handoff"),
        "description": scenario.get("description", ""),
        "should_memory_help": should_help,
        "seeds": seeds,
        "top_k": top_k,
        "pull_source_hit_count": arm_context[ARM_PULL_BACKED]["source_hit_count"],
        "pull_expansion_turn_count": arm_context[ARM_PULL_BACKED]["expansion_turn_count"],
        "pull_agent_roundtrips": arm_context[ARM_PULL_BACKED]["agent_roundtrips"],
        "arm_summaries": arm_summaries,
        "orchestration_cost_tokens": orchestration_cost,
        "per_seed_winners": per_seed_winners,
        "consensus_winner": consensus_winner,
        "winner_votes": winner_votes,
        "pairwise": pairwise,
        "arm_continuations": {arm: per_arm_seed_continuations[arm] for arm in ARMS},
    }


def _seed_winner(seed_rubrics: dict[str, dict[str, Any]], cost: dict[str, int]) -> str:
    """Winner for a single sample, computed identically for value and no-value
    scenarios so the no-value guard is FALSIFIABLE.

    Winner = the arm with the highest correctness among arms that did not
    overreach (drag in forbidden/stale content); ties are broken by LOWER
    user-orchestration cost (the experiment's point), then by a fixed arm order.
    Because ``no_memory`` has cost 0 it wins any tie it is part of — so a memory
    arm can only win by *strictly* exceeding it. In a no-value scenario, where
    the receiving thread is already sufficient, that means a memory arm winning
    is a real guard failure, not a foregone conclusion.
    """
    totals = {arm: int(seed_rubrics[arm]["total"]) for arm in ARMS}
    eligible = [arm for arm in ARMS if not seed_rubrics[arm]["overreach"]]
    if not eligible:
        return ARM_NO_MEMORY
    best_score = max(totals[arm] for arm in eligible)
    tied = [arm for arm in eligible if totals[arm] == best_score]
    return min(tied, key=lambda a: (cost[a], ARMS.index(a)))


def _majority(items: list[str]) -> tuple[str, dict[str, int]]:
    """Explicit majority policy: return the strict plurality winner, or the
    literal string ``"tie"`` when the top count is shared. Deterministic and
    order-independent (unlike ``Counter.most_common`` on ties)."""
    votes = Counter(items)
    if not votes:
        return "tie", {}
    top = max(votes.values())
    leaders = [value for value, count in votes.items() if count == top]
    winner = leaders[0] if len(leaders) == 1 else "tie"
    return winner, dict(votes)


def _consensus(per_seed_winners: list[str]) -> tuple[str, dict[str, int]]:
    return _majority(per_seed_winners)


def _build_arm_contexts(*, scenario: dict[str, Any], config: AppConfig, top_k: int) -> dict[str, dict[str, Any]]:
    prior_events = scenario.get("prior_events", [])
    current_query = dict(scenario.get("current_query") or {})
    container_ref = current_query.get("container_ref")

    # no_memory: nothing routed in.
    contexts: dict[str, dict[str, Any]] = {
        ARM_NO_MEMORY: {"results": [], "user_supplied_text": "", "source_hit_count": 0,
                        "expansion_turn_count": 0, "agent_roundtrips": 0},
    }

    # manual_transcript: the whole prior-session transcript, as source-shaped rows.
    transcript_results = [
        {
            "result_kind": "source_hit",
            "source_type": ev.get("source_type", "conversation_message"),
            "source_id": ev.get("source_id", ""),
            "excerpt": str(ev.get("content", "")),
        }
        for ev in prior_events
    ]
    transcript_text = "\n".join(str(ev.get("content", "")) for ev in prior_events)
    contexts[ARM_MANUAL_TRANSCRIPT] = {
        "results": transcript_results, "user_supplied_text": transcript_text,
        "source_hit_count": 0, "expansion_turn_count": 0, "agent_roundtrips": 0,
    }

    # manual_summary: a single human-authored summary row.
    summary_text = str(scenario.get("handoff_summary", ""))
    contexts[ARM_MANUAL_SUMMARY] = {
        "results": [{"result_kind": "source_hit", "source_type": "handoff_summary",
                     "source_id": scenario["scenario_id"], "excerpt": summary_text}],
        "user_supplied_text": summary_text, "source_hit_count": 0,
        "expansion_turn_count": 0, "agent_roundtrips": 0,
    }

    # pull_backed: source_only search + /source/{id}/context expansion, built
    # from the ACTUAL API response surface (redacted excerpts + neighbor turns).
    contexts[ARM_PULL_BACKED] = _build_pull_context(
        prior_events=prior_events, current_query=current_query,
        container_ref=container_ref, config=config, top_k=top_k,
    )
    return contexts


def _build_pull_context(
    *,
    prior_events: list[dict[str, Any]],
    current_query: dict[str, Any],
    container_ref: str | None,
    config: AppConfig,
    top_k: int,
) -> dict[str, Any]:
    with TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        database_url = f"sqlite:///{Path(temp_dir) / 'continuity-handoff.db'}"
        vector_index_config = replace(config.vector_index, index_path=str(Path(temp_dir) / "vector.index"))
        scenario_config = replace(
            config,
            sqlite_url=database_url,
            default_use_case="agent_conversation_memory",
            vector_index=vector_index_config,
        )
        with TestClient(create_app(scenario_config)) as client:
            for event in prior_events:
                resp = client.post("/items", json=[_with_private_default(event)])
                resp.raise_for_status()
            client.app.state.pallium_service.drain_processing_queue(worker_id="continuity-handoff-runner")

            # Pointer+pull step 1: source-only history search (the shipped P1 primitive).
            query_request = _with_private_default({**current_query, "source_only": True})
            query_request.setdefault("limit", 6)
            search_resp = client.post("/query", json=query_request)
            search_resp.raise_for_status()
            search_results = search_resp.json().get("results", [])
            source_hits = [r for r in search_results if r.get("result_kind") == "source_hit" and r.get("source_item_id")]

            agent_roundtrips = 1  # the source_only search
            results: list[dict[str, Any]] = []
            expansion_turn_count = 0
            top_hits = source_hits[:top_k]
            # De-duplicate across ranked hits and their overlapping expansion
            # windows: each raw turn is included at most once, so the pull input
            # does not repeat evidence (which would inflate the turn count and
            # unfairly differ from the single-copy manual transcript). Seed the
            # seen-set with ALL ranked hit ids up front, so a ranked hit that
            # also appears in another hit's window is never re-added as an
            # expansion turn.
            seen_item_ids: set[str] = {h["source_item_id"] for h in top_hits if h.get("source_item_id")}
            for hit in top_hits:
                # Keep the ranked source hit itself (redacted excerpt as returned).
                results.append({
                    "result_kind": "source_hit",
                    "source_item_id": hit.get("source_item_id"),
                    "source_type": hit.get("source_type"),
                    "source_id": hit.get("source_id"),
                    "excerpt": hit.get("excerpt", ""),
                    "raw_rank": hit.get("raw_rank"),
                })
            for hit in top_hits:
                # Pointer+pull step 2: expand the neighborhood on demand.
                params = {"before": 2, "after": 2}
                if container_ref:
                    params["container_ref"] = container_ref
                ctx_resp = client.get(f"/source/{hit['source_item_id']}/context", params=params)
                agent_roundtrips += 1
                if ctx_resp.status_code != 200:
                    continue
                for item in ctx_resp.json().get("items", []):
                    item_id = item.get("source_item_id")
                    if item.get("is_anchor") or not item_id or item_id in seen_item_ids:
                        continue  # anchor, unidentifiable, or already added
                    seen_item_ids.add(item_id)
                    expansion_turn_count += 1
                    results.append({
                        "result_kind": "source_hit",
                        "source_item_id": item_id,
                        "source_type": item.get("source_type"),
                        "source_id": item.get("source_id"),
                        "excerpt": item.get("content", ""),
                    })
            engine = getattr(client.app.state.pallium_service._storage, "_engine", None)
            if engine is not None:
                engine.dispose()

    return {
        "results": results,
        "user_supplied_text": str(current_query.get("text", "")),
        "source_hit_count": len(source_hits),
        "expansion_turn_count": expansion_turn_count,
        "agent_roundtrips": agent_roundtrips,
    }


def _build_summary(
    *, results: list[dict[str, Any]], scenario_file: Path, config: AppConfig, run_id: str, seeds: int, top_k: int
) -> dict[str, Any]:
    value_rows = [r for r in results if r["should_memory_help"]]

    arm_means: dict[str, float] = {}
    arm_spread: dict[str, float] = {}
    arm_cost: dict[str, float] = {}
    rows = value_rows or results  # same row set for correctness AND cost aggregates
    for arm in ARMS:
        arm_means[arm] = round(statistics.fmean([r["arm_summaries"][arm]["mean_correctness"] for r in rows]), 3) if rows else 0.0
        arm_spread[arm] = round(statistics.fmean([r["arm_summaries"][arm]["correctness_spread"] for r in rows]), 3) if rows else 0.0
        arm_cost[arm] = round(statistics.fmean([r["orchestration_cost_tokens"][arm] for r in rows]), 3) if rows else 0.0

    consensus_counts = Counter(r["consensus_winner"] for r in value_rows)
    pull_vs = {other: Counter() for other in (ARM_NO_MEMORY, ARM_MANUAL_TRANSCRIPT, ARM_MANUAL_SUMMARY)}
    for r in value_rows:
        for other in pull_vs:
            pull_vs[other][r["pairwise"][f"pull_vs_{other}"]["consensus"]] += 1

    # Headline predicates, matched exactly to the wording used below:
    #  - "at least as correct as the manual baselines" = pull mean >= manual mean
    #    (no tolerance slack).
    #  - "strictly lower cost" = pull cost strictly below EACH manual arm.
    manual_mean = statistics.fmean([arm_means[a] for a in MANUAL_ARMS]) if rows else 0.0
    pull_mean = arm_means[ARM_PULL_BACKED]
    pull_preserves_correctness = pull_mean + 1e-9 >= manual_mean
    pull_strictly_cheaper_than_manual = all(arm_cost[ARM_PULL_BACKED] < arm_cost[a] for a in MANUAL_ARMS)

    return {
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "experiment": "cross_context_work_continuity_handoff",
        "scenario_file": str(scenario_file),
        "provider": config.llm_provider_for_default_use_case,
        "model": config.llm_model_for_default_use_case,
        "seeds": seeds,
        "top_k": top_k,
        "scenarios_total": len(results),
        "value_scenarios": len(value_rows),
        "arms": list(ARMS),
        "arm_mean_correctness": arm_means,
        "arm_correctness_spread": arm_spread,
        "arm_mean_orchestration_cost_tokens": arm_cost,
        "pull_mean_correctness": round(pull_mean, 3),
        "manual_mean_correctness": round(manual_mean, 3),
        "consensus_winner_counts": dict(consensus_counts),
        "pull_vs_baselines_consensus": {other: dict(counts) for other, counts in pull_vs.items()},
        "pull_preserves_manual_correctness": bool(pull_preserves_correctness),
        "pull_strictly_cheaper_than_manual": bool(pull_strictly_cheaper_than_manual),
        "headline": _headline(
            preserves=pull_preserves_correctness,
            cheaper=pull_strictly_cheaper_than_manual,
            pull_mean=pull_mean,
            manual_mean=manual_mean,
        ),
    }


def _headline(*, preserves: bool, cheaper: bool, pull_mean: float, manual_mean: float) -> str:
    corr = f"(pull mean {pull_mean:.2f} vs manual mean {manual_mean:.2f})"
    if preserves and cheaper:
        return (f"Pointer+pull was at least as correct as the manual baselines {corr} at strictly lower "
                f"user-orchestration cost on the authored scenarios.")
    if preserves and not cheaper:
        return f"Pointer+pull was at least as correct as the manual baselines {corr} but NOT strictly cheaper on user-orchestration cost."
    if not preserves and cheaper:
        return f"Pointer+pull was strictly cheaper on user-orchestration cost but LESS correct than the manual baselines {corr}."
    return f"Pointer+pull was neither at least as correct as the manual baselines {corr} nor strictly cheaper."


def _build_report(*, summary: dict[str, Any], results: list[dict[str, Any]]) -> str:
    lines = [
        "# Cross-Context Work-Continuity Handoff Experiment (Experiment 2)",
        "",
        f"Run ID: `{summary['run_id']}`",
        f"Provider/model: `{summary['provider']}` / `{summary['model']}`",
        f"Seeds: {summary['seeds']} | top-K pull hits: {summary['top_k']}",
        "",
        "## Arms",
        "",
        "- `no_memory` — current-thread context only.",
        "- `pull_backed` — source_only search + /source/{id}/context expansion (Pallium P1).",
        "- `manual_transcript` — full prior transcript pasted in.",
        "- `manual_summary` — human-authored summary pasted in.",
        "",
        "## Aggregate (value scenarios)",
        "",
        f"- scenarios: {summary['scenarios_total']} ({summary['value_scenarios']} value)",
        "",
        "| Arm | Mean correctness (± spread) | Mean orchestration cost (tokens) |",
        "|---|---|---|",
    ]
    for arm in summary["arms"]:
        mean = summary["arm_mean_correctness"][arm]
        spread = summary["arm_correctness_spread"][arm]
        lines.append(f"| `{arm}` | {mean:.2f} ± {spread:.2f} | {summary['arm_mean_orchestration_cost_tokens'][arm]} |")
    lines.extend([
        "",
        f"- consensus winner counts: {summary['consensus_winner_counts']}",
        f"- pull vs baselines (consensus): {summary['pull_vs_baselines_consensus']}",
        f"- pull at least as correct as manual: {summary['pull_preserves_manual_correctness']}",
        f"- pull strictly cheaper than manual: {summary['pull_strictly_cheaper_than_manual']}",
        "",
        f"**Headline:** {summary['headline']}",
        "",
        "## Per-Scenario",
        "",
    ])
    for r in results:
        arms = r["arm_summaries"]
        lines.append(
            f"- `{r['scenario_id']}` (value={r['should_memory_help']}): winner `{r['consensus_winner']}` "
            f"{r['winner_votes']}; pull hits={r['pull_source_hit_count']} expand={r['pull_expansion_turn_count']} "
            f"roundtrips={r['pull_agent_roundtrips']}; "
            f"correctness no_mem={arms[ARM_NO_MEMORY]['mean_correctness']}±{arms[ARM_NO_MEMORY]['correctness_spread']} "
            f"pull={arms[ARM_PULL_BACKED]['mean_correctness']}±{arms[ARM_PULL_BACKED]['correctness_spread']} "
            f"transcript={arms[ARM_MANUAL_TRANSCRIPT]['mean_correctness']}±{arms[ARM_MANUAL_TRANSCRIPT]['correctness_spread']} "
            f"summary={arms[ARM_MANUAL_SUMMARY]['mean_correctness']}±{arms[ARM_MANUAL_SUMMARY]['correctness_spread']}"
        )
    return "\n".join(lines) + "\n"


def _build_run_id(config: AppConfig, seeds: int) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    provider = (config.llm_provider_for_default_use_case or "provider").replace("_", "-")
    model = (config.llm_model_for_default_use_case or "model").replace("/", "-").replace(".", "-")
    return f"continuity-handoff__{provider}__{model}__seeds{seeds}__{timestamp}"


if __name__ == "__main__":
    raise SystemExit(main())
