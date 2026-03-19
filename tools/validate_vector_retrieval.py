"""Vector retrieval validation script.

Downloads BGE-small-en-v1.5 ONNX model and validates embedding quality
against benchmark scenarios PLUS realistic query variants. Tests a gradient
from pure-abstract queries (zero domain content) through lightly-anchored
queries (1-2 domain words) to moderately-specific queries.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import onnxruntime as ort
from huggingface_hub import hf_hub_download
from tokenizers import Tokenizer


MODEL_REPO = "BAAI/bge-small-en-v1.5"
ONNX_FILE = "onnx/model.onnx"
TOKENIZER_FILE = "tokenizer.json"
SCENARIOS_PATH = Path("evals/vector_retrieval/scenarios.json")


def download_model() -> tuple[str, str]:
    print(f"Downloading {MODEL_REPO}...")
    model_path = hf_hub_download(repo_id=MODEL_REPO, filename=ONNX_FILE)
    tokenizer_path = hf_hub_download(repo_id=MODEL_REPO, filename=TOKENIZER_FILE)
    return model_path, tokenizer_path


def embed_texts(texts: list[str], session: ort.InferenceSession, tokenizer: Tokenizer) -> np.ndarray:
    encodings = tokenizer.encode_batch(texts)
    max_len = max(len(e.ids) for e in encodings)
    input_ids = np.zeros((len(texts), max_len), dtype=np.int64)
    attention_mask = np.zeros((len(texts), max_len), dtype=np.int64)
    token_type_ids = np.zeros((len(texts), max_len), dtype=np.int64)
    for i, enc in enumerate(encodings):
        length = len(enc.ids)
        input_ids[i, :length] = enc.ids
        attention_mask[i, :length] = 1
    outputs = session.run(
        None,
        {"input_ids": input_ids, "attention_mask": attention_mask, "token_type_ids": token_type_ids},
    )
    embeddings = outputs[0][:, 0, :]
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    return embeddings / np.maximum(norms, 1e-12)


def cosine_sim(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b))


# ---------------------------------------------------------------------------
# Memory texts: curated per-type embedding text (what build_embedding_text
# would produce) — one per scenario
# ---------------------------------------------------------------------------
MEMORY_TEXTS = {
    "task-checkpoint": (
        "Catalog sync scheduled job was failing because the nightly batch API "
        "token expired after 90-day credential window. Token rotation policy "
        "was not applied to service accounts. Refreshed token and restarted "
        "sync; 412 of 580 records processed."
    ),
    "investigation": (
        "Root cause of duplicate hold entries: the reservation queue consumer "
        "processed the backlog from the delayed catalog sync but did not "
        "deduplicate against existing holds. Adding a unique constraint on "
        "patron plus item within the same hold window resolved the duplicates."
    ),
    "pattern": (
        "Recurring pattern across sync-related incidents: when nightly batch "
        "jobs accumulate a backlog larger than 200 records, downstream queue "
        "consumers fail to handle the burst and produce duplicates or stale "
        "state. Introducing batch-size caps at the producer level prevents "
        "cascading failures."
    ),
    "decision": (
        "Decision: use event-time ordering instead of wall-clock ordering for "
        "reservation priority when catalog sync is delayed. Rationale: "
        "wall-clock ordering penalizes patrons whose requests were queued "
        "before the sync delay."
    ),
    "significance": (
        "Investigation outcome: the branch checkout terminal failures were "
        "caused by a race condition between the hold-release job and the "
        "checkout transaction. The hold-release job deleted the hold record "
        "before checkout committed, causing a foreign-key violation."
    ),
}


# ---------------------------------------------------------------------------
# Query variants: gradient from abstract to domain-anchored
# Each group targets ONE memory text.
# ---------------------------------------------------------------------------
QUERY_VARIANTS = [
    {
        "target": "task-checkpoint",
        "label": "catalog sync checkpoint",
        "variants": [
            ("pure-abstract",       "Where did things end up with that?"),
            ("light-anchor",        "Where did things end up with the sync job?"),
            ("moderate-anchor",     "What's the status on the catalog sync failure?"),
            ("domain-specific",     "Did the catalog sync token rotation get fixed?"),
            ("near-lexical",        "What happened with the expired API token on the nightly batch?"),
        ],
    },
    {
        "target": "investigation",
        "label": "duplicate holds investigation",
        "variants": [
            ("pure-abstract",       "How did it turn out?"),
            ("light-anchor",        "How did the duplicate issue turn out?"),
            ("moderate-anchor",     "What was the root cause of the duplicate holds?"),
            ("domain-specific",     "Did we fix the reservation queue duplicates?"),
            ("near-lexical",        "Why were there duplicate hold entries after the delayed catalog sync?"),
        ],
    },
    {
        "target": "pattern",
        "label": "batch processing pattern",
        "variants": [
            ("pure-abstract",       "Any takeaways worth noting?"),
            ("light-anchor",        "Any takeaways from the sync incidents?"),
            ("moderate-anchor",     "What patterns did we see in the batch processing failures?"),
            ("domain-specific",     "Is there a recurring issue with nightly batch backlogs?"),
            ("near-lexical",        "When batch jobs accumulate a backlog do downstream consumers fail?"),
        ],
    },
    {
        "target": "decision",
        "label": "reservation ordering decision",
        "variants": [
            ("pure-abstract",       "What approach did we settle on?"),
            ("light-anchor",        "What approach did we settle on for reservation ordering?"),
            ("moderate-anchor",     "How are we handling priority when catalog sync is delayed?"),
            ("domain-specific",     "Are we using event-time or wall-clock ordering for reservations?"),
            ("near-lexical",        "Did we decide on event-time ordering for reservation priority during sync delays?"),
        ],
    },
    {
        "target": "significance",
        "label": "checkout terminal race condition",
        "variants": [
            ("pure-abstract",       "What actually mattered there?"),
            ("light-anchor",        "What actually mattered with the checkout failures?"),
            ("moderate-anchor",     "What caused the branch checkout terminal to fail?"),
            ("domain-specific",     "Was there a race condition with the hold-release job?"),
            ("near-lexical",        "Did the hold-release job delete records before checkout committed?"),
        ],
    },
]


def run_validation():
    print("=" * 80)
    print("VECTOR RETRIEVAL VALIDATION -- Query Realism Gradient")
    print("=" * 80)

    model_path, tokenizer_path = download_model()
    print("\nLoading ONNX model...")
    session = ort.InferenceSession(model_path)
    tokenizer = Tokenizer.from_file(tokenizer_path)
    tokenizer.enable_padding()
    tokenizer.enable_truncation(max_length=512)

    dims = embed_texts(["test"], session, tokenizer).shape[1]
    print(f"  Dimensions: {dims}")

    # Embed all memory texts
    memory_keys = list(MEMORY_TEXTS.keys())
    memory_txts = [MEMORY_TEXTS[k] for k in memory_keys]
    t0 = time.perf_counter()
    memory_vecs = embed_texts(memory_txts, session, tokenizer)
    t1 = time.perf_counter()
    print(f"  Memory embedding: {(t1-t0)*1000:.1f}ms for {len(memory_txts)} texts")

    # -----------------------------------------------------------------------
    # Test 1: Per-group gradient analysis
    # -----------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("TEST 1: QUERY REALISM GRADIENT")
    print("Each row shows cosine similarity to the TARGET memory vs BEST non-target.")
    print("=" * 80)

    all_results = []

    for group in QUERY_VARIANTS:
        target_key = group["target"]
        target_idx = memory_keys.index(target_key)
        print(f"\n--- Target: {group['label']} ({target_key}) ---")
        print(f"{'Level':<20} {'Query':<60} {'Target':>7} {'BestOther':>10} {'Margin':>8} {'Rank':>5}")
        print("-" * 115)

        for level, query_text in group["variants"]:
            q_vec = embed_texts([query_text], session, tokenizer)[0]

            # Score against all memories
            scores = {}
            for j, mk in enumerate(memory_keys):
                scores[mk] = cosine_sim(q_vec, memory_vecs[j])

            target_score = scores[target_key]
            other_scores = {k: v for k, v in scores.items() if k != target_key}
            best_other_key = max(other_scores, key=other_scores.get)
            best_other_score = other_scores[best_other_key]
            margin = target_score - best_other_score

            # Rank: 1 = target is the best match
            rank = 1 + sum(1 for v in scores.values() if v > target_score)

            marker = "OK" if rank == 1 else f"MISS(rank={rank})"
            print(f"{level:<20} {query_text:<60} {target_score:>7.4f} {best_other_score:>10.4f} {margin:>+8.4f} {marker:>5}")

            all_results.append({
                "group": group["label"],
                "target": target_key,
                "level": level,
                "query": query_text,
                "target_score": target_score,
                "best_other_score": best_other_score,
                "margin": margin,
                "rank": rank,
            })

    # -----------------------------------------------------------------------
    # Test 2: Summary by realism level
    # -----------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("TEST 2: SUMMARY BY REALISM LEVEL")
    print("=" * 80)

    levels = ["pure-abstract", "light-anchor", "moderate-anchor", "domain-specific", "near-lexical"]
    for level in levels:
        level_results = [r for r in all_results if r["level"] == level]
        rank1_count = sum(1 for r in level_results if r["rank"] == 1)
        avg_margin = np.mean([r["margin"] for r in level_results])
        avg_target = np.mean([r["target_score"] for r in level_results])
        print(f"  {level:<20}  rank-1={rank1_count}/{len(level_results)}  avg_margin={avg_margin:+.4f}  avg_target_sim={avg_target:.4f}")

    # -----------------------------------------------------------------------
    # Test 3: Threshold analysis on realistic queries (light-anchor+)
    # -----------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("TEST 3: THRESHOLD ANALYSIS (light-anchor and above)")
    print("=" * 80)

    realistic_results = [r for r in all_results if r["level"] != "pure-abstract"]
    relevant_scores = [r["target_score"] for r in realistic_results]
    # For irrelevant: use best_other_score as proxy for "would this create a false positive?"
    irrelevant_scores = [r["best_other_score"] for r in realistic_results]

    for threshold in [0.3, 0.35, 0.4, 0.45, 0.5, 0.55, 0.6, 0.65, 0.7]:
        tp = sum(1 for s in relevant_scores if s >= threshold)
        fp = sum(1 for s in irrelevant_scores if s >= threshold)
        recall = tp / len(relevant_scores)
        print(f"  threshold={threshold:.2f}: recall={recall:.2f}  FP_risk={fp}/{len(irrelevant_scores)}")

    # -----------------------------------------------------------------------
    # Test 4: Cross-memory confusion matrix for light-anchor queries
    # -----------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("TEST 4: CROSS-MEMORY SCORES FOR LIGHT-ANCHOR QUERIES")
    print("(Shows whether light domain hints are enough for discrimination)")
    print("=" * 80)

    light_results = [r for r in all_results if r["level"] == "light-anchor"]
    print(f"\n{'Query target':<25} ", end="")
    for mk in memory_keys:
        print(f"{mk:>15}", end="")
    print(f"  {'Rank':>5}")

    for r in light_results:
        q_vec = embed_texts([r["query"]], session, tokenizer)[0]
        print(f"{r['target']:<25} ", end="")
        scores = []
        for j, mk in enumerate(memory_keys):
            s = cosine_sim(q_vec, memory_vecs[j])
            scores.append(s)
            marker = " *" if mk == r["target"] else ""
            print(f"{s:>13.4f}{marker}", end="")
        target_idx = memory_keys.index(r["target"])
        rank = 1 + sum(1 for s in scores if s > scores[target_idx])
        print(f"  {rank:>5}")

    print("\n" + "=" * 80)
    print("DONE")
    print("=" * 80)


if __name__ == "__main__":
    run_validation()
