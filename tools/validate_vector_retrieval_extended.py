"""Extended vector retrieval validation.

Tests:
1. build_embedding_text() curated output vs raw conversation text
2. Diverse query patterns (real user phrasing styles)
3. usearch round-trip with real vectors
4. End-to-end latency (embed + index + search)
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import onnxruntime as ort
from huggingface_hub import hf_hub_download
from tokenizers import Tokenizer
from usearch.index import Index

MODEL_REPO = "BAAI/bge-small-en-v1.5"
ONNX_FILE = "onnx/model.onnx"
TOKENIZER_FILE = "tokenizer.json"

# --- Globals set by init_model() ---
_session: ort.InferenceSession | None = None
_tokenizer: Tokenizer | None = None


def init_model():
    global _session, _tokenizer
    model_path = hf_hub_download(repo_id=MODEL_REPO, filename=ONNX_FILE)
    tokenizer_path = hf_hub_download(repo_id=MODEL_REPO, filename=TOKENIZER_FILE)
    _session = ort.InferenceSession(model_path)
    _tokenizer = Tokenizer.from_file(tokenizer_path)
    _tokenizer.enable_padding()
    _tokenizer.enable_truncation(max_length=512)


def embed(texts: list[str]) -> np.ndarray:
    encodings = _tokenizer.encode_batch(texts)
    max_len = max(len(e.ids) for e in encodings)
    input_ids = np.zeros((len(texts), max_len), dtype=np.int64)
    attention_mask = np.zeros((len(texts), max_len), dtype=np.int64)
    token_type_ids = np.zeros((len(texts), max_len), dtype=np.int64)
    for i, enc in enumerate(encodings):
        length = len(enc.ids)
        input_ids[i, :length] = enc.ids
        attention_mask[i, :length] = 1
    outputs = _session.run(
        None,
        {"input_ids": input_ids, "attention_mask": attention_mask, "token_type_ids": token_type_ids},
    )
    embeddings = outputs[0][:, 0, :]
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    return embeddings / np.maximum(norms, 1e-12)


def cosine_sim(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b))


# ===================================================================
# MEMORY CONTENT: raw conversation vs curated embedding text
# ===================================================================

# Scenario: catalog sync failure (task checkpoint)
RAW_CONVERSATION = (
    "Can you check why the catalog sync scheduled job keeps failing? "
    "The catalog sync investigation found that the scheduled job was failing "
    "because the API token used by the nightly batch process had expired. "
    "The token rotation policy was not applied to service accounts, so the "
    "sync stalled after the 90-day credential window closed. "
    "Current status: refreshed the service account token and restarted the "
    "sync job. 412 of 580 records processed so far. Remaining batches "
    "should complete by tomorrow morning."
)

CURATED_EMBEDDING_TEXT = (
    "Task: Catalog sync scheduled job failure investigation. "
    "Current state: Nightly batch API token expired after 90-day credential "
    "window. Token rotation policy not applied to service accounts. "
    "Refreshed token and restarted sync; 412 of 580 records processed. "
    "Next step: Monitor remaining batch completion by tomorrow morning."
)

MINIMAL_SUMMARY = (
    "Catalog sync job was failing due to expired API token. Fixed by "
    "refreshing the token. Sync in progress."
)

# Scenario: duplicate holds (investigation outcome)
RAW_CONVERSATION_2 = (
    "We are seeing duplicate hold entries in the reservation queue after "
    "the delayed catalog sync runs. Can you investigate? "
    "The root cause is a missing deduplication check in the hold queue "
    "consumer. When the catalog sync backlog cleared, it replayed events "
    "that were already processed, and the consumer inserted duplicate holds "
    "for the same patron-item pair. "
    "Resolution: Added a unique constraint on (patron_id, item_id, hold_window) "
    "in the reservation_holds table. Duplicate inserts now fail gracefully."
)

CURATED_EMBEDDING_TEXT_2 = (
    "Investigation: Duplicate hold entries in reservation queue after delayed "
    "catalog sync. Root cause: hold queue consumer lacked deduplication check. "
    "Backlog replay inserted duplicate holds for same patron-item pair. "
    "Resolution: unique constraint on patron_id, item_id, hold_window."
)

# Scenario: decision
RAW_CONVERSATION_3 = (
    "We need to decide how to handle reservation ordering when catalog sync "
    "is delayed. Should we use wall-clock time or the original event time? "
    "Decision: use event-time ordering instead of wall-clock ordering for "
    "reservation priority when catalog sync is delayed. Rationale: wall-clock "
    "ordering penalizes patrons whose requests were queued before the sync delay."
)

CURATED_EMBEDDING_TEXT_3 = (
    "Decision: Use event-time ordering for reservation priority during catalog "
    "sync delays. Rationale: wall-clock ordering penalizes patrons whose "
    "requests were queued before the delay."
)

ALL_MEMORIES = {
    "task-checkpoint-raw": RAW_CONVERSATION,
    "task-checkpoint-curated": CURATED_EMBEDDING_TEXT,
    "task-checkpoint-minimal": MINIMAL_SUMMARY,
    "investigation-raw": RAW_CONVERSATION_2,
    "investigation-curated": CURATED_EMBEDDING_TEXT_2,
    "decision-raw": RAW_CONVERSATION_3,
    "decision-curated": CURATED_EMBEDDING_TEXT_3,
}

# ===================================================================
# DIVERSE QUERY PATTERNS: how real users actually ask
# ===================================================================

DIVERSE_QUERIES = {
    "task-checkpoint": [
        # Temporal patterns
        ("temporal-recent",     "What was the last thing we looked at with catalog sync?"),
        ("temporal-before",     "Before we moved on, what was the sync status?"),
        # Conversational patterns
        ("conversational",      "Hey, remind me about the sync job situation"),
        ("casual",              "What's going on with that sync thing again?"),
        # Professional/formal
        ("formal",              "Could you summarize the current state of the catalog synchronization issue?"),
        ("status-request",      "Status update on the batch processing token issue?"),
        # Indirect/oblique
        ("indirect",            "I need to update the team on the nightly job progress"),
        ("oblique",             "Are we still waiting on something with the service accounts?"),
        # Question word variants
        ("how-question",        "How far along is the catalog sync recovery?"),
        ("who-question",        "Who was working on the expired token problem?"),
    ],
    "investigation": [
        ("temporal-recent",     "What did we find out about the duplicate holds?"),
        ("conversational",      "So the reservation queue duplicates -- what was the deal?"),
        ("formal",              "What was the root cause analysis for the hold queue issue?"),
        ("status-request",      "Is the duplicate hold problem resolved?"),
        ("indirect",            "I need to know if the reservation deduplication fix is in place"),
        ("how-question",        "How did the duplicate entries get into the hold queue?"),
    ],
    "decision": [
        ("temporal-recent",     "What did we decide about reservation ordering?"),
        ("conversational",      "So are we going with event-time or wall-clock for reservations?"),
        ("formal",              "What is the current ordering policy for delayed reservations?"),
        ("indirect",            "I need to implement the reservation priority logic -- which approach?"),
        ("why-question",        "Why did we choose event-time ordering over wall-clock?"),
        ("confirmation",        "We're using event-time ordering for reservations, right?"),
    ],
}


def test_1_curated_vs_raw():
    """Test whether curated embedding text discriminates better than raw conversation."""
    print("\n" + "=" * 80)
    print("TEST 1: CURATED vs RAW vs MINIMAL EMBEDDING TEXT")
    print("Does build_embedding_text() output embed better than raw conversation?")
    print("=" * 80)

    queries = [
        ("light-anchor",    "Where did things end up with the sync job?"),
        ("moderate",        "What's the status on the catalog sync failure?"),
        ("domain-specific", "Did the catalog sync token rotation get fixed?"),
    ]

    memory_variants = {
        "raw":     RAW_CONVERSATION,
        "curated": CURATED_EMBEDDING_TEXT,
        "minimal": MINIMAL_SUMMARY,
    }

    memory_vecs = {}
    for name, text in memory_variants.items():
        memory_vecs[name] = embed([text])[0]

    # Also embed the other memories as distractors
    distractor_vecs = {
        "investigation": embed([CURATED_EMBEDDING_TEXT_2])[0],
        "decision":      embed([CURATED_EMBEDDING_TEXT_3])[0],
    }

    print(f"\n{'Query':<55} {'Raw':>7} {'Curated':>9} {'Minimal':>9} {'Distractor-best':>16}")
    print("-" * 100)

    for level, query_text in queries:
        q_vec = embed([query_text])[0]
        raw_score = cosine_sim(q_vec, memory_vecs["raw"])
        curated_score = cosine_sim(q_vec, memory_vecs["curated"])
        minimal_score = cosine_sim(q_vec, memory_vecs["minimal"])
        dist_scores = [cosine_sim(q_vec, v) for v in distractor_vecs.values()]
        best_dist = max(dist_scores)

        best = max(raw_score, curated_score, minimal_score)
        markers = {
            raw_score: " *" if raw_score == best else "",
            curated_score: " *" if curated_score == best else "",
            minimal_score: " *" if minimal_score == best else "",
        }

        print(f"{query_text:<55} {raw_score:>6.4f}{markers[raw_score]} {curated_score:>7.4f}{markers[curated_score]} {minimal_score:>7.4f}{markers[minimal_score]} {best_dist:>14.4f}")

    # Repeat for investigation
    print(f"\n--- Investigation queries ---")
    inv_queries = [
        ("light",    "How did the duplicate issue turn out?"),
        ("moderate", "What was the root cause of the duplicate holds?"),
    ]
    inv_raw_vec = embed([RAW_CONVERSATION_2])[0]
    inv_curated_vec = embed([CURATED_EMBEDDING_TEXT_2])[0]

    print(f"{'Query':<55} {'Raw':>7} {'Curated':>9}")
    print("-" * 75)
    for level, q in inv_queries:
        qv = embed([q])[0]
        print(f"{q:<55} {cosine_sim(qv, inv_raw_vec):>7.4f} {cosine_sim(qv, inv_curated_vec):>7.4f}")


def test_2_diverse_queries():
    """Test diverse real-world query patterns."""
    print("\n" + "=" * 80)
    print("TEST 2: DIVERSE REAL-WORLD QUERY PATTERNS")
    print("How do different phrasing styles score against curated memory?")
    print("=" * 80)

    target_vecs = {
        "task-checkpoint": embed([CURATED_EMBEDDING_TEXT])[0],
        "investigation":   embed([CURATED_EMBEDDING_TEXT_2])[0],
        "decision":        embed([CURATED_EMBEDDING_TEXT_3])[0],
    }

    for target, queries in DIVERSE_QUERIES.items():
        print(f"\n--- Target: {target} ---")
        print(f"{'Style':<20} {'Query':<60} {'Target':>7} {'BestOther':>10} {'Margin':>8} {'Rank':>5}")
        print("-" * 115)

        for style, query_text in queries:
            qv = embed([query_text])[0]
            scores = {k: cosine_sim(qv, v) for k, v in target_vecs.items()}
            target_score = scores[target]
            other_scores = {k: v for k, v in scores.items() if k != target}
            best_other = max(other_scores.values())
            margin = target_score - best_other
            rank = 1 + sum(1 for v in scores.values() if v > target_score)
            marker = "OK" if rank == 1 else f"MISS(r={rank})"
            print(f"{style:<20} {query_text:<60} {target_score:>7.4f} {best_other:>10.4f} {margin:>+8.4f} {marker:>5}")


def test_3_usearch_roundtrip():
    """Test usearch index with real vectors."""
    print("\n" + "=" * 80)
    print("TEST 3: USEARCH ROUND-TRIP WITH REAL VECTORS")
    print("=" * 80)

    # Create index with real embeddings
    index = Index(ndim=384, metric="cos", dtype="f32")

    memories = {
        0: ("task-checkpoint", CURATED_EMBEDDING_TEXT),
        1: ("investigation",   CURATED_EMBEDDING_TEXT_2),
        2: ("decision",        CURATED_EMBEDDING_TEXT_3),
    }

    # Add memories
    vecs = embed([text for _, text in memories.values()])
    for key in memories:
        index.add(key, vecs[key].astype(np.float32))

    print(f"  Index size: {index.size} vectors, {384} dimensions")

    # Search with various queries
    test_queries = [
        ("light-task",    "Where did things end up with the sync job?",                "task-checkpoint"),
        ("light-invest",  "How did the duplicate issue turn out?",                      "investigation"),
        ("light-decision","What approach did we settle on for reservation ordering?",   "decision"),
        ("moderate-task", "What's the status on the catalog sync failure?",             "task-checkpoint"),
        ("domain-invest", "Did we fix the reservation queue duplicates?",               "investigation"),
    ]

    print(f"\n{'Query':<60} {'Expected':>16} {'Got':>16} {'Sim':>6} {'Match':>6}")
    print("-" * 110)

    for label, query_text, expected in test_queries:
        qv = embed([query_text])[0].astype(np.float32)
        results = index.search(qv, 3, exact=True)
        top_key = int(results.keys[0])
        top_sim = float(1.0 - results.distances[0])  # usearch cos metric returns distance
        got_label = memories[top_key][0]
        match = "OK" if got_label == expected else "MISS"
        print(f"{query_text:<60} {expected:>16} {got_label:>16} {top_sim:>6.4f} {match:>6}")

        # Show all results
        for rank in range(min(3, len(results.keys))):
            k = int(results.keys[rank])
            sim = float(1.0 - results.distances[rank])
            print(f"  rank {rank+1}: {memories[k][0]:>16}  sim={sim:.4f}")


def test_4_latency():
    """Test embedding and search latency."""
    print("\n" + "=" * 80)
    print("TEST 4: LATENCY")
    print("=" * 80)

    # Single text embedding
    times = []
    for _ in range(20):
        t0 = time.perf_counter()
        embed(["What's the status on the catalog sync failure?"])
        times.append((time.perf_counter() - t0) * 1000)
    print(f"  Single embed:  mean={np.mean(times):.1f}ms  p50={np.median(times):.1f}ms  p95={np.percentile(times, 95):.1f}ms")

    # Batch embedding (5 texts)
    batch = [
        "Where did things end up with the sync job?",
        "How did the duplicate issue turn out?",
        "Any takeaways from the sync incidents?",
        "What approach did we settle on for reservation ordering?",
        "What actually mattered with the checkout failures?",
    ]
    times = []
    for _ in range(10):
        t0 = time.perf_counter()
        embed(batch)
        times.append((time.perf_counter() - t0) * 1000)
    print(f"  Batch(5) embed: mean={np.mean(times):.1f}ms  p50={np.median(times):.1f}ms  p95={np.percentile(times, 95):.1f}ms")

    # Batch embedding (20 texts)
    batch20 = batch * 4
    times = []
    for _ in range(5):
        t0 = time.perf_counter()
        embed(batch20)
        times.append((time.perf_counter() - t0) * 1000)
    print(f"  Batch(20) embed: mean={np.mean(times):.1f}ms  p50={np.median(times):.1f}ms  p95={np.percentile(times, 95):.1f}ms")

    # usearch search latency
    index = Index(ndim=384, metric="cos", dtype="f32")
    # Add 100 random vectors
    for i in range(100):
        index.add(i, np.random.randn(384).astype(np.float32))

    qv = np.random.randn(384).astype(np.float32)
    times = []
    for _ in range(100):
        t0 = time.perf_counter()
        index.search(qv, 10, exact=True)
        times.append((time.perf_counter() - t0) * 1000)
    print(f"  usearch(100 vecs, k=10): mean={np.mean(times):.3f}ms  p50={np.median(times):.3f}ms")

    # 1000 vectors
    index2 = Index(ndim=384, metric="cos", dtype="f32")
    for i in range(1000):
        index2.add(i, np.random.randn(384).astype(np.float32))
    times = []
    for _ in range(100):
        t0 = time.perf_counter()
        index2.search(qv, 10, exact=True)
        times.append((time.perf_counter() - t0) * 1000)
    print(f"  usearch(1000 vecs, k=10): mean={np.mean(times):.3f}ms  p50={np.median(times):.3f}ms")


if __name__ == "__main__":
    print("=" * 80)
    print("EXTENDED VECTOR RETRIEVAL VALIDATION")
    print("=" * 80)
    init_model()
    test_1_curated_vs_raw()
    test_2_diverse_queries()
    test_3_usearch_roundtrip()
    test_4_latency()
    print("\n" + "=" * 80)
    print("ALL TESTS COMPLETE")
    print("=" * 80)
