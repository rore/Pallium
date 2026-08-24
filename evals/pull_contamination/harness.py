"""Pull-contamination filtering harness (deterministic A/B outcomes, no judge).

The distinctive hypothesis of the vNext pull model is not only *whether* an agent
pulls prior history, but whether — once plausible-but-WRONG history is in front of
it — the agent FILTERS that history out or gets CONTAMINATED by it. This harness
isolates the filtering question: per scenario it **forces** the condition's
history into the agent's context (it does NOT rely on a pull decision), then
measures the final answer's A-vs-B choice deterministically.

Three conditions per scenario:
  1. ``no_history``            — baseline; no history in context.
  2. ``relevant_history``      — positive control; history supports the correct
                                 approach A.
  3. ``contaminating_history`` — the test; history plausibly argues the wrong
                                 approach B.

Each scenario defines an objectively correct approach A determinable from the
task text ALONE (so the no-history baseline should choose A), and a ``marker_a`` /
``marker_b`` regex pair. The PRIMARY signal is a deterministic marker scan of the
final answer (``classify_answer``): contains A-marker and not B → chose_A; B and
not A → chose_B; else ambiguous. No LLM judge is used here — an ambiguous-only
judge may be layered on later, deliberately out of scope for this harness.

The forced history is presented to the agent the SAME way a real pull result would
be — rendered through ``evals.history_pull_decision.agent._render_results`` and a
FINALIZE/AFTER-style system prompt — so the only variable across conditions is
WHICH history is present, not how it is framed.

Run paths mirror the history-pull decision harness:
  * default (real provider): the answering agent uses the configured provider
    (``AppConfig.from_env`` → ``build_eval_providers``).
  * ``--dry-run``: a deterministic scripted stub, no network, for CI self-testing.

No service, DB, or retrieval is involved: history is forced directly into the
prompt, so production surfaces are untouched by construction.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from app.mcp.server import _compact_history, _json_text
from evals.history_pull_decision.agent import ScriptedDecisionProvider, _render_results
from evals.historical_lookup_measurement import _wilson_95
from providers.llm.base import LLMProvider, LLMProviderError

_SCENARIOS_PATH = Path(__file__).resolve().parent / "scenarios.json"

CONDITION_NO_HISTORY = "no_history"
CONDITION_RELEVANT = "relevant_history"
CONDITION_CONTAMINATING = "contaminating_history"
CONDITIONS = (CONDITION_NO_HISTORY, CONDITION_RELEVANT, CONDITION_CONTAMINATING)

#: Delimiter that introduces the forced history in the with-history user prompt.
#: The scripted dry-run stub keys off it to distinguish the two prompt shapes.
HISTORY_DELIMITER = "Retrieved prior work (from your own earlier sessions):\n"


# ---------------------------------------------------------------------------
# Prompts + schema (FINALIZE/AFTER style, mirroring history_pull_decision.agent)
# ---------------------------------------------------------------------------

NO_HISTORY_SYSTEM_PROMPT = """\
You are a software engineering assistant working on a task. You have NO project
history to draw on — answer from the task requirements and standard best practice
alone. Keep it brief: a few sentences in prose, no long code listing. You MUST
state the specific value or approach you recommend explicitly (e.g. the exact
number, unit, algorithm, or convention). Return exactly the JSON schema.
"""

WITH_HISTORY_SYSTEM_PROMPT = """\
You are a software engineering assistant working on a task. You searched your
prior work and retrieved the excerpt(s) below. Use the retrieved context where it
is genuinely relevant to THIS task, and IGNORE it where it is not — decide for
yourself; retrieved history can be about a different subtask, outdated, or from a
different project with different conventions. Write your final answer to the task.
Keep it brief: a few sentences in prose, no long code listing. You MUST state the
specific value or approach you recommend explicitly (e.g. the exact number, unit,
algorithm, or convention). Return exactly the JSON schema.
"""

ANSWER_SCHEMA = '{"answer":"string"}'


# ---------------------------------------------------------------------------
# Scenario model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Scenario:
    id: str
    taxonomy_type: str
    current_task: str
    marker_a: str
    marker_b: str
    relevant_history: str
    contaminating_history: str


def load_scenarios(path: Path | str = _SCENARIOS_PATH) -> list[Scenario]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    out: list[Scenario] = []
    for raw in data["scenarios"]:
        out.append(
            Scenario(
                id=str(raw["id"]),
                taxonomy_type=str(raw["taxonomy_type"]),
                current_task=str(raw["current_task"]),
                marker_a=str(raw["marker_a"]),
                marker_b=str(raw["marker_b"]),
                relevant_history=str(raw["relevant_history"]),
                contaminating_history=str(raw["contaminating_history"]),
            )
        )
    return out


def load_case(path: Path | str = _SCENARIOS_PATH) -> str:
    """The scenario file's ``case`` label ('explicit-task' / 'ambiguous-task').

    Controls only reporting framing (the ``honesty`` note + a printed line), not
    the harness logic. Defaults to 'explicit-task' for the original scenarios.json
    which predates the field.
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return str(data.get("case", "explicit-task"))


# ---------------------------------------------------------------------------
# Deterministic A/B detection (the PRIMARY signal)
# ---------------------------------------------------------------------------


def classify_answer(answer: str, marker_a: str, marker_b: str) -> str:
    """Classify a final answer as ``chose_A`` / ``chose_B`` / ``ambiguous``.

    Markers are case-insensitive regular expressions. Contains A and not B →
    chose_A; contains B and not A → chose_B; contains both or neither →
    ambiguous. This marker scan is the primary experiment signal.
    """
    has_a = re.search(marker_a, answer, re.IGNORECASE) is not None
    has_b = re.search(marker_b, answer, re.IGNORECASE) is not None
    if has_a and not has_b:
        return "chose_A"
    if has_b and not has_a:
        return "chose_B"
    return "ambiguous"


def classify_answer_leading(answer: str, marker_a: str, marker_b: str) -> str:
    """Decision-first classifier: whichever marker appears FIRST wins.

    On ambiguous/judgment tasks the strict ``classify_answer`` (both markers →
    ambiguous) systematically UNDER-reports the choice, because the agent names
    the rejected option to justify its pick ("UUIDv7 — auto-increment would
    bottleneck..."). Real answers are decision-first (the choice leads the
    sentence), so the earliest marker match is the actual decision. Only one
    marker → that one; neither → ambiguous. This is the primary detector for the
    ambiguous-task case; the strict one is retained as a conservative cross-check.

    Caveat: mis-scores an answer that leads with the rejected option ("Unlike
    bcrypt, use Argon2id"); inspection of the real run showed the agent leads with
    its choice, and both detectors are reported so the divergence is visible.
    """
    ma = re.search(marker_a, answer, re.IGNORECASE)
    mb = re.search(marker_b, answer, re.IGNORECASE)
    if ma and mb:
        return "chose_A" if ma.start() < mb.start() else "chose_B"
    if ma:
        return "chose_A"
    if mb:
        return "chose_B"
    return "ambiguous"


_STOPWORDS = frozenset(
    {
        "about", "after", "again", "against", "along", "another", "because",
        "before", "being", "between", "could", "every", "other", "should",
        "since", "state", "still", "their", "there", "these", "thing", "those",
        "through", "under", "until", "using", "value", "which", "while", "would",
        "across", "among", "avoid", "based", "cause", "small", "keeps", "moved",
        "later", "means", "terms",
    }
)


def _distinctive_tokens(text: str) -> set[str]:
    """Lowercased alphanumeric tokens of length >= 5 that are not stopwords."""
    return {
        t
        for t in re.findall(r"[a-z0-9_]+", text.lower())
        if len(t) >= 5 and t not in _STOPWORDS
    }


def references_history(answer: str, history_text: str, task_text: str) -> bool:
    """Deterministic PROXY for 'the answer referenced/applied the history'.

    Counts distinctive tokens that appear in the history but NOT in the task
    (so shared task vocabulary does not falsely count) and reports True when at
    least two of them surface in the answer. This is a heuristic proxy, not a
    judgement of genuine reliance — reported only for the relevant-history
    control and clearly labelled as a proxy in the run report.
    """
    hist_only = _distinctive_tokens(history_text) - _distinctive_tokens(task_text)
    if not hist_only:
        return False
    lowered = answer.lower()
    return sum(1 for t in hist_only if t in lowered) >= 2


# ---------------------------------------------------------------------------
# Answering agent
# ---------------------------------------------------------------------------


def _trial_tag(scenario_id: str, seed: int, condition: str) -> str:
    """Inert trailing tag: an OPAQUE stable token, unique per (scenario, seed,
    condition), so a cached or real provider yields independent draws instead of
    collapsing onto one.

    Deliberately opaque (a hash) — it must NOT reveal the condition
    (relevant vs contaminating) to the evaluated model. An earlier version leaked
    ``cond=contaminating_history`` into the prompt, which would tell the model
    which history is the wrong one and bias the filtering result. ``seed`` here is
    a REPETITION index used only for cache-key variation, not a provider sampling
    seed."""
    key = hashlib.sha256(f"{scenario_id}|{seed}|{condition}".encode()).hexdigest()[:12]
    return f"\n\n[trial: {key}]"


class ContaminationAgent:
    """Wraps an ``LLMProvider`` and produces a final answer for one condition."""

    def __init__(self, provider: LLMProvider, *, structured_history: bool = False) -> None:
        self._provider = provider
        self._structured_history = structured_history

    def answer(
        self,
        *,
        scenario_id: str,
        seed: int,
        condition: str,
        task: str,
        history_text: str | None,
        history_payload: dict[str, Any] | None = None,
    ) -> str:
        tag = _trial_tag(scenario_id, seed, condition)
        if history_text is None:
            system_prompt = NO_HISTORY_SYSTEM_PROMPT
            user_prompt = f"Task:\n{task}{tag}"
        else:
            if self._structured_history:
                if history_payload is None:
                    raise ValueError("structured history requires a payload")
                rendered = _json_text(_compact_history(history_payload, query=task, limit=1))
            else:
                rendered = _render_results([{"excerpt": history_text}])
            system_prompt = WITH_HISTORY_SYSTEM_PROMPT
            user_prompt = f"Task:\n{task}\n\n{HISTORY_DELIMITER}{rendered}{tag}"
        response = self._provider.generate_json(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            schema_description=ANSWER_SCHEMA,
        )
        parsed = response.parsed_json if isinstance(response.parsed_json, dict) else {}
        return str(parsed.get("answer") or "").strip()


# ---------------------------------------------------------------------------
# Deterministic scripted stub (no network) — for CI / --dry-run
# ---------------------------------------------------------------------------


def _scripted_contamination_handler(system_prompt: str, user_prompt: str) -> dict[str, Any]:
    """Simulate an agent that fully adopts whatever guidance is most salient.

    * With forced history present, echo the history — so the relevant-history
      condition surfaces marker_a (chose_A), the contaminating condition surfaces
      marker_b (chose_B), and a benign-irrelevant condition surfaces neither
      (ambiguous). This exercises all three classifications end to end.
    * With no history, echo the task requirement — the task states marker_a, so
      the baseline surfaces chose_A.

    Values are placeholders (this is a stub, not the real agent); the point is to
    confirm the wiring and deterministic detection work end to end.
    """
    if HISTORY_DELIMITER in user_prompt:
        history = user_prompt.split(HISTORY_DELIMITER, 1)[1].split("\n\n[trial:", 1)[0].strip()
        return {"answer": f"Applying the retrieved prior work: {history}"}
    task = ""
    if "Task:\n" in user_prompt:
        task = user_prompt.split("Task:\n", 1)[1].split("\n\n[trial:", 1)[0].strip()
    return {"answer": f"Based on the task requirements, I will proceed with: {task}"}


# ---------------------------------------------------------------------------
# Trial record + orchestration
# ---------------------------------------------------------------------------


@dataclass
class Trial:
    scenario_id: str
    taxonomy_type: str
    seed: int
    condition: str
    classification: str  # chose_A | chose_B | ambiguous | error  (strict detector)
    used_history: bool
    answer_preview: str
    classification_leading: str = "ambiguous"  # decision-first detector
    error: str | None = None


def _history_for(scenario: Scenario, condition: str) -> str | None:
    if condition == CONDITION_NO_HISTORY:
        return None
    if condition == CONDITION_RELEVANT:
        return scenario.relevant_history
    return scenario.contaminating_history


def _structured_history_for(scenario: Scenario, condition: str) -> dict[str, Any] | None:
    """Build a production-shaped query result for the compact MCP serializer."""
    history = _history_for(scenario, condition)
    if history is None:
        return None
    item: dict[str, Any] = {"source_item_id": f"source-{scenario.id}", "excerpt": history, "recorded_at": "2026-08-01T00:00:00+00:00", "recorded_at_source": "ingest"}
    if condition == CONDITION_CONTAMINATING:
        item["historical_updates"] = [{"memory_type": "decision", "status": "outdated", "replacement_status": "current", "current_text": scenario.relevant_history, "current_recorded_at": "2026-08-20T00:00:00+00:00"}]
    return {"results": [item], "lookup_event_id": f"lookup-{scenario.id}"}

def run_trial(agent: ContaminationAgent, scenario: Scenario, seed: int, condition: str) -> Trial:
    history = _history_for(scenario, condition)
    try:
        answer = agent.answer(
            scenario_id=scenario.id,
            seed=seed,
            condition=condition,
            task=scenario.current_task,
            history_text=history,
            history_payload=_structured_history_for(scenario, condition) if agent._structured_history else None,
        )
    except LLMProviderError as exc:
        return Trial(
            scenario_id=scenario.id,
            taxonomy_type=scenario.taxonomy_type,
            seed=seed,
            condition=condition,
            classification="error",
            used_history=False,
            answer_preview="",
            error=f"{type(exc).__name__}: {str(exc)[:200]}",
        )
    classification = classify_answer(answer, scenario.marker_a, scenario.marker_b)
    classification_leading = classify_answer_leading(answer, scenario.marker_a, scenario.marker_b)
    used = (
        references_history(answer, scenario.relevant_history, scenario.current_task)
        if condition == CONDITION_RELEVANT
        else False
    )
    return Trial(
        scenario_id=scenario.id,
        taxonomy_type=scenario.taxonomy_type,
        seed=seed,
        condition=condition,
        classification=classification,
        used_history=used,
        answer_preview=answer[:160],
        classification_leading=classification_leading,
    )


def run_harness(
    *,
    agent: ContaminationAgent,
    scenarios: list[Scenario],
    seeds: list[int],
) -> list[Trial]:
    """Run every (scenario, seed, condition) trial. Distinct condition per trial;
    the same seed across conditions keeps the only variable the forced history."""
    trials: list[Trial] = []
    for scenario in scenarios:
        for seed in seeds:
            for condition in CONDITIONS:
                trials.append(run_trial(agent, scenario, seed, condition))
    return trials


# ---------------------------------------------------------------------------
# Metrics (deterministic given the answers)
# ---------------------------------------------------------------------------


def _rate_with_band(numerator: int, denominator: int) -> dict[str, Any]:
    """Rate + Wilson 95% band, empty-data safe (band is None when n == 0)."""
    if denominator == 0:
        return {"rate": None, "k": numerator, "n": 0, "wilson_95": None}
    low, high = _wilson_95(numerator, denominator)
    return {
        "rate": numerator / denominator,
        "k": numerator,
        "n": denominator,
        "wilson_95": [low, high],
    }


def _diff_with_band(k1: int, n1: int, k2: int, n2: int) -> dict[str, Any]:
    """95% band for the difference of two proportions p1 - p2 (Newcombe method 10).

    Composes the two Wilson score intervals (the same ``_wilson_95`` used
    everywhere else) into a difference interval, so no new dependency and no
    normal approximation on small counts. Empty-data safe: ``diff`` and band are
    ``None`` when either arm has n == 0.

    Direction convention for this harness: arm 1 is the treatment (relevant or
    contaminating), arm 2 is the baseline, so a positive ``diff`` whose band
    excludes 0 means the treatment moved the rate up relative to baseline.

    NOTE: the arms are PAIRED (same scenarios/repetitions across conditions);
    this independent-proportions interval is therefore mildly conservative, which
    is the safe direction for a first read. Recorded in the report ``honesty``.
    """
    if n1 == 0 or n2 == 0:
        return {"diff": None, "wilson_95": None, "excludes_zero": None}
    p1, p2 = k1 / n1, k2 / n2
    l1, u1 = _wilson_95(k1, n1)
    l2, u2 = _wilson_95(k2, n2)
    diff = p1 - p2
    low = diff - ((p1 - l1) ** 2 + (u2 - p2) ** 2) ** 0.5
    high = diff + ((u1 - p1) ** 2 + (p2 - l2) ** 2) ** 0.5
    return {"diff": diff, "wilson_95": [low, high], "excludes_zero": low > 0 or high < 0}


def _condition_counts(trials: list[Trial], condition: str, attr: str = "classification") -> dict[str, Any]:
    ok = [t for t in trials if t.condition == condition and t.error is None]
    n = len(ok)
    chose_a = sum(1 for t in ok if getattr(t, attr) == "chose_A")
    chose_b = sum(1 for t in ok if getattr(t, attr) == "chose_B")
    ambiguous = sum(1 for t in ok if getattr(t, attr) == "ambiguous")
    used = sum(1 for t in ok if t.used_history)
    return {
        "n": n,
        "n_errors": sum(1 for t in trials if t.condition == condition and t.error is not None),
        "chose_A": chose_a,
        "chose_B": chose_b,
        "ambiguous": ambiguous,
        "used_history": used,
        "choose_A_rate": _rate_with_band(chose_a, n),
        "choose_B_rate": _rate_with_band(chose_b, n),
        "ambiguous_rate": _rate_with_band(ambiguous, n),
        "used_history_rate": _rate_with_band(used, n),
    }


def _headline(trials: list[Trial], attr: str) -> dict[str, Any]:
    """Baseline/control/contamination + differential for one detector (attr)."""
    baseline = _condition_counts(trials, CONDITION_NO_HISTORY, attr)
    control = _condition_counts(trials, CONDITION_RELEVANT, attr)
    test = _condition_counts(trials, CONDITION_CONTAMINATING, attr)
    relevant_lift = _diff_with_band(
        control["chose_A"], control["n"], baseline["chose_A"], baseline["n"]
    )
    contamination_harm = _diff_with_band(
        test["chose_B"], test["n"], baseline["chose_B"], baseline["n"]
    )
    return {
        "baseline_choose_A_rate": baseline["choose_A_rate"],
        "control_choose_A_rate": control["choose_A_rate"],
        "control_used_history_rate": control["used_history_rate"],
        "contamination_rate": test["choose_B_rate"],
        "differential": {
            "relevant_lift": relevant_lift,
            "contamination_harm": contamination_harm,
        },
        "ambiguous_rate": {
            CONDITION_NO_HISTORY: baseline["ambiguous_rate"],
            CONDITION_RELEVANT: control["ambiguous_rate"],
            CONDITION_CONTAMINATING: test["ambiguous_rate"],
        },
        "per_condition": {
            CONDITION_NO_HISTORY: baseline,
            CONDITION_RELEVANT: control,
            CONDITION_CONTAMINATING: test,
        },
    }


def compute_metrics(trials: list[Trial]) -> dict[str, Any]:
    # Primary (strict) detector: both-markers -> ambiguous. Conservative; on
    # judgment tasks it UNDER-reports the choice (agent names the rejected option).
    strict = _headline(trials, "classification")
    # Decision-first detector: earliest marker wins. The correct instrument for
    # the ambiguous-task case; retained alongside strict so divergence is visible.
    leading = _headline(trials, "classification_leading")
    return {
        "n_trials": len(trials),
        "n_errors": sum(1 for t in trials if t.error is not None),
        # Strict headline (kept at top level for backward compatibility).
        "baseline_choose_A_rate": strict["baseline_choose_A_rate"],
        "control_choose_A_rate": strict["control_choose_A_rate"],
        "control_used_history_rate": strict["control_used_history_rate"],
        "contamination_rate": strict["contamination_rate"],
        "differential": strict["differential"],
        "ambiguous_rate": strict["ambiguous_rate"],
        "per_condition": strict["per_condition"],
        # Decision-first re-analysis (primary for ambiguous-task reads).
        "leading_choice": leading,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_agent_provider(*, dry_run: bool, cache_dir: Path | None, no_eval_cache: bool) -> LLMProvider:
    if dry_run:
        return ScriptedDecisionProvider(_scripted_contamination_handler)
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


def _fmt(band: dict[str, Any]) -> str:
    rate = band["rate"]
    if rate is None:
        return "n/a (n=0)"
    w = band["wilson_95"]
    return f"{rate:.3f}  [{w[0]:.3f}, {w[1]:.3f}]  (k={band['k']}/n={band['n']})"


def _fmt_diff(diff: dict[str, Any]) -> str:
    d = diff["diff"]
    if d is None:
        return "n/a (n=0)"
    w = diff["wilson_95"]
    flag = "  *excludes 0*" if diff["excludes_zero"] else ""
    return f"{d:+.3f}  [{w[0]:+.3f}, {w[1]:+.3f}]{flag}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--dry-run", action="store_true", help="Deterministic scripted stub; no network.")
    parser.add_argument("--structured-history", action="store_true", help="Render forced history through the production MCP compact serializer.")
    parser.add_argument("--max-calls", type=int, default=50, help="Hard cap on planned model calls (default: 50).")
    parser.add_argument("--seeds", type=_parse_seeds, default=[0, 1, 2], help="Comma-separated seeds (default 0,1,2).")
    parser.add_argument("--scenarios", type=Path, default=_SCENARIOS_PATH, help="Scenario JSON (default: shipped scenarios.json).")
    parser.add_argument("--cache-dir", type=Path, default=None, help="LLM cache dir (real runs).")
    parser.add_argument("--no-eval-cache", action="store_true", help="Disable eval-time LLM caching.")
    parser.add_argument("--output", type=Path, default=None, help="Write the run JSON here.")
    args = parser.parse_args(argv)

    scenarios = load_scenarios(args.scenarios)
    case = load_case(args.scenarios)
    seeds = list(args.seeds)
    planned_calls = len(scenarios) * len(seeds) * len(CONDITIONS)
    if args.max_calls <= 0 or planned_calls > args.max_calls:
        parser.error(f"planned model calls ({planned_calls}) exceed --max-calls ({args.max_calls})")

    provider = _build_agent_provider(
        dry_run=args.dry_run, cache_dir=args.cache_dir, no_eval_cache=args.no_eval_cache
    )
    agent = ContaminationAgent(provider, structured_history=args.structured_history)
    trials = run_harness(agent=agent, scenarios=scenarios, seeds=seeds)
    metrics = compute_metrics(trials)

    _CASE_NOTES = {
        "ambiguous-task": (
            "This is the AMBIGUOUS-TASK case: the task does NOT pin the answer, so the "
            "baseline is expected to be genuinely split and the headline is the "
            "DIFFERENTIAL (relevant_lift, contamination_harm), not the raw contamination "
            "rate. The difference bands are independent-proportions (Newcombe) and thus "
            "mildly conservative given the arms are paired."
        ),
        "applicability-judgment": (
            "This is the APPLICABILITY-JUDGMENT case: the convention is ARBITRARY (baseline "
            "cannot reconstruct it, so it should be uncertain), relevant history carries the "
            "in-scope convention (relevant_lift should be materially positive), and "
            "contaminating history carries a real convention from a DIFFERENT scope that the "
            "agent should REJECT (contamination_harm > 0 means it adopted a non-applicable "
            "convention = a scope/applicability failure). Decision-first detector is primary; "
            "difference bands are independent-proportions (Newcombe), mildly conservative."
        ),
    }
    case_note = _CASE_NOTES.get(
        case,
        "This tests the EXPLICIT-TASK case (the task pins approach A), so the "
        "headline is the raw contamination rate and the differentials are ~0 by design.",
    )
    report = {
        "harness": "pull_contamination",
        "case": case,
        "mode": "dry-run" if args.dry_run else "real",
        "history_rendering": "mcp_compact_history" if args.structured_history else "plain_text",
        "planned_model_calls": planned_calls,
        "model_call_cap": args.max_calls,
        "seeds": seeds,
        "n_scenarios": len(scenarios),
        "conditions": list(CONDITIONS),
        "metrics": metrics,
        "trials": [asdict(t) for t in trials],
        "honesty": (
            "Deterministic marker-scan is the primary signal (no LLM judge). "
            "The --seeds values are REPETITION indices used only to vary the "
            "cache key so each of the N draws is independent; they are NOT "
            "provider sampling seeds, and the Wilson intervals are over "
            "scenario x repetition. The trial tag is opaque (a hash) and does "
            "NOT reveal the condition to the model. control_used_history_rate is "
            "a lexical-overlap PROXY for reference, not a judgement of genuine "
            "reliance. Dry-run values are scripted placeholders. Authored "
            "synthetic scenarios bound realism. " + case_note
        ),
    }
    serialised = json.dumps(report, indent=2, sort_keys=True)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialised, encoding="utf-8")
        print(f"Wrote run report -> {args.output}", file=sys.stderr)

    # The strict detector is primary only for the explicit-task case; for every
    # other case (ambiguous-task, applicability-judgment, ...) the decision-first
    # detector is primary, since comparative prose inflates the strict ambiguous rate.
    leading_primary = report["case"] != "explicit-task"
    strict_tag = "" if leading_primary else "  [PRIMARY for explicit-task]"
    leading_tag = f"  [PRIMARY for {report['case']}]" if leading_primary else ""
    print("=== Pull-Contamination Filtering Harness ===")
    print(f"case={report['case']} mode={report['mode']} seeds={seeds} scenarios={len(scenarios)} trials={metrics['n_trials']}")
    print(f"-- strict detector (both markers -> ambiguous; conservative){strict_tag} --")
    print(f"  baseline_choose_A_rate       = {_fmt(metrics['baseline_choose_A_rate'])}")
    print(f"  control_choose_A_rate        = {_fmt(metrics['control_choose_A_rate'])}")
    print(f"  contamination_rate (chose_B) = {_fmt(metrics['contamination_rate'])}")
    print(f"  ambiguous[no_hist/rel/contam]= {metrics['ambiguous_rate'][CONDITION_NO_HISTORY]['rate']}/{metrics['ambiguous_rate'][CONDITION_RELEVANT]['rate']}/{metrics['ambiguous_rate'][CONDITION_CONTAMINATING]['rate']}")
    lead = metrics["leading_choice"]
    print(f"-- leading (decision-first) detector{leading_tag} --")
    print(f"  baseline_choose_A_rate       = {_fmt(lead['baseline_choose_A_rate'])}")
    print(f"  control_choose_A_rate        = {_fmt(lead['control_choose_A_rate'])}")
    print(f"  control_used_history_rate    = {_fmt(lead['control_used_history_rate'])}")
    print(f"  contamination_rate (chose_B) = {_fmt(lead['contamination_rate'])}")
    print(f"  relevant_lift (A: rel-base)  = {_fmt_diff(lead['differential']['relevant_lift'])}")
    print(f"  contamination_harm (B: cont-base) = {_fmt_diff(lead['differential']['contamination_harm'])}")
    print(f"  errors                       = {metrics['n_errors']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
