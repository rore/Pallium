"""History-pull decision harness (non-circular Experiment-1 shaped data).

An LLM agent (``evals.history_pull_decision.agent.DecisionAgent``) is given the
history-search + source-expansion tools and DECIDES ON ITS OWN, per scenario,
whether to pull prior history. Agent-chosen pulls flow through the REAL service
(``POST /query {source_only, agent_pull}`` + ``GET /source/{id}/context``) so the
historical-lookup reuse-funnel events persist naturally. The persisted events are
then consumed by the existing rollup + reuse-ladder judge (imported as libraries,
never reimplemented) to produce the reuse rungs with kappa + Wilson.

Two run paths, mirroring how the judge gates LLM cost:
  * default (real provider): the decision agent uses the configured provider
    (``AppConfig.from_env`` → ``build_eval_providers``); the reuse judge is run
    separately (``python -m evals.historical_lookup_judge``) over the scratch DB.
  * ``--dry-run``: a deterministic scripted stub drives a full search+expand
    chain with NO network, for CI self-testing.

The SERVICE's own LLM (memory extraction at ingest) is always a stub: source-only
retrieval is extraction-independent (it ranks raw turns), so stubbing it does not
touch the measured path — only the agent's pull DECISIONS and the reuse JUDGE use
the real LLM. Everything runs in-process via ``fastapi.testclient.TestClient``
against a disposable scratch SQLite DB in a temp dir; no port is bound, so the
live service/DB is untouchable by construction.

Metrics emitted here are the deterministic BEHAVIOURAL layer (lookup rate,
unprompted-pull rate, lookup→non-empty-result); the useful-result rate and the
three reuse rungs come from the judge over these same persisted events. A
simulated rate is a PROXY for, and cannot substitute for, the live Phase-1 gate
(design 015, decision-point 1).
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from evals.history_pull_decision.agent import DecisionAgent, ScriptedDecisionProvider
from providers.llm.base import LLMProvider, LLMProviderError

_SCENARIOS_PATH = Path(__file__).resolve().parent / "scenarios.json"
_VISIBILITY = "private"


# ---------------------------------------------------------------------------
# Scenario model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Scenario:
    id: str
    user_directed: bool
    opportunity: bool
    prior_turns: list[dict[str, str]]
    current_task: str


def load_scenarios(path: Path | str = _SCENARIOS_PATH) -> list[Scenario]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    out: list[Scenario] = []
    for raw in data["scenarios"]:
        out.append(
            Scenario(
                id=str(raw["id"]),
                user_directed=bool(raw["user_directed"]),
                opportunity=bool(raw["opportunity"]),
                prior_turns=list(raw.get("prior_turns", [])),
                current_task=str(raw["current_task"]),
            )
        )
    return out


# ---------------------------------------------------------------------------
# In-process service backend (scratch DB, no bound port)
# ---------------------------------------------------------------------------


class InProcessService:
    """Wraps a ``TestClient`` over a scratch DB with a stubbed service LLM.

    Never binds a network port; the live service on :19836 is unreachable from
    here by construction.
    """

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        # Build the app with a stub extraction LLM (patch the module global the
        # same way tests/config_helpers does). Import lazily so importing this
        # module never triggers app construction.
        import app.dependencies as deps
        from tests.stub_providers import TieredMemorySemanticProvider
        from tests.config_helpers import build_llm_test_config
        from app.main import create_app
        from fastapi.testclient import TestClient

        self._original_build = deps.build_llm_provider
        deps.build_llm_provider = lambda config, **_: TieredMemorySemanticProvider()
        self._deps = deps
        config = build_llm_test_config(
            default_use_case="agent_conversation_memory",
            sqlite_url=f"sqlite:///{db_path}",
        )
        self._client = TestClient(create_app(config))
        self._client.__enter__()

    @property
    def db_path(self) -> Path:
        return self._db_path

    def _service(self):
        return self._client.app.state.pallium_service

    def ingest(self, *, container_ref: str, thread_ref: str, role: str, content: str) -> str:
        import uuid

        source_type = "chat_message" if role == "user" else "assistant_artifact"
        artifact_kind = "message" if role == "user" else "assistant_output"
        resp = self._client.post(
            "/items",
            json=[
                {
                    "source_type": source_type,
                    "source_id": f"hpd-{uuid.uuid4().hex[:12]}",
                    "content_type": "text/plain",
                    "content": content,
                    "artifact_kind": artifact_kind,
                    "role": role,
                    "container_ref": container_ref,
                    "thread_ref": thread_ref,
                    "visibility": _VISIBILITY,
                }
            ],
        )
        assert resp.status_code == 200, resp.text
        return resp.json()[0]["source_item_id"]

    def drain(self) -> None:
        self._service().drain_processing_queue(worker_id="hpd-harness")

    def search_history(self, *, query: str, container_ref: str, thread_ref: str, limit: int = 5) -> dict[str, Any]:
        resp = self._client.post(
            "/query",
            json={
                "text": query,
                "container_ref": container_ref,
                "thread_ref": thread_ref,
                "visibility": _VISIBILITY,
                "limit": limit,
                "source_only": True,
                "trigger_origin": "agent_pull",
            },
        )
        assert resp.status_code == 200, resp.text
        return resp.json()

    def expand_source(self, *, source_item_id: str, container_ref: str, parent_lookup_id: str) -> dict[str, Any]:
        resp = self._client.get(
            f"/source/{source_item_id}/context",
            params={"container_ref": container_ref, "parent_lookup_id": parent_lookup_id},
        )
        assert resp.status_code == 200, resp.text
        return resp.json()

    def close(self) -> None:
        try:
            self._client.__exit__(None, None, None)
        finally:
            # Dispose the storage + metrics engines so Windows releases the DB
            # file handle before a separate judge process (or tmp cleanup) opens
            # it. Mirrors scripts/live_funnel_smoke.dispose_app_engines.
            app = getattr(self._client, "app", None)
            state = getattr(app, "state", None)
            try:
                storage = self._service()._storage
                engine = getattr(storage, "_engine", None)
                if engine is not None:
                    engine.dispose()
            except Exception:  # noqa: BLE001 - best-effort teardown
                pass
            metrics_store = getattr(state, "metrics_store", None)
            factory = getattr(metrics_store, "_session_factory", None)
            if factory is not None:
                try:
                    with factory() as s:
                        s.get_bind().dispose()
                except Exception:  # noqa: BLE001 - best-effort teardown
                    pass
            self._deps.build_llm_provider = self._original_build


# ---------------------------------------------------------------------------
# Trial record + orchestration
# ---------------------------------------------------------------------------


@dataclass
class Trial:
    scenario_id: str
    seed: int
    user_directed: bool
    opportunity: bool
    searched: bool
    query: str
    lookup_event_id: str | None
    n_source_hits: int
    expanded: bool
    answer_preview: str
    error: str | None = None
    note: str | None = None


def _run_trial(
    service: InProcessService,
    agent: DecisionAgent,
    scenario: Scenario,
    seed: int,
) -> Trial:
    container = f"chat:hpd:{scenario.id}"
    session_thread = f"{container}:session:s{seed}"

    # The current session's opening user turn (judge CONTEXT BEFORE the lookup).
    service.ingest(container_ref=container, thread_ref=session_thread, role="user", content=scenario.current_task)

    decision = agent.decide_search(scenario_id=scenario.id, task=scenario.current_task, seed=seed)
    lookup_event_id: str | None = None
    source_hits: list[dict[str, Any]] = []
    expanded = False
    answer = ""
    note: str | None = None

    if decision.search:
        result = service.search_history(query=decision.query, container_ref=container, thread_ref=session_thread)
        lookup_event_id = result.get("lookup_event_id")
        source_hits = [r for r in result.get("results", []) if r.get("result_kind") == "source_hit"]
        try:
            after = agent.decide_after_results(
                scenario_id=scenario.id, task=scenario.current_task, results=source_hits, seed=seed
            )
            context_parts = [str(h.get("excerpt") or "") for h in source_hits]
            if after.expand and after.expand_index is not None and after.expand_index < len(source_hits) and lookup_event_id:
                anchor_id = source_hits[after.expand_index]["source_item_id"]
                ctx = service.expand_source(
                    source_item_id=anchor_id, container_ref=container, parent_lookup_id=lookup_event_id
                )
                expanded = True
                context_parts.extend(str(i.get("content") or "") for i in ctx.get("items", []))
            # Guarantee a real, history-incorporating work turn: use the after-
            # results answer only when it is non-empty AND no expansion happened;
            # otherwise finalize with the (expanded) retrieved context.
            answer = after.answer
            if expanded or not answer:
                answer = agent.finalize_answer(
                    scenario_id=scenario.id, task=scenario.current_task,
                    context_text="\n".join(p for p in context_parts if p)[:4000], seed=seed,
                )
        except LLMProviderError as exc:
            # Post-decision failure: the pull decision (searched=True + the
            # persisted lookup) is already valid and counted; only the answer
            # generation failed. Record a soft note, not a hard error.
            note = f"after_results_failed: {type(exc).__name__}"
    else:
        # No-search completion: the agent does the task from its own knowledge.
        # Persisting a REAL answer (not a placeholder) makes a no-pull session
        # legitimately substantive — the agent chose not to pull, but still did
        # the work — so it counts in the eligibility denominator correctly.
        try:
            answer = agent.complete_without_history(
                scenario_id=scenario.id, task=scenario.current_task, seed=seed
            )
        except LLMProviderError as exc:
            note = f"completion_failed: {type(exc).__name__}"

    # Ingest the assistant work turn ONLY when a real answer was produced. On a
    # post-decision failure we deliberately do NOT persist a placeholder turn:
    # that would make a session look substantive without real work and pollute
    # the eligibility denominator. The pull decision itself is still recorded.
    if answer:
        service.ingest(container_ref=container, thread_ref=session_thread, role="assistant", content=answer)

    return Trial(
        scenario_id=scenario.id,
        seed=seed,
        user_directed=scenario.user_directed,
        opportunity=scenario.opportunity,
        searched=decision.search,
        query=decision.query,
        lookup_event_id=lookup_event_id,
        n_source_hits=len(source_hits),
        expanded=expanded,
        answer_preview=answer[:160],
        note=note,
    )


def run_harness(
    *,
    service: InProcessService,
    agent: DecisionAgent,
    scenarios: list[Scenario],
    seeds: list[int],
) -> list[Trial]:
    """Seed each scenario's prior turns once, then run every (scenario, seed)
    trial. Distinct session thread per seed → distinct eligible session."""
    trials: list[Trial] = []
    for scenario in scenarios:
        container = f"chat:hpd:{scenario.id}"
        history_thread = f"{container}:history"
        for turn in scenario.prior_turns:
            service.ingest(
                container_ref=container,
                thread_ref=history_thread,
                role=str(turn.get("role", "user")),
                content=str(turn.get("content", "")),
            )
        service.drain()  # mark prior turns processed → they count as prior-indexed
        for seed in seeds:
            try:
                trials.append(_run_trial(service, agent, scenario, seed))
            except (LLMProviderError, AssertionError) as exc:
                trials.append(
                    Trial(
                        scenario_id=scenario.id, seed=seed, user_directed=scenario.user_directed,
                        opportunity=scenario.opportunity, searched=False, query="",
                        lookup_event_id=None, n_source_hits=0, expanded=False,
                        answer_preview="", error=f"{type(exc).__name__}: {str(exc)[:200]}",
                    )
                )
        service.drain()  # process the session turns too
    return trials


# ---------------------------------------------------------------------------
# Behavioural metrics (deterministic given the agent's decisions)
# ---------------------------------------------------------------------------


def compute_behavioural_metrics(trials: list[Trial]) -> dict[str, Any]:
    def rate(num: int, den: int) -> float | None:
        return (num / den) if den else None

    ok = [t for t in trials if t.error is None]
    n = len(ok)
    searched = [t for t in ok if t.searched]
    undirected = [t for t in ok if not t.user_directed]
    undirected_searched = [t for t in undirected if t.searched]
    directed = [t for t in ok if t.user_directed]
    directed_searched = [t for t in directed if t.searched]
    opportunity = [t for t in ok if t.opportunity]
    opportunity_searched = [t for t in opportunity if t.searched]
    no_opportunity = [t for t in ok if not t.opportunity]
    no_opp_searched = [t for t in no_opportunity if t.searched]
    searched_nonempty = [t for t in searched if t.n_source_hits > 0]

    return {
        "n_trials": len(trials),
        "n_trials_ok": n,
        "n_errors": len(trials) - n,
        "n_soft_notes": sum(1 for t in ok if t.note),
        "lookup_rate": rate(len(searched), n),
        "unprompted_pull_rate": rate(len(undirected_searched), len(undirected)),
        "user_directed_pull_rate": rate(len(directed_searched), len(directed)),
        "opportunity_pull_rate": rate(len(opportunity_searched), len(opportunity)),
        "no_opportunity_pull_rate": rate(len(no_opp_searched), len(no_opportunity)),
        "lookup_to_nonempty_result_rate": rate(len(searched_nonempty), len(searched)),
        "expand_rate_of_lookups": rate(sum(1 for t in searched if t.expanded), len(searched)),
        "counts": {
            "searched": len(searched),
            "undirected": len(undirected),
            "undirected_searched": len(undirected_searched),
            "directed": len(directed),
            "opportunity": len(opportunity),
            "no_opportunity": len(no_opportunity),
        },
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_agent_provider(*, dry_run: bool, cache_dir: Path | None, no_eval_cache: bool) -> LLMProvider:
    if dry_run:
        return ScriptedDecisionProvider()
    from app.config import AppConfig
    from evals.eval_common import build_eval_providers

    config = AppConfig.from_env()
    main_provider, _judge = build_eval_providers(
        config, cache_dir=cache_dir, no_eval_cache=no_eval_cache
    )
    return main_provider


def _parse_seeds(raw: str) -> list[int]:
    seeds = [int(p.strip()) for p in raw.split(",") if p.strip()]
    if not seeds:
        raise argparse.ArgumentTypeError("at least one seed required")
    if len(set(seeds)) != len(seeds):
        raise argparse.ArgumentTypeError("seeds must be distinct")
    return seeds


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--dry-run", action="store_true", help="Deterministic scripted stub; no network.")
    parser.add_argument("--seeds", type=_parse_seeds, default=[0, 1, 2], help="Comma-separated agent seeds (default 0,1,2).")
    parser.add_argument("--scenarios", type=Path, default=_SCENARIOS_PATH)
    parser.add_argument("--db", type=Path, default=None, help="Scratch DB path (default: temp dir). Rejected if it already exists unless --overwrite.")
    parser.add_argument("--overwrite", action="store_true", help="Delete an existing --db (and its -wal/-shm/-journal sidecars) before starting, so reruns do not accumulate events.")
    parser.add_argument(
        "--eligibility-n", type=int, default=1,
        help="Prior-indexed-turns threshold for an eligible session. Default 1 "
        "(these scenarios seed few prior turns; the judge/rollup default of 50 "
        "would yield 0 eligible). Recorded and echoed into the judge command.",
    )
    parser.add_argument("--cache-dir", type=Path, default=None, help="LLM cache dir (real runs).")
    parser.add_argument("--no-eval-cache", action="store_true")
    parser.add_argument("--output", type=Path, default=None, help="Write the run JSON here.")
    parser.add_argument("--keep-db", action="store_true", help="Keep the scratch DB (needed to run the judge over it).")
    args = parser.parse_args(argv)

    scenarios = load_scenarios(args.scenarios)
    seeds = list(args.seeds)
    eligibility_n = args.eligibility_n

    tmpdir: tempfile.TemporaryDirectory | None = None
    if args.db is not None:
        db_path = args.db
        sidecars = [Path(str(db_path) + s) for s in ("", "-wal", "-shm", "-journal")]
        if db_path.exists():
            if not args.overwrite:
                parser.error(
                    f"{db_path} already exists; reusing it would mix events across runs. "
                    "Pass --overwrite to replace it (removes the db + -wal/-shm/-journal), "
                    "or choose a fresh --db path."
                )
            for p in sidecars:
                if p.exists():
                    p.unlink()
        db_path.parent.mkdir(parents=True, exist_ok=True)
    else:
        tmpdir = tempfile.TemporaryDirectory(prefix="hpd-scratch-", ignore_cleanup_errors=True)
        db_path = Path(tmpdir.name) / "hpd.db"

    provider = _build_agent_provider(dry_run=args.dry_run, cache_dir=args.cache_dir, no_eval_cache=args.no_eval_cache)
    agent = DecisionAgent(provider)

    service = InProcessService(db_path)
    try:
        trials = run_harness(service=service, agent=agent, scenarios=scenarios, seeds=seeds)
    finally:
        service.close()

    metrics = compute_behavioural_metrics(trials)
    report = {
        "harness": "history_pull_decision",
        "mode": "dry-run" if args.dry_run else "real",
        "seeds": seeds,
        "eligibility_n": eligibility_n,
        "n_scenarios": len(scenarios),
        "scratch_db": str(db_path),
        "behavioural_metrics": metrics,
        "trials": [asdict(t) for t in trials],
        "honesty": (
            "Behavioural metrics only. useful-result rate + reuse rungs come from "
            "the reuse-ladder judge over these persisted events. A simulated rate "
            "is a proxy, not the live Phase-1 gate."
        ),
    }
    serialised = json.dumps(report, indent=2, sort_keys=True)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialised, encoding="utf-8")
        print(f"Wrote run report -> {args.output}", file=sys.stderr)

    print("=== History-Pull Decision Harness ===")
    print(f"mode={report['mode']} seeds={seeds} scenarios={len(scenarios)} eligibility_n={eligibility_n}")
    m = metrics
    print(f"  lookup_rate                     = {m['lookup_rate']}")
    print(f"  unprompted_pull_rate            = {m['unprompted_pull_rate']}")
    print(f"  opportunity_pull_rate           = {m['opportunity_pull_rate']}")
    print(f"  no_opportunity_pull_rate        = {m['no_opportunity_pull_rate']}")
    print(f"  lookup_to_nonempty_result_rate  = {m['lookup_to_nonempty_result_rate']}")
    print(f"  errors                          = {m['n_errors']}")
    print(f"  soft_notes (post-decision)      = {m['n_soft_notes']}")
    if args.keep_db or args.db is not None:
        seeds_csv = ",".join(str(s) for s in seeds)
        print(f"  scratch DB (kept)               = {db_path}")
        print(
            f"  run the judge:  python -m evals.historical_lookup_judge "
            f"--db {db_path} --seeds {seeds_csv} --eligibility-n {eligibility_n}"
        )
    elif tmpdir is not None:
        tmpdir.cleanup()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
