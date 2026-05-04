"""
Routing regression test: measures whether status/progress queries return
appropriate memory types without regressing specific recall queries.

Run against live service: python -m evals.routing_status_recall_eval
"""
import json
import sys
import time
import urllib.request
from dataclasses import dataclass

SERVICE_URL = "http://127.0.0.1:19836"
CONTAINER_REF = "git:github.com/rore/pallium"

STATUS_QUERIES = [
    "what are we doing now in this project",
    "where did we leave off",
    "what should I work on next",
    "summarize recent progress",
    "what happened in the last session",
    "current active work",
]

SPECIFIC_RECALL_QUERIES = [
    "what did we decide about haiku vs sonnet",
    "why did we disable interest extraction",
    "what is the extraction precision",
    "how does the anchor prefilter work",
    "what model does write extraction use",
    "constraint about language cues",
    "what was the investigation outcome for thread rebuild truncation",
]

DESIRED_STATUS_TYPES = {"task_checkpoint", "thread_summary"}
DESIRED_RECALL_TYPES = {"investigation_outcome", "decision", "constraint_memory"}


@dataclass
class QueryResult:
    query: str
    result_types: list[str]
    injected_types: list[str]
    should_inject: bool
    has_desired_type: bool
    lane: str
    demoted_types: list[str]


def query_service(text: str) -> dict:
    req = urllib.request.Request(
        f"{SERVICE_URL}/query/debug",
        data=json.dumps({
            "text": text,
            "container_ref": CONTAINER_REF,
            "visibility": "private",
        }).encode(),
        headers={"Content-Type": "application/json"},
    )
    resp = urllib.request.urlopen(req, timeout=15)
    return json.loads(resp.read())


def evaluate_query(text: str, desired_types: set[str]) -> QueryResult:
    result = query_service(text)
    results = result.get("results", [])
    result_types = [(r.get("type") or "source") for r in results]
    blocks = result.get("injectable_blocks", [])
    injected_types = [b.get("memory_type", "?") for b in blocks]
    trace = result.get("trace", {})
    routing = trace.get("routing", {})
    demoted = [d.get("memory_type", "?") for d in routing.get("demoted_higher_level_hits", [])]
    lane = routing.get("selected_layer", "?")

    has_desired = bool(set(result_types) & desired_types)

    return QueryResult(
        query=text,
        result_types=result_types,
        injected_types=injected_types,
        should_inject=result.get("should_inject", False),
        has_desired_type=has_desired,
        lane=lane,
        demoted_types=demoted,
    )


def run_eval():
    print("=" * 70)
    print("ROUTING STATUS/RECALL EVALUATION")
    print("=" * 70)
    print()

    # Status queries
    print("--- STATUS QUERIES (desired: task_checkpoint, thread_summary) ---")
    print()
    status_hits = 0
    status_results = []
    for q in STATUS_QUERIES:
        try:
            r = evaluate_query(q, DESIRED_STATUS_TYPES)
            status_results.append(r)
            hit = "HIT" if r.has_desired_type else "MISS"
            if r.has_desired_type:
                status_hits += 1
            print(f"  [{hit}] \"{q}\"")
            print(f"        types={r.result_types[:3]} lane={r.lane} demoted={r.demoted_types}")
            time.sleep(2)
        except Exception as e:
            print(f"  [ERR] \"{q}\" -> {e}")
        print()

    # Specific recall queries
    print("--- SPECIFIC RECALL (desired: investigation_outcome, decision, constraint) ---")
    print()
    recall_hits = 0
    recall_results = []
    for q in SPECIFIC_RECALL_QUERIES:
        try:
            r = evaluate_query(q, DESIRED_RECALL_TYPES)
            recall_results.append(r)
            hit = "HIT" if r.has_desired_type else "MISS"
            if r.has_desired_type:
                recall_hits += 1
            print(f"  [{hit}] \"{q}\"")
            print(f"        types={r.result_types[:3]} lane={r.lane}")
            time.sleep(2)
        except Exception as e:
            print(f"  [ERR] \"{q}\" -> {e}")
        print()

    # Summary
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"  Status queries:  {status_hits}/{len(STATUS_QUERIES)} return desired type ({100*status_hits/max(len(STATUS_QUERIES),1):.0f}%)")
    print(f"  Recall queries:  {recall_hits}/{len(SPECIFIC_RECALL_QUERIES)} return desired type ({100*recall_hits/max(len(SPECIFIC_RECALL_QUERIES),1):.0f}%)")
    print()
    print("  Target: improve status without regressing recall")
    print()

    # Demotions
    all_demotions = [d for r in status_results for d in r.demoted_types]
    if all_demotions:
        print(f"  Thread_summary demotions in status queries: {all_demotions.count('thread_summary')}/{len(STATUS_QUERIES)}")


if __name__ == "__main__":
    run_eval()
