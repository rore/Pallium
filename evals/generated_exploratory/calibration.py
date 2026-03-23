"""Calibration runner for QPP injection justification.

Loads labeled scenarios from multiple eval suites, executes each through the
pipeline, extracts injection signals at the decision point, and evaluates
both justification formulas (linear + rule-based) against the labels.

Usage:
    python -m evals.generated_exploratory.calibration
    python -m evals.generated_exploratory.calibration --output-dir evals/generated_exploratory/output/calibration
"""

from __future__ import annotations

import argparse
import itertools
import json
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from fastapi.testclient import TestClient

from app.config import AppConfig
from app.main import create_app
from semantic.agent_conversation_memory_routing_justification import (
    InjectionSignals,
    LinearWeights,
    RuleThresholds,
    compute_injection_signals,
    justify_injection_linear,
    justify_injection_rules,
)


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent

_SEED_SCENARIOS = _REPO_ROOT / "evals" / "generated_exploratory" / "scenarios" / "seed_invariant_scenarios.json"
_MEMORY_ROUTING_SCENARIOS = _REPO_ROOT / "evals" / "memory_routing" / "scenarios.json"
_WORK_RESUMPTION_SCENARIOS = _REPO_ROOT / "evals" / "work_resumption" / "scenarios.json"
_DEFAULT_OUTPUT_DIR = _REPO_ROOT / "evals" / "generated_exploratory" / "output" / "calibration"


# ---------------------------------------------------------------------------
# Label derivation
# ---------------------------------------------------------------------------

def _derive_label(scenario: dict[str, Any], source: str) -> bool | None:
    """Derive the injection label (True=should inject, False=should not) from scenario metadata.

    Returns None for scenarios where the label is ambiguous.
    """
    if source == "seed":
        scenario_id = scenario.get("scenario_id", "")
        # Off-topic seed scenarios should NOT inject
        if "off-topic" in scenario_id or "off_topic" in scenario_id:
            return False
        # Explicit metadata override
        meta = scenario.get("_generation_metadata") or {}
        if "expected_should_inject" in meta:
            return bool(meta["expected_should_inject"])
        # Seed scenarios that are P0 correctness invariants and not off-topic
        # are generally about correct retrieval/injection behavior.
        # We mark them as positive (should inject) unless they have
        # soft_expectations.must_not_include that suggests suppression.
        return True

    if source == "memory_routing":
        expected = scenario.get("expected_value")
        if expected is not None:
            return bool(expected)
        return None

    if source == "work_resumption":
        should_help = scenario.get("should_memory_help")
        if should_help is not None:
            return bool(should_help)
        return None

    if source == "generated_negative":
        return False

    return None


# ---------------------------------------------------------------------------
# Scenario normalization
# ---------------------------------------------------------------------------

def _normalize_seed_scenario(scenario: dict[str, Any]) -> dict[str, Any]:
    """Already in step-based format — return as-is."""
    return scenario


def _normalize_simple_scenario(scenario: dict[str, Any]) -> dict[str, Any]:
    """Convert prior_events + current_query format to step-based format."""
    steps = []
    if scenario.get("prior_events"):
        steps.append({
            "step_id": "ingest",
            "action": "ingest",
            "events": scenario["prior_events"],
        })
    if scenario.get("current_thread_context"):
        # Thread context items are ingested as events with defaults
        context_events = []
        query = scenario.get("current_query") or {}
        container_ref = query.get("container_ref", "chat:calibration")
        for ctx in scenario["current_thread_context"]:
            context_events.append({
                "source_type": "chat_message",
                "source_id": f"ctx-{len(context_events)}",
                "content_type": "text/plain",
                "content": ctx.get("content", ""),
                "artifact_kind": ctx.get("artifact_kind", "message"),
                "role": ctx.get("role", "user"),
                "container_ref": container_ref,
                "thread_ref": f"{container_ref}:thread-calibration",
                "actor_ref": "user:calibration",
                "source_ref": "calibration",
                "occurred_at": datetime(2026, 3, 20, 10, len(context_events), tzinfo=timezone.utc).isoformat(),
            })
        if context_events:
            steps.append({
                "step_id": "context_ingest",
                "action": "ingest",
                "events": context_events,
            })
    if scenario.get("current_query"):
        steps.append({
            "step_id": "query",
            "action": "query",
            "query": scenario["current_query"],
        })
    return {**scenario, "steps": steps}


# ---------------------------------------------------------------------------
# Scenario loading
# ---------------------------------------------------------------------------

def _load_labeled_scenarios(
    *,
    seed_path: Path | None = None,
    memory_routing_path: Path | None = None,
    work_resumption_path: Path | None = None,
    generated_negative_paths: list[Path] | None = None,
) -> list[dict[str, Any]]:
    """Load and label scenarios from all available sources."""
    labeled: list[dict[str, Any]] = []

    if seed_path and seed_path.exists():
        raw = json.loads(seed_path.read_text(encoding="utf-8"))
        for s in raw:
            label = _derive_label(s, "seed")
            if label is None:
                continue
            labeled.append({
                "scenario": _normalize_seed_scenario(s),
                "scenario_id": s.get("scenario_id", "unknown"),
                "source": "seed",
                "label": label,
            })

    if memory_routing_path and memory_routing_path.exists():
        raw = json.loads(memory_routing_path.read_text(encoding="utf-8"))
        for s in raw:
            label = _derive_label(s, "memory_routing")
            if label is None:
                continue
            labeled.append({
                "scenario": _normalize_simple_scenario(s),
                "scenario_id": s.get("scenario_id", "unknown"),
                "source": "memory_routing",
                "label": label,
            })

    if work_resumption_path and work_resumption_path.exists():
        raw = json.loads(work_resumption_path.read_text(encoding="utf-8"))
        for s in raw:
            label = _derive_label(s, "work_resumption")
            if label is None:
                continue
            labeled.append({
                "scenario": _normalize_simple_scenario(s),
                "scenario_id": s.get("scenario_id", "unknown"),
                "source": "work_resumption",
                "label": label,
            })

    for path in (generated_negative_paths or []):
        if path.exists():
            raw = json.loads(path.read_text(encoding="utf-8"))
            for s in raw:
                labeled.append({
                    "scenario": _normalize_seed_scenario(s) if "steps" in s else _normalize_simple_scenario(s),
                    "scenario_id": s.get("scenario_id", "unknown"),
                    "source": "generated_negative",
                    "label": False,
                })

    return labeled


# ---------------------------------------------------------------------------
# Signal extraction from debug trace
# ---------------------------------------------------------------------------

def _extract_signals_from_debug(debug_payload: dict[str, Any]) -> InjectionSignals:
    """Build InjectionSignals from the debug trace's routing data.

    Reconstructs candidate-like dicts from the trace entries and feeds them
    to compute_injection_signals.
    """
    routing = debug_payload.get("trace", {}).get("routing") or {}
    selected_results = routing.get("selected_results") or []

    # Reconstruct candidate dicts from trace entries
    candidates: list[dict[str, object]] = []
    for entry in selected_results:
        candidates.append({
            "routing_score": int(entry.get("routing_score", 0)),
            "retrieval_score": int(entry.get("retrieval_score", 0)),
            "support_grade": str(entry.get("support_grade", "weak")),
            "layer": str(entry.get("layer", "")),
            "work_signal_types": tuple(entry.get("work_signal_types", ())),
            "work_usefulness_score": int(entry.get("work_usefulness_score", 0)),
            "lexical_score": entry.get("lexical_score"),
            "vector_score": entry.get("vector_score"),
            "freshness_timestamp_value": entry.get("freshness_timestamp"),
        })

    return compute_injection_signals(candidates)


# ---------------------------------------------------------------------------
# Scenario execution
# ---------------------------------------------------------------------------

def _with_default_visibility(payload: dict[str, Any]) -> dict[str, Any]:
    updated = dict(payload)
    updated.setdefault("container_visibility", "public")
    return updated


def _drain(client: TestClient) -> None:
    client.app.state.pallium_service.drain_processing_queue(worker_id="calibration-runner")


def _run_scenario(
    scenario: dict[str, Any],
    config: AppConfig,
) -> dict[str, Any]:
    """Execute a scenario and return the debug payload + query payload."""
    with TemporaryDirectory() as temp_dir:
        db_url = f"sqlite:///{Path(temp_dir) / 'cal.db'}"
        scenario_config = replace(
            config,
            sqlite_url=db_url,
            default_use_case="agent_conversation_memory",
        )

        with TestClient(create_app(scenario_config)) as client:
            query_payload: dict[str, Any] = {}
            debug_payload: dict[str, Any] = {}

            for step in scenario.get("steps", []):
                action = step.get("action")
                if action == "ingest":
                    for event in step.get("events", []):
                        resp = client.post("/items", json=[_with_default_visibility(event)])
                        resp.raise_for_status()
                    _drain(client)
                elif action == "query":
                    query_request = _with_default_visibility(step["query"])
                    resp = client.post("/query", json=query_request)
                    resp.raise_for_status()
                    query_payload = resp.json()
                    resp = client.post("/query/debug", json=query_request)
                    resp.raise_for_status()
                    debug_payload = resp.json()

            engine = getattr(client.app.state.pallium_service._storage, "_engine", None)
            if engine is not None:
                engine.dispose()

    return {"query": query_payload, "debug": debug_payload}


# ---------------------------------------------------------------------------
# Formula evaluation
# ---------------------------------------------------------------------------

def _evaluate_formulas(
    collected: list[dict[str, Any]],
) -> dict[str, Any]:
    """Evaluate both formulas on collected signal data and report metrics."""
    if not collected:
        return {"error": "no_data"}

    linear_results = _evaluate_single_formula(collected, "linear")
    rules_results = _evaluate_single_formula(collected, "rules")

    return {
        "linear": linear_results,
        "rules": rules_results,
        "recommendation": _pick_winner(linear_results, rules_results),
    }


def _evaluate_single_formula(
    collected: list[dict[str, Any]],
    formula: str,
) -> dict[str, Any]:
    """Evaluate one formula and return precision/recall/F1."""
    tp = fp = tn = fn = 0
    misclassified: list[dict[str, Any]] = []

    for entry in collected:
        signals = InjectionSignals(**entry["signals"])
        label = entry["label"]

        if formula == "linear":
            result = justify_injection_linear(signals)
        else:
            result = justify_injection_rules(signals)

        predicted = result.justified

        if predicted and label:
            tp += 1
        elif predicted and not label:
            fp += 1
            misclassified.append({
                "scenario_id": entry["scenario_id"],
                "source": entry["source"],
                "label": label,
                "predicted": predicted,
                "reason": result.reason,
                "score": result.score,
                "type": "false_positive",
            })
        elif not predicted and not label:
            tn += 1
        else:
            fn += 1
            misclassified.append({
                "scenario_id": entry["scenario_id"],
                "source": entry["source"],
                "label": label,
                "predicted": predicted,
                "reason": result.reason,
                "score": result.score,
                "type": "false_negative",
            })

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

    return {
        "tp": tp, "fp": fp, "tn": tn, "fn": fn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "misclassified": misclassified,
    }


def _pick_winner(linear: dict[str, Any], rules: dict[str, Any]) -> dict[str, Any]:
    """Pick the better formula.  Prefer higher precision, then F1.  Tie-break: rules (more interpretable)."""
    linear_f1 = linear["f1"]
    rules_f1 = rules["f1"]
    linear_prec = linear["precision"]
    rules_prec = rules["precision"]

    if rules_prec >= linear_prec and rules_f1 >= linear_f1 - 0.02:
        return {"winner": "rules", "reason": "Higher or equal precision, comparable F1, more interpretable"}
    if linear_prec > rules_prec + 0.05:
        return {"winner": "linear", "reason": "Significantly higher precision"}
    if linear_f1 > rules_f1 + 0.05:
        return {"winner": "linear", "reason": "Significantly higher F1"}
    return {"winner": "rules", "reason": "Close performance, prefer interpretability"}


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------

def run_calibration(
    *,
    output_dir: Path,
    config: AppConfig,
    seed_path: Path | None = None,
    memory_routing_path: Path | None = None,
    work_resumption_path: Path | None = None,
    generated_negative_paths: list[Path] | None = None,
) -> Path:
    """Run full calibration: load scenarios → execute → extract signals → evaluate formulas."""
    output_dir.mkdir(parents=True, exist_ok=True)

    labeled = _load_labeled_scenarios(
        seed_path=seed_path or _SEED_SCENARIOS,
        memory_routing_path=memory_routing_path or _MEMORY_ROUTING_SCENARIOS,
        work_resumption_path=work_resumption_path or _WORK_RESUMPTION_SCENARIOS,
        generated_negative_paths=generated_negative_paths,
    )

    print(f"Loaded {len(labeled)} labeled scenarios")
    pos = sum(1 for s in labeled if s["label"])
    neg = len(labeled) - pos
    print(f"  Positive (should inject): {pos}")
    print(f"  Negative (should NOT inject): {neg}")

    collected: list[dict[str, Any]] = []
    signals_path = output_dir / "signals.jsonl"

    with signals_path.open("w", encoding="utf-8") as f:
        for i, entry in enumerate(labeled):
            scenario_id = entry["scenario_id"]
            print(f"  [{i+1}/{len(labeled)}] {scenario_id} ...", end=" ", flush=True)
            try:
                result = _run_scenario(entry["scenario"], config)
                signals = _extract_signals_from_debug(result["debug"])
                actual_inject = result["query"].get("should_inject", False)

                record = {
                    "scenario_id": scenario_id,
                    "source": entry["source"],
                    "label": entry["label"],
                    "actual_should_inject": actual_inject,
                    "signals": asdict(signals),
                }
                collected.append(record)
                f.write(json.dumps(record, default=str) + "\n")
                print("OK")
            except Exception as exc:
                print(f"ERROR: {exc}")
                record = {
                    "scenario_id": scenario_id,
                    "source": entry["source"],
                    "label": entry["label"],
                    "error": f"{type(exc).__name__}: {exc}",
                }
                f.write(json.dumps(record, default=str) + "\n")

    # Filter out errored entries
    valid = [c for c in collected if "signals" in c]
    print(f"\nCollected signals from {len(valid)} / {len(labeled)} scenarios")

    evaluation = _evaluate_formulas(valid)
    eval_path = output_dir / "evaluation.json"
    eval_path.write_text(json.dumps(evaluation, indent=2, default=str), encoding="utf-8")

    print(f"\n{'='*60}")
    print("CALIBRATION RESULTS")
    print(f"{'='*60}")
    for formula in ("linear", "rules"):
        r = evaluation[formula]
        print(f"\n{formula.upper()}:")
        print(f"  Precision: {r['precision']:.4f}  Recall: {r['recall']:.4f}  F1: {r['f1']:.4f}")
        print(f"  TP={r['tp']}  FP={r['fp']}  TN={r['tn']}  FN={r['fn']}")
        if r["misclassified"]:
            print(f"  Misclassified ({len(r['misclassified'])}):")
            for m in r["misclassified"]:
                print(f"    {m['type']}: {m['scenario_id']} [{m['source']}] → {m['reason']}")

    rec = evaluation.get("recommendation", {})
    print(f"\nRECOMMENDATION: {rec.get('winner', '?')} — {rec.get('reason', '?')}")
    print(f"\nResults written to {output_dir}")

    return output_dir


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Calibrate QPP injection justification.")
    parser.add_argument("--output-dir", type=Path, default=_DEFAULT_OUTPUT_DIR)
    parser.add_argument("--generated-negatives", type=Path, nargs="*", default=[])
    args = parser.parse_args()

    run_calibration(
        output_dir=args.output_dir,
        config=AppConfig.from_env(),
        generated_negative_paths=args.generated_negatives,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
