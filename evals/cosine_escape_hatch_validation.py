"""Validate cosine escape hatch assumptions for the retrieval relevance floor.

Uses real BGE-small-en-v1.5 embeddings to test whether a cosine similarity
threshold can safely allow vector-only matches (no lexical overlap) without
injecting irrelevant memories.

Tests three core assumptions:
  A1: Cross-vocabulary paraphrases score >= 0.70 cosine
  A2: Unrelated memories in diverse containers stay <= 0.65
  A3: Closely related but distinct topics are distinguishable

Run: python -m evals.cosine_escape_hatch_validation
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass

import numpy as np

from providers.embedding.onnx_provider import OnnxEmbeddingProvider


@dataclass
class SimilarityResult:
    query: str
    target_label: str
    target_sim: float
    best_other_label: str
    best_other_sim: float
    margin: float


def _cosine(a: list[float], b: list[float]) -> float:
    return float(np.dot(a, b))


def _embed_all(provider: OnnxEmbeddingProvider, texts: dict[str, str]) -> dict[str, list[float]]:
    labels = list(texts.keys())
    raw_texts = [texts[k] for k in labels]
    vectors = provider.embed(raw_texts)
    return dict(zip(labels, vectors))


def _score_query(
    query_vec: list[float],
    target_label: str,
    memory_vecs: dict[str, list[float]],
) -> SimilarityResult:
    sims = {label: _cosine(query_vec, vec) for label, vec in memory_vecs.items()}
    target_sim = sims[target_label]
    others = {k: v for k, v in sims.items() if k != target_label}
    best_other_label = max(others, key=others.get) if others else ""
    best_other_sim = others[best_other_label] if others else 0.0
    return SimilarityResult(
        query="",
        target_label=target_label,
        target_sim=round(target_sim, 4),
        best_other_label=best_other_label,
        best_other_sim=round(best_other_sim, 4),
        margin=round(target_sim - best_other_sim, 4),
    )


# ---------------------------------------------------------------------------
# Test 1: Cross-vocabulary paraphrase similarity
# ---------------------------------------------------------------------------

CROSS_VOCAB_MEMORIES = {
    "event_sourcing": "Decision: Use event sourcing for the audit trail. Rationale: provides immutable history of all state changes for compliance.",
    "token_rotation": "Decision: Rotate service credentials every 90 days. Rationale: limits exposure window if a token is compromised.",
    "sync_failure": "Investigation outcome: Nightly batch sync fails when catalog entries exceed 10k rows. Key finding: the bulk insert times out at the default 30-second connection limit.",
    "cache_strategy": "Decision: Use Redis with 15-minute TTL for session data. Rationale: balances freshness with database load reduction.",
    "deploy_pipeline": "Decision: Blue-green deployment via ArgoCD for zero-downtime releases. Rationale: allows instant rollback if health checks fail.",
}

CROSS_VOCAB_QUERIES = {
    "what approach did we pick for tracking changes?": "event_sourcing",
    "how often do we refresh the service auth keys?": "token_rotation",
    "what was the issue with the scheduled data import?": "sync_failure",
    "what are we doing for temporary user data storage?": "cache_strategy",
    "how do we ship new versions without downtime?": "deploy_pipeline",
}


def test_cross_vocabulary(provider: OnnxEmbeddingProvider) -> list[SimilarityResult]:
    memory_vecs = _embed_all(provider, CROSS_VOCAB_MEMORIES)
    results = []
    for query_text, target_label in CROSS_VOCAB_QUERIES.items():
        query_vec = provider.embed([query_text])[0]
        r = _score_query(query_vec, target_label, memory_vecs)
        r.query = query_text
        results.append(r)
    return results


# ---------------------------------------------------------------------------
# Test 2: Diverse container noise floor
# ---------------------------------------------------------------------------

DIVERSE_MEMORIES = {
    "event_sourcing": "Decision: Use event sourcing architecture for audit compliance and state tracking.",
    "connection_pool": "Decision: Configure PostgreSQL connection pooling with PgBouncer at 50 max connections.",
    "oauth_flow": "Decision: Implement OAuth2 PKCE flow for mobile app authentication.",
    "k8s_autoscaler": "Decision: Tune Kubernetes horizontal pod autoscaler with 70% CPU target and 2-minute stabilization.",
    "redis_cache": "Decision: Redis cache invalidation uses tag-based purging with 10-minute TTL fallback.",
    "graphql_federation": "Decision: GraphQL schema federation across catalog, inventory, and user services.",
    "apm_instrumentation": "Investigation outcome: Datadog APM instrumentation shows p99 latency spike in checkout flow. Key finding: N+1 query in cart item resolution.",
    "terraform_state": "Decision: Terraform state locking with S3 backend and DynamoDB lock table.",
    "snapshot_testing": "Decision: Jest snapshot testing for React component regression. Rationale: catches unintended UI changes without manual visual review.",
    "dlq_retry": "Decision: RabbitMQ dead-letter queue with exponential backoff retry up to 3 attempts.",
}

DIVERSE_QUERIES = {
    "what was the plan for scaling pods automatically?": "k8s_autoscaler",
    "how are we handling expired cache entries?": "redis_cache",
    "what testing approach did we go with for the frontend?": "snapshot_testing",
    "what did we find about the slow checkout?": "apm_instrumentation",
    "how do we manage infrastructure config state?": "terraform_state",
}


def test_diverse_container(provider: OnnxEmbeddingProvider) -> list[SimilarityResult]:
    memory_vecs = _embed_all(provider, DIVERSE_MEMORIES)
    results = []
    for query_text, target_label in DIVERSE_QUERIES.items():
        query_vec = provider.embed([query_text])[0]
        r = _score_query(query_vec, target_label, memory_vecs)
        r.query = query_text
        results.append(r)
    return results


# ---------------------------------------------------------------------------
# Test 3: Near-miss topic discrimination
# ---------------------------------------------------------------------------

NEAR_MISS_MEMORIES = {
    "db_indexing": "Decision: Add composite index on (tenant_id, created_at) for read query performance. Rationale: the most common dashboard query filters by tenant and sorts by date.",
    "db_migration": "Decision: Use Alembic for database schema migration with version-controlled upgrade scripts. Rationale: reproducible schema changes across environments.",
    "db_pooling": "Decision: Set connection pool size to 20 with 5-second timeout for write-heavy ingestion service. Rationale: prevents connection exhaustion during batch imports.",
    "api_rate_limit": "Decision: API rate limiting at 100 requests per minute per tenant with token bucket algorithm.",
    "api_versioning": "Decision: API versioning via URL path prefix /v1/ /v2/ with 6-month deprecation window.",
    "api_auth": "Decision: API authentication via JWT with RS256 signing and 15-minute token expiry.",
}

NEAR_MISS_QUERIES = {
    "what did we decide about making reads faster?": ("db_indexing", "db_migration"),
    "how are we handling schema changes?": ("db_migration", "db_indexing"),
    "what was the write capacity approach?": ("db_pooling", "db_indexing"),
    "how do we control request volume per customer?": ("api_rate_limit", "api_versioning"),
    "what's the approach for breaking API changes?": ("api_versioning", "api_rate_limit"),
}


def test_near_miss(provider: OnnxEmbeddingProvider) -> list[dict]:
    memory_vecs = _embed_all(provider, NEAR_MISS_MEMORIES)
    results = []
    for query_text, (target, near_miss) in NEAR_MISS_QUERIES.items():
        query_vec = provider.embed([query_text])[0]
        target_sim = _cosine(query_vec, memory_vecs[target])
        near_miss_sim = _cosine(query_vec, memory_vecs[near_miss])
        # Find best unrelated (not target, not near_miss)
        others = {k: _cosine(query_vec, v) for k, v in memory_vecs.items() if k not in (target, near_miss)}
        best_distant = max(others.values()) if others else 0.0
        results.append({
            "query": query_text,
            "target": target,
            "target_sim": round(target_sim, 4),
            "near_miss": near_miss,
            "near_miss_sim": round(near_miss_sim, 4),
            "target_vs_near_miss_margin": round(target_sim - near_miss_sim, 4),
            "best_distant_sim": round(best_distant, 4),
            "target_vs_distant_margin": round(target_sim - best_distant, 4),
        })
    return results


# ---------------------------------------------------------------------------
# Test 4: Threshold sweep
# ---------------------------------------------------------------------------

THRESHOLDS = [0.55, 0.60, 0.65, 0.68, 0.70, 0.72, 0.75, 0.80]


def threshold_sweep(all_results: list[SimilarityResult]) -> list[dict]:
    sweep = []
    for t in THRESHOLDS:
        tp = sum(1 for r in all_results if r.target_sim >= t)
        fn = sum(1 for r in all_results if r.target_sim < t)
        fp = sum(1 for r in all_results if r.best_other_sim >= t)
        recall = tp / len(all_results) if all_results else 0
        precision = tp / (tp + fp) if (tp + fp) > 0 else 1.0
        sweep.append({
            "threshold": t,
            "recall": round(recall, 3),
            "precision": round(precision, 3),
            "true_positives": tp,
            "false_negatives": fn,
            "false_positives": fp,
        })
    return sweep


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("Loading ONNX embedding provider (BGE-small-en-v1.5)...")
    provider = OnnxEmbeddingProvider(model="BAAI/bge-small-en-v1.5")
    print(f"Model: {provider.model_name()}, dimensions: {provider.dimensions()}\n")

    report: dict = {}

    # Test 1
    print("=" * 70)
    print("TEST 1: Cross-vocabulary paraphrase similarity")
    print("=" * 70)
    cross_results = test_cross_vocabulary(provider)
    for r in cross_results:
        status = "PASS" if r.target_sim >= 0.70 else ("WARN" if r.target_sim >= 0.65 else "FAIL")
        print(f"  [{status}] target={r.target_sim:.3f}  best_other={r.best_other_sim:.3f}  margin={r.margin:+.3f}")
        print(f"         {r.query}")
        print(f"         target={r.target_label}  best_other={r.best_other_label}")
    avg_target = np.mean([r.target_sim for r in cross_results])
    avg_margin = np.mean([r.margin for r in cross_results])
    print(f"\n  Avg target sim: {avg_target:.3f}")
    print(f"  Avg margin:     {avg_margin:+.3f}")
    passes_a1 = all(r.target_sim >= 0.65 for r in cross_results)
    print(f"  A1 (target >= 0.65): {'PASS' if passes_a1 else 'FAIL'}")
    report["test1_cross_vocabulary"] = {
        "results": [{"query": r.query, "target": r.target_label, "target_sim": r.target_sim, "best_other": r.best_other_label, "best_other_sim": r.best_other_sim, "margin": r.margin} for r in cross_results],
        "avg_target_sim": round(float(avg_target), 4),
        "avg_margin": round(float(avg_margin), 4),
        "assumption_a1_pass": passes_a1,
    }

    # Test 2
    print(f"\n{'=' * 70}")
    print("TEST 2: Diverse container noise floor")
    print("=" * 70)
    diverse_results = test_diverse_container(provider)
    for r in diverse_results:
        noise_ok = r.best_other_sim <= 0.65
        target_ok = r.target_sim >= 0.70
        status = "PASS" if (noise_ok and target_ok) else ("WARN" if noise_ok else "FAIL")
        print(f"  [{status}] target={r.target_sim:.3f}  best_other={r.best_other_sim:.3f}  margin={r.margin:+.3f}")
        print(f"         {r.query}")
        print(f"         target={r.target_label}  best_other={r.best_other_label}")
    max_other = max(r.best_other_sim for r in diverse_results)
    passes_a2 = max_other <= 0.65
    print(f"\n  Max non-target sim: {max_other:.3f}")
    print(f"  A2 (max other <= 0.65): {'PASS' if passes_a2 else 'FAIL'}")
    report["test2_diverse_container"] = {
        "results": [{"query": r.query, "target": r.target_label, "target_sim": r.target_sim, "best_other": r.best_other_label, "best_other_sim": r.best_other_sim, "margin": r.margin} for r in diverse_results],
        "max_non_target_sim": round(float(max_other), 4),
        "assumption_a2_pass": passes_a2,
    }

    # Test 3
    print(f"\n{'=' * 70}")
    print("TEST 3: Near-miss topic discrimination")
    print("=" * 70)
    near_results = test_near_miss(provider)
    for r in near_results:
        correct_rank = r["target_sim"] > r["near_miss_sim"]
        status = "PASS" if correct_rank else "FAIL"
        print(f"  [{status}] target={r['target_sim']:.3f}  near_miss={r['near_miss_sim']:.3f}  margin={r['target_vs_near_miss_margin']:+.3f}")
        print(f"         {r['query']}")
        print(f"         target={r['target']}  near_miss={r['near_miss']}")
    passes_a3 = all(r["target_sim"] > r["near_miss_sim"] for r in near_results)
    avg_near_margin = np.mean([r["target_vs_near_miss_margin"] for r in near_results])
    print(f"\n  Avg target vs near-miss margin: {avg_near_margin:+.3f}")
    print(f"  A3 (target > near_miss for all): {'PASS' if passes_a3 else 'FAIL'}")
    report["test3_near_miss"] = {
        "results": near_results,
        "avg_near_miss_margin": round(float(avg_near_margin), 4),
        "assumption_a3_pass": passes_a3,
    }

    # Test 4: Threshold sweep
    print(f"\n{'=' * 70}")
    print("TEST 4: Threshold sweep (combined test 1 + test 2)")
    print("=" * 70)
    all_sim_results = cross_results + diverse_results
    sweep = threshold_sweep(all_sim_results)
    print(f"  {'Threshold':>10} {'Recall':>8} {'Precision':>10} {'TP':>4} {'FN':>4} {'FP':>4}")
    print(f"  {'-'*10} {'-'*8} {'-'*10} {'-'*4} {'-'*4} {'-'*4}")
    for s in sweep:
        marker = " <--" if s["threshold"] == 0.70 else ""
        print(f"  {s['threshold']:>10.2f} {s['recall']:>8.3f} {s['precision']:>10.3f} {s['true_positives']:>4} {s['false_negatives']:>4} {s['false_positives']:>4}{marker}")
    report["test4_threshold_sweep"] = sweep

    # Summary
    print(f"\n{'=' * 70}")
    print("SUMMARY")
    print("=" * 70)
    print(f"  A1 (cross-vocab target >= 0.65):    {'PASS' if passes_a1 else 'FAIL'}")
    print(f"  A2 (diverse noise <= 0.65):          {'PASS' if passes_a2 else 'FAIL'}")
    print(f"  A3 (near-miss discrimination):       {'PASS' if passes_a3 else 'FAIL'}")

    recommended = None
    for s in sweep:
        if s["recall"] >= 0.80 and s["precision"] >= 0.90:
            recommended = s["threshold"]
            break
    if recommended:
        print(f"\n  Recommended threshold: {recommended} (first with recall >= 0.80, precision >= 0.90)")
    else:
        print("\n  No threshold meets recall >= 0.80 AND precision >= 0.90")
        best_f1 = max(sweep, key=lambda s: 2 * s["recall"] * s["precision"] / (s["recall"] + s["precision"]) if (s["recall"] + s["precision"]) > 0 else 0)
        print(f"  Best F1 threshold: {best_f1['threshold']} (recall={best_f1['recall']}, precision={best_f1['precision']})")

    report["summary"] = {
        "a1_pass": passes_a1,
        "a2_pass": passes_a2,
        "a3_pass": passes_a3,
        "recommended_threshold": recommended,
    }

    print(json.dumps(report, indent=2), file=open("evals/cosine_escape_hatch_validation_results.json", "w"))
    print(f"\nFull results written to evals/cosine_escape_hatch_validation_results.json")


if __name__ == "__main__":
    main()
