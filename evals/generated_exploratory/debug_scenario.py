"""One-shot diagnostic: replay a scenario and dump the full debug trace.

Usage:
    python -m evals.generated_exploratory.debug_scenario \
        --scenario-file evals/generated_exploratory/scenarios/recall_completeness_batch.json \
        --scenario-id recall-comparative-branch-hold-queues
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

from app.config import AppConfig
from app.main import create_app


def main() -> int:
    parser = argparse.ArgumentParser(description="Replay a scenario and dump debug trace.")
    parser.add_argument("--scenario-file", type=Path, required=True)
    parser.add_argument("--scenario-id", required=True)
    parser.add_argument("--cache-dir", type=Path, default=None)
    args = parser.parse_args()

    scenarios = json.loads(args.scenario_file.read_text(encoding="utf-8"))
    scenario = next((s for s in scenarios if s["scenario_id"] == args.scenario_id), None)
    if not scenario:
        print(f"Scenario {args.scenario_id!r} not found")
        return 1

    config = AppConfig.from_env()

    with TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        db_path = Path(temp_dir) / "debug.db"
        vector_path = Path(temp_dir) / "vector.index"
        scenario_config = replace(
            config,
            sqlite_url=f"sqlite:///{db_path}",
            default_use_case="agent_conversation_memory",
            vector_index=replace(config.vector_index, index_path=str(vector_path)),
        )

        with TestClient(create_app(scenario_config)) as client:
            if args.cache_dir:
                from evals.generated_exploratory.invariant_runner import _wrap_providers_with_cache
                _wrap_providers_with_cache(client, args.cache_dir)

            # Ingest
            for step in scenario["steps"]:
                if step["action"] != "ingest":
                    continue
                events = step.get("events", [])
                resp = client.post("/items", json=events)
                resp.raise_for_status()
                print(f"  Ingested {len(events)} items (step: {step['step_id']})")

            # Drain
            svc = client.app.state.pallium_service
            svc.drain_processing_queue(worker_id="debug-runner")
            svc.reconcile_vector_index()
            print("  Processing complete")

            # Query
            for step in scenario["steps"]:
                if step["action"] != "query":
                    continue
                query_req = step.get("query", {})
                print(f"\n{'='*70}")
                print(f"QUERY: {query_req.get('text')}")
                print(f"{'='*70}")

                debug_resp = client.post("/query/debug", json=query_req)
                debug_resp.raise_for_status()
                debug = debug_resp.json()

                query_resp = client.post("/query", json=query_req)
                query_resp.raise_for_status()
                query = query_resp.json()

                # Injection decision
                print(f"\nshould_inject: {debug.get('should_inject')}")
                print(f"decision_reason: {debug.get('decision_reason')}")

                # Routing trace
                trace = debug.get("trace", {})
                routing = trace.get("routing", {})
                if routing:
                    print(f"\n--- Routing Trace ---")
                    envelope = routing.get("query_signal_envelope", {})
                    print(f"  signal_envelope: {json.dumps(envelope, indent=2)}")
                    justification = routing.get("justification", {})
                    if justification:
                        print(f"  justification: {json.dumps(justification, indent=2)}")
                    policy = routing.get("policy_decision", {})
                    if policy:
                        print(f"  policy_decision: {json.dumps(policy, indent=2)}")

                # Results summary
                results = debug.get("results", [])
                print(f"\n--- Results ({len(results)} total) ---")
                for i, r in enumerate(results):
                    kind = r.get("result_kind")
                    rtype = r.get("type", "")
                    score = r.get("score")
                    lex = r.get("lexical_score")
                    vec = r.get("vector_score")
                    src = r.get("retrieval_source", "")
                    if kind == "memory_hit":
                        payload = r.get("payload", {})
                        text = (
                            payload.get("statement")
                            or payload.get("summary")
                            or payload.get("decision")
                            or payload.get("carry_forward_answer")
                            or payload.get("description")
                            or ""
                        )[:120]
                        print(f"  [{i}] {kind} ({rtype}) score={score} lex={lex} vec={vec} src={src}")
                        print(f"       {text}")
                    elif kind == "source_hit":
                        excerpt = (r.get("excerpt") or "")[:120]
                        print(f"  [{i}] {kind} score={score} lex={lex} vec={vec} src={src}")
                        print(f"       {excerpt}")

                # Injectable blocks
                blocks = query.get("injectable_blocks", [])
                print(f"\n--- Injectable Blocks ({len(blocks)}) ---")
                for i, b in enumerate(blocks):
                    btype = b.get("block_type") or b.get("memory_type", "")
                    text = (b.get("text") or "")[:200]
                    print(f"  [{i}] {btype}: {text}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
