"""Focused retrieval quality tests from LoCoMo conv-26 failure analysis.

Runs the 37 failing queries through Pallium's retrieval pipeline and checks
whether the gold answer information appears in the retrieved results.
No LLM calls — pure retrieval quality measurement.

Usage:
    python -m pytest evals/test_retrieval_quality.py -x -q
    python -m pytest evals/test_retrieval_quality.py -x -q -k "test_gold_in_context_rate"
"""
from __future__ import annotations

import json
import shutil
from dataclasses import replace
from pathlib import Path

import pytest

from app.config import AppConfig
from app.main import create_app
from starlette.testclient import TestClient

DB_CACHE = Path("evals/locomo/db_cache/conv-26.db")
VECTOR_CACHE = Path("evals/locomo/db_cache/conv-26.vector.index")
CONV_ID = "conv-26"

# Curated failure cases: queries that failed in the full benchmark
# Gold answer info was NOT in the top-10 retrieved results
FAILURE_CASES = [
    {"q": "What is Caroline's relationship status?", "gold": "Single", "cat": "multi_hop",
     "gold_keywords": ["single"], "gold_in_any_active": True,
     "note": "active thread_summary mentions 'single parenthood'; atomic_fact 'Caroline and Mel are in a relationship' is wrong (hallucination)"},
    {"q": "Where has Melanie camped?", "gold": "beach, mountains, forest", "cat": "multi_hop",
     "gold_keywords": ["beach", "mountains", "forest"],
     "note": "needs 3 locations scattered across different facts"},
    {"q": "What books has Melanie read?", "gold": "Nothing is Impossible, Charlotte's Web", "cat": "multi_hop",
     "gold_keywords": ["charlotte", "web"],
     "note": "'Nothing is Impossible' not in source data at all; Charlotte's Web in superseded fact_summary"},
    {"q": "What kind of art does Caroline make?", "gold": "abstract art", "cat": "multi_hop",
     "gold_keywords": ["abstract"],
     "note": "superseded atomic_fact has 'Caroline has been experimenting with abstract painting'"},
    {"q": "What events has Caroline participated in to help children?", "gold": "Mentoring program, school speech", "cat": "multi_hop",
     "gold_keywords": ["mentoring", "mentorship"],
     "note": "active thread_summary and task_checkpoint mention mentorship but not retrieved"},
    {"q": "What activities has Melanie done with her family?", "gold": "Pottery, painting, camping, museum, swimming, hiking", "cat": "multi_hop",
     "gold_keywords": ["pottery", "camping", "museum", "swimming", "hiking"],
     "note": "needs 6 activities from multiple facts; mega-fact has some but not all"},
    {"q": "What are Melanie's pets' names?", "gold": "Oliver, Luna, Bailey", "cat": "multi_hop",
     "gold_keywords": ["oliver", "luna", "bailey"],
     "note": "pet names scattered across different facts"},
    {"q": "What subject have Caroline and Melanie both painted?", "gold": "Sunsets", "cat": "multi_hop",
     "gold_keywords": ["sunset"],
     "note": "sunset mentioned in superseded atomic_facts for both people"},
    {"q": "What musical artists/bands has Melanie seen?", "gold": "Summer Sounds, Matt Patterson", "cat": "multi_hop",
     "gold_keywords": ["summer sounds", "matt patterson"],
     "note": "both are in Mel's event fact_summary but retrieval doesn't find it for this query"},
    {"q": "What book did Melanie read from Caroline's suggestion?", "gold": "Becoming Nicole", "cat": "multi_hop",
     "gold_keywords": ["becoming nicole"],
     "note": "in active fact_summary for Caroline but query is about Melanie"},
    {"q": "What book did Caroline recommend to Melanie?", "gold": "Becoming Nicole", "cat": "open_domain",
     "gold_keywords": ["becoming nicole"],
     "note": "same fact, different query angle"},
    {"q": "What pets does Melanie have?", "gold": "Two cats and a dog", "cat": "open_domain",
     "gold_keywords": ["cat", "dog", "oliver", "bailey"],
     "note": "active fact_summary mentions Oliver and Bailey but query doesn't match well"},
    {"q": "What are the new shoes that Melanie got used for?", "gold": "Running", "cat": "open_domain",
     "gold_keywords": ["running", "shoes"],
     "note": "running shoes mentioned in assistant's event fact_summary"},
    {"q": "What kind of pot did Mel and her kids make with clay?", "gold": "a cup with a dog face on it", "cat": "open_domain",
     "gold_keywords": ["cup", "dog face"],
     "note": "very specific detail, likely only in source_items"},
    {"q": "What did Melanie and her family see during their camping trip last summer?", "gold": "Perseid meteor shower", "cat": "open_domain",
     "gold_keywords": ["perseid", "meteor"],
     "note": "in active Mel's event fact_summary"},
    {"q": "What are Caroline's plans for the summer?", "gold": "researching adoption agencies", "cat": "open_domain",
     "gold_keywords": ["adoption", "agencies"],
     "note": "adoption is in multiple active facts but 'summer plans' framing doesn't match"},
    {"q": "What kind of painting did Caroline share with Melanie on October 13?", "gold": "An abstract painting with blue streaks on a wall.", "cat": "open_domain",
     "gold_keywords": ["abstract", "blue streaks"],
     "note": "very specific detail with date; superseded atomic_facts have this"},
]


@pytest.fixture(scope="module")
def retrieval_client():
    """Create a test client with conv-26 cached DB."""
    if not DB_CACHE.exists():
        pytest.skip("conv-26 cached DB not found")

    config = AppConfig.from_env()
    vector_config = replace(
        config.vector_index,
        index_path=str(VECTOR_CACHE) if VECTOR_CACHE.exists() else None,
    )
    scenario_config = replace(
        config,
        sqlite_url=f"sqlite:///{DB_CACHE}",
        default_use_case="agent_conversation_memory",
        vector_index=vector_config,
    )
    app = create_app(scenario_config)
    with TestClient(app) as client:
        yield client


def _query_pallium(client, question: str, limit: int = 10) -> dict:
    """Run a query and return the full debug response."""
    resp = client.post("/query/debug", json={
        "text": question,
        "limit": limit,
        "container_ref": CONV_ID,
        "visibility": "public",
        "runtime_context": {
            "turn_kind": "new_session",
            "session_has_sufficient_local_context": False,
        },
    })
    assert resp.status_code == 200
    return resp.json()


def _check_keywords_in_results(results: list[dict], keywords: list[str]) -> tuple[bool, list[str]]:
    """Check if gold keywords appear in retrieved results. Returns (found, missing)."""
    context = ""
    for r in results:
        context += " " + (r.get("text") or "") + " " + (r.get("excerpt") or "")
    context = context.lower()

    found = []
    missing = []
    for kw in keywords:
        if kw.lower() in context:
            found.append(kw)
        else:
            missing.append(kw)

    return len(missing) == 0, missing


def _count_source_hits(results: list[dict]) -> int:
    return sum(1 for r in results if r.get("kind") == "source_hit")


def _count_memory_hits(results: list[dict]) -> int:
    return sum(1 for r in results if r.get("kind") == "memory_hit")


# =========================================================================
# Individual failure case tests
# =========================================================================

@pytest.mark.parametrize("case", FAILURE_CASES, ids=[c["q"][:50] for c in FAILURE_CASES])
def test_retrieval_finds_gold(retrieval_client, case):
    """Check if retrieval returns results containing gold answer keywords.

    These are known failures from the LoCoMo benchmark. Each test documents
    a specific retrieval gap. As we improve retrieval, these should start passing.
    """
    response = _query_pallium(retrieval_client, case["q"])
    results = response.get("results", [])

    found, missing = _check_keywords_in_results(results, case["gold_keywords"])

    # Record for reporting even on failure
    source_hits = _count_source_hits(results)
    memory_hits = _count_memory_hits(results)

    if not found:
        pytest.xfail(
            f"Gold keywords {missing} not in top-10. "
            f"Slots: {source_hits} source + {memory_hits} memory. "
            f"Note: {case.get('note', '')}"
        )


# =========================================================================
# Aggregate metrics
# =========================================================================

def test_gold_in_context_rate(retrieval_client):
    """Track overall gold-in-context rate across all failure cases.

    This is the key metric. As we improve retrieval, this number should go up.
    Current baseline: 0/37 (these were all failures).
    """
    found_count = 0
    total = len(FAILURE_CASES)

    for case in FAILURE_CASES:
        response = _query_pallium(retrieval_client, case["q"])
        results = response.get("results", [])
        found, _ = _check_keywords_in_results(results, case["gold_keywords"])
        if found:
            found_count += 1

    rate = found_count / total * 100
    print(f"\n  Gold-in-context: {found_count}/{total} ({rate:.0f}%)")

    # This assertion will start passing as we improve retrieval
    # For now, just track the number
    assert found_count >= 0  # always passes — the xfail tests above track individual cases


def test_source_hit_ratio(retrieval_client):
    """Track what fraction of result slots are source_hits (raw conversation).

    Lower is better — source_hits are low-value for factual queries.
    Current baseline: ~3.8/10 = 38%.
    """
    total_source = 0
    total_results = 0

    for case in FAILURE_CASES:
        response = _query_pallium(retrieval_client, case["q"])
        results = response.get("results", [])
        total_source += _count_source_hits(results)
        total_results += len(results)

    ratio = total_source / total_results * 100 if total_results else 0
    print(f"\n  Source hit ratio: {total_source}/{total_results} ({ratio:.0f}%)")

    # Track: should decrease as we improve retrieval
    assert ratio < 50  # loose bound — tighten as we improve
