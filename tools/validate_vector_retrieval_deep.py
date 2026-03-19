"""Deeper validation: implications for write and query paths.

Tests:
1. BGE instruction prefix — BGE models are designed with a query prefix
   "Represent this sentence for searching relevant passages: "
   Does using it improve discrimination?
2. Shorter vs longer embedding text — test a single-field summary vs
   the multi-field concatenation
3. Would embedding raw SourceItem content add value over memory-only?
4. Query expansion with thread context — if we prepend "regarding catalog sync:"
   to an abstract query, does it help?
"""

from __future__ import annotations

import numpy as np
import onnxruntime as ort
from huggingface_hub import hf_hub_download
from tokenizers import Tokenizer

MODEL_REPO = "BAAI/bge-small-en-v1.5"
ONNX_FILE = "onnx/model.onnx"
TOKENIZER_FILE = "tokenizer.json"

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


def sim(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b))


# --- Memory text variants ---

MEMORIES = {
    "task-checkpoint": {
        "multi-field": (
            "Task: Catalog sync scheduled job failure investigation. "
            "Current state: Nightly batch API token expired after 90-day credential "
            "window. Token rotation policy not applied to service accounts. "
            "Refreshed token and restarted sync; 412 of 580 records processed. "
            "Next step: Monitor remaining batch completion by tomorrow morning."
        ),
        "summary-only": (
            "Catalog sync job was failing because the nightly batch API token "
            "expired. Token rotation was not applied to service accounts. "
            "Refreshed token, sync in progress."
        ),
        "key-sentence": (
            "Catalog sync nightly batch API token expired after 90-day window; "
            "refreshed and restarted, 412 of 580 processed."
        ),
        "raw-source": (
            "The catalog sync investigation found that the scheduled job was failing "
            "because the API token used by the nightly batch process had expired. "
            "The token rotation policy was not applied to service accounts, so the "
            "sync stalled after the 90-day credential window closed."
        ),
    },
    "investigation": {
        "multi-field": (
            "Investigation: Duplicate hold entries in reservation queue after delayed "
            "catalog sync. Root cause: hold queue consumer lacked deduplication check. "
            "Backlog replay inserted duplicate holds for same patron-item pair. "
            "Resolution: unique constraint on patron_id, item_id, hold_window."
        ),
        "summary-only": (
            "Duplicate holds caused by missing deduplication in queue consumer. "
            "Backlog replay created duplicates. Fixed with unique constraint."
        ),
        "key-sentence": (
            "Duplicate hold entries from missing deduplication in reservation "
            "queue consumer; fixed with unique constraint on patron-item-window."
        ),
        "raw-source": (
            "The root cause is a missing deduplication check in the hold queue "
            "consumer. When the catalog sync backlog cleared, it replayed events "
            "that were already processed, and the consumer inserted duplicate holds "
            "for the same patron-item pair."
        ),
    },
    "decision": {
        "multi-field": (
            "Decision: Use event-time ordering for reservation priority during "
            "catalog sync delays. Rationale: wall-clock ordering penalizes patrons "
            "whose requests were queued before the delay."
        ),
        "summary-only": (
            "Using event-time ordering instead of wall-clock for reservation "
            "priority when catalog sync is delayed."
        ),
        "key-sentence": (
            "Event-time ordering for reservation priority during sync delays; "
            "wall-clock penalizes pre-delay patrons."
        ),
        "raw-source": (
            "Decision: use event-time ordering instead of wall-clock ordering for "
            "reservation priority when catalog sync is delayed. Rationale: wall-clock "
            "ordering penalizes patrons whose requests were queued before the sync delay."
        ),
    },
}

# --- Queries at different abstraction levels ---
QUERIES = {
    "task-checkpoint": [
        ("pure-abstract",   "Where did things end up with that?"),
        ("light-anchor",    "Where did things end up with the sync job?"),
        ("moderate",        "What's the status on the catalog sync failure?"),
    ],
    "investigation": [
        ("pure-abstract",   "How did it turn out?"),
        ("light-anchor",    "How did the duplicate issue turn out?"),
        ("moderate",        "What was the root cause of the duplicate holds?"),
    ],
    "decision": [
        ("pure-abstract",   "What approach did we settle on?"),
        ("light-anchor",    "What approach did we settle on for reservation ordering?"),
        ("moderate",        "How are we handling priority when catalog sync is delayed?"),
    ],
}

BGE_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


def test_1_bge_prefix():
    """Does the BGE retrieval instruction prefix improve discrimination?"""
    print("\n" + "=" * 80)
    print("TEST 1: BGE INSTRUCTION PREFIX")
    print("BGE models recommend prefixing queries with an instruction for retrieval.")
    print("Does it help?")
    print("=" * 80)

    # Use multi-field memory texts
    memory_keys = list(MEMORIES.keys())
    mem_vecs = embed([MEMORIES[k]["multi-field"] for k in memory_keys])

    print(f"\n{'Target':<15} {'Level':<15} {'Query':<55} {'NoPrefix':>9} {'Prefix':>9} {'Delta':>7}")
    print("-" * 115)

    improvements = []
    for target, queries in QUERIES.items():
        target_idx = memory_keys.index(target)
        for level, query_text in queries:
            # Without prefix
            qv_no = embed([query_text])[0]
            scores_no = [sim(qv_no, mem_vecs[j]) for j in range(len(memory_keys))]
            target_no = scores_no[target_idx]
            rank_no = 1 + sum(1 for s in scores_no if s > target_no)

            # With prefix
            qv_pf = embed([BGE_QUERY_PREFIX + query_text])[0]
            scores_pf = [sim(qv_pf, mem_vecs[j]) for j in range(len(memory_keys))]
            target_pf = scores_pf[target_idx]
            rank_pf = 1 + sum(1 for s in scores_pf if s > target_pf)

            # Margin improvement
            margin_no = target_no - max(s for i, s in enumerate(scores_no) if i != target_idx)
            margin_pf = target_pf - max(s for i, s in enumerate(scores_pf) if i != target_idx)
            delta = margin_pf - margin_no
            improvements.append(delta)

            no_str = f"{target_no:.4f}(r{rank_no})"
            pf_str = f"{target_pf:.4f}(r{rank_pf})"
            print(f"{target:<15} {level:<15} {query_text:<55} {no_str:>9} {pf_str:>9} {delta:>+7.4f}")

    avg_delta = np.mean(improvements)
    print(f"\nAverage margin improvement with prefix: {avg_delta:+.4f}")
    print(f"Prefix helped (positive delta): {sum(1 for d in improvements if d > 0)}/{len(improvements)}")


def test_2_text_length_variants():
    """Does shorter/denser text embed better than multi-field concatenation?"""
    print("\n" + "=" * 80)
    print("TEST 2: EMBEDDING TEXT LENGTH VARIANTS")
    print("Comparing: multi-field (long) vs summary-only vs key-sentence (shortest)")
    print("=" * 80)

    memory_keys = list(MEMORIES.keys())

    for target, queries in QUERIES.items():
        variants = MEMORIES[target]
        var_names = list(variants.keys())
        var_vecs = embed([variants[v] for v in var_names])

        # Other memories (distractors) use multi-field
        distractor_vecs = {
            k: embed([MEMORIES[k]["multi-field"]])[0]
            for k in memory_keys if k != target
        }

        print(f"\n--- Target: {target} ---")
        print(f"  Lengths: " + ", ".join(f"{v}={len(variants[v])}ch" for v in var_names))
        print(f"\n  {'Level':<15} {'Query':<55} ", end="")
        for v in var_names:
            print(f"{v:>12}", end="")
        print(f"  {'BestDistract':>12}")
        print("  " + "-" * (15 + 55 + 12 * len(var_names) + 14))

        for level, query_text in queries:
            qv = embed([query_text])[0]
            print(f"  {level:<15} {query_text:<55} ", end="")
            scores = []
            for vi, vn in enumerate(var_names):
                s = sim(qv, var_vecs[vi])
                scores.append(s)
                print(f"{s:>12.4f}", end="")
            best_dist = max(sim(qv, dv) for dv in distractor_vecs.values())
            print(f"  {best_dist:>12.4f}")

            # Show which variant has best margin over distractors
            margins = [s - best_dist for s in scores]
            best_variant = var_names[np.argmax(margins)]


def test_3_query_context_expansion():
    """If we prepend domain context to abstract queries, does it help?"""
    print("\n" + "=" * 80)
    print("TEST 3: QUERY CONTEXT EXPANSION")
    print("What if we prepend thread/topic context to abstract queries?")
    print("Simulates: routing layer knows the current container/thread topic.")
    print("=" * 80)

    memory_keys = list(MEMORIES.keys())
    mem_vecs = embed([MEMORIES[k]["multi-field"] for k in memory_keys])

    context_expansions = {
        "task-checkpoint": [
            ("bare",         "Where did things end up with that?"),
            ("+topic",       "Regarding catalog sync: where did things end up with that?"),
            ("+thread-hint", "In our conversation about the sync job failure: where did things end up?"),
        ],
        "investigation": [
            ("bare",         "How did it turn out?"),
            ("+topic",       "Regarding duplicate holds: how did it turn out?"),
            ("+thread-hint", "In the hold queue investigation: how did it turn out?"),
        ],
        "decision": [
            ("bare",         "What approach did we settle on?"),
            ("+topic",       "Regarding reservation ordering: what approach did we settle on?"),
            ("+thread-hint", "For the catalog sync delay handling: what approach did we settle on?"),
        ],
    }

    print(f"\n{'Target':<15} {'Expansion':<15} {'Query':<65} {'Target':>7} {'Margin':>8} {'Rank':>5}")
    print("-" * 120)

    for target, expansions in context_expansions.items():
        target_idx = memory_keys.index(target)
        for exp_type, query_text in expansions:
            qv = embed([query_text])[0]
            scores = [sim(qv, mem_vecs[j]) for j in range(len(memory_keys))]
            target_score = scores[target_idx]
            best_other = max(s for i, s in enumerate(scores) if i != target_idx)
            margin = target_score - best_other
            rank = 1 + sum(1 for s in scores if s > target_score)
            marker = "OK" if rank == 1 else f"MISS(r={rank})"
            print(f"{target:<15} {exp_type:<15} {query_text:<65} {target_score:>7.4f} {margin:>+8.4f} {marker:>5}")


def test_4_source_vs_memory_as_target():
    """Would embedding raw SourceItem content add retrieval value?"""
    print("\n" + "=" * 80)
    print("TEST 4: RAW SOURCE ITEM vs MEMORY OBJECT AS EMBEDDING TARGET")
    print("Should we embed SourceItems too, or is memory-only sufficient?")
    print("=" * 80)

    memory_keys = list(MEMORIES.keys())

    # For each target: compare rank-1 accuracy using memory-only vs memory+source
    print(f"\n{'Target':<15} {'Level':<15} {'Query':<55} {'MemOnly':>9} {'MemRank':>8} {'SrcOnly':>9} {'SrcRank':>8}")
    print("-" * 125)

    for target, queries in QUERIES.items():
        mem_vec = embed([MEMORIES[target]["multi-field"]])[0]
        src_vec = embed([MEMORIES[target]["raw-source"]])[0]

        # Distractors (both mem and src from other targets)
        other_mem = [embed([MEMORIES[k]["multi-field"]])[0] for k in memory_keys if k != target]
        other_src = [embed([MEMORIES[k]["raw-source"]])[0] for k in memory_keys if k != target]

        for level, query_text in queries:
            qv = embed([query_text])[0]

            # Memory-only scoring
            mem_score = sim(qv, mem_vec)
            mem_others = [sim(qv, ov) for ov in other_mem]
            mem_rank = 1 + sum(1 for s in mem_others if s > mem_score)

            # Source-only scoring
            src_score = sim(qv, src_vec)
            src_others = [sim(qv, ov) for ov in other_src]
            src_rank = 1 + sum(1 for s in src_others if s > src_score)

            print(f"{target:<15} {level:<15} {query_text:<55} {mem_score:>8.4f} {'r'+str(mem_rank):>8} {src_score:>8.4f} {'r'+str(src_rank):>8}")


if __name__ == "__main__":
    print("=" * 80)
    print("DEEP VALIDATION: WRITE PATH AND QUERY PATH IMPLICATIONS")
    print("=" * 80)
    init_model()
    test_1_bge_prefix()
    test_2_text_length_variants()
    test_3_query_context_expansion()
    test_4_source_vs_memory_as_target()
    print("\n" + "=" * 80)
    print("ALL TESTS COMPLETE")
    print("=" * 80)
