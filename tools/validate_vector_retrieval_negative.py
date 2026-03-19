"""Negative-case and assumption validation for vector retrieval.

Tests:
1. False-positive rate: with many unrelated same-container memories, how many
   irrelevant memories score above threshold for a given query?
2. Current vs simplified build_embedding_text(): systematic comparison
3. Length guard calibration: what threshold filters correctly?
"""

from __future__ import annotations

import numpy as np
import onnxruntime as ort
from huggingface_hub import hf_hub_download
from tokenizers import Tokenizer

MODEL_REPO = "BAAI/bge-small-en-v1.5"
_session: ort.InferenceSession | None = None
_tokenizer: Tokenizer | None = None


def init_model():
    global _session, _tokenizer
    model_path = hf_hub_download(repo_id=MODEL_REPO, filename="onnx/model.onnx")
    tokenizer_path = hf_hub_download(repo_id=MODEL_REPO, filename="tokenizer.json")
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
        l = len(enc.ids); input_ids[i, :l] = enc.ids; attention_mask[i, :l] = 1
    out = _session.run(None, {"input_ids": input_ids, "attention_mask": attention_mask, "token_type_ids": token_type_ids})
    e = out[0][:, 0, :]
    n = np.linalg.norm(e, axis=1, keepdims=True)
    return e / np.maximum(n, 1e-12)


def sim(a, b):
    return float(np.dot(a, b))


# ===================================================================
# REALISTIC CONTAINER: 15 memory objects, mix of types, one target
# Simulates a real container with diverse memories
# ===================================================================

CONTAINER_MEMORIES = {
    # --- TARGET: catalog sync investigation ---
    "target:task-checkpoint": (
        "Catalog sync scheduled job was failing because the nightly batch API "
        "token expired after 90-day credential window. Token rotation policy "
        "was not applied to service accounts. Refreshed token and restarted "
        "sync; 412 of 580 records processed."
    ),

    # --- RELATED but different topic (same domain) ---
    "related:hold-queue-fix": (
        "Duplicate hold entries in reservation queue resolved by adding "
        "unique constraint on patron_id, item_id, hold_window."
    ),
    "related:event-time-decision": (
        "Decision: use event-time ordering instead of wall-clock ordering "
        "for reservation priority when catalog sync is delayed."
    ),
    "related:batch-pattern": (
        "Recurring pattern: nightly batch jobs that accumulate backlogs "
        "larger than 200 records cause downstream queue failures."
    ),

    # --- UNRELATED topics (same container, different workstreams) ---
    "unrelated:branch-printer": (
        "Branch printer configuration updated to use new network gateway. "
        "All 12 branch locations migrated to the updated firmware."
    ),
    "unrelated:patron-card": (
        "Patron card renewal workflow redesigned. New cards now include "
        "QR code for self-checkout terminal authentication."
    ),
    "unrelated:budget-report": (
        "Annual budget report shows 12% increase in digital lending. "
        "Physical collection acquisition budget reduced by 8%."
    ),
    "unrelated:staff-training": (
        "Staff training schedule for new catalog management system "
        "published. Three sessions planned for March and April."
    ),
    "unrelated:building-hvac": (
        "HVAC system maintenance completed for the main branch reading room. "
        "Temperature control now within 1 degree of target."
    ),
    "unrelated:website-redesign": (
        "Library website redesign launched with improved search. Patron "
        "feedback collected from 200 respondents shows 78% satisfaction."
    ),
    "unrelated:volunteer-program": (
        "Summer volunteer program registration opened. Expected 45 volunteers "
        "for children's reading program across 6 branches."
    ),
    "unrelated:accessibility-audit": (
        "Accessibility audit completed for digital services. Three WCAG AA "
        "violations found in the online catalog search interface."
    ),
    "unrelated:overdue-policy": (
        "Overdue fine policy changed: first notice at 7 days, second at 14, "
        "account suspension at 30 days. Late fees reduced by 50%."
    ),
    "unrelated:meeting-rooms": (
        "Meeting room booking system upgraded. Patrons can now reserve "
        "rooms up to 2 weeks in advance via the mobile app."
    ),
    "unrelated:inter-library": (
        "Inter-library loan processing time reduced from 5 days to 3 days "
        "by switching to the regional consortium's automated routing."
    ),
}


def test_1_false_positive_rate():
    """With 15 memories in a container, how many false positives per query?"""
    print("\n" + "=" * 80)
    print("TEST 1: FALSE POSITIVE RATE (15 memories in container)")
    print("How many irrelevant memories score above threshold for each query?")
    print("=" * 80)

    mem_keys = list(CONTAINER_MEMORIES.keys())
    mem_texts = [CONTAINER_MEMORIES[k] for k in mem_keys]
    mem_vecs = embed(mem_texts)

    target_key = "target:task-checkpoint"
    target_idx = mem_keys.index(target_key)
    related_keys = {k for k in mem_keys if k.startswith("related:")}
    unrelated_keys = {k for k in mem_keys if k.startswith("unrelated:")}

    queries = [
        ("light-anchor",    "Where did things end up with the sync job?"),
        ("moderate",        "What's the status on the catalog sync failure?"),
        ("domain-specific", "Did the catalog sync token rotation get fixed?"),
        ("casual",          "What's going on with that sync thing again?"),
        ("conversational",  "Hey, remind me about the sync job situation"),
        ("formal",          "Could you summarize the catalog synchronization issue?"),
        ("indirect",        "I need to update the team on the nightly job progress"),
    ]

    thresholds = [0.3, 0.35, 0.4, 0.45, 0.5, 0.55, 0.6]

    print(f"\n{'Query':<55} {'TargetSim':>9}  ", end="")
    for t in thresholds:
        print(f"  t={t:.2f}", end="")
    print()
    print("-" * (55 + 10 + len(thresholds) * 8))

    # Collect data for summary
    fp_by_threshold = {t: [] for t in thresholds}

    for label, query_text in queries:
        qv = embed([query_text])[0]
        scores = [(mk, sim(qv, mem_vecs[j])) for j, mk in enumerate(mem_keys)]
        scores.sort(key=lambda x: x[1], reverse=True)

        target_score = next(s for k, s in scores if k == target_key)
        target_rank = next(i + 1 for i, (k, _) in enumerate(scores) if k == target_key)

        print(f"{query_text:<55} {target_score:>7.4f}(r{target_rank})", end="")

        for t in thresholds:
            # Count false positives: unrelated memories above threshold
            fp_unrelated = sum(1 for k, s in scores if k in unrelated_keys and s >= t)
            fp_related = sum(1 for k, s in scores if k in related_keys and s >= t)
            fp_total = fp_unrelated + fp_related  # everything except target
            fp_by_threshold[t].append(fp_unrelated)
            print(f"  {fp_unrelated:>2}u+{fp_related:>1}r", end="")
        print()

        # Show top 5 for first query
        if label == "light-anchor":
            print(f"  Top 5 results:")
            for rank, (mk, s) in enumerate(scores[:5], 1):
                category = "TARGET" if mk == target_key else ("RELATED" if mk in related_keys else "UNRELATED")
                print(f"    {rank}. {mk:35} sim={s:.4f}  [{category}]")

    # Summary
    print(f"\n{'Threshold':<12} {'Avg unrelated FP':>18} {'Max unrelated FP':>18} {'Avg total above':>18}")
    print("-" * 70)
    for t in thresholds:
        fps = fp_by_threshold[t]
        print(f"  {t:.2f}       {np.mean(fps):>16.1f}   {max(fps):>16d}   {sum(fps):>16d}")


def test_2_low_value_distractor():
    """Do low-value/generic memories get falsely surfaced?"""
    print("\n" + "=" * 80)
    print("TEST 2: LOW-VALUE / GENERIC MEMORY DISTRACTOR TEST")
    print("Do vague/generic memories score above threshold?")
    print("=" * 80)

    low_value_memories = [
        ("greeting",          "Hello! How can I help you today?"),
        ("acknowledgment",    "Got it, I'll look into that."),
        ("filler",            "Let me check on that for you."),
        ("vague-summary",     "We discussed some options and agreed to move forward."),
        ("generic-status",    "Things are progressing as expected."),
        ("meta-discussion",   "That's a good point, let me think about it."),
        ("short-decision",    "We decided to go with option B."),
        ("vague-outcome",     "The investigation concluded without clear findings."),
    ]

    target_memory = (
        "Catalog sync scheduled job was failing because the nightly batch API "
        "token expired after 90-day credential window."
    )

    queries = [
        ("light-anchor",    "Where did things end up with the sync job?"),
        ("moderate",        "What's the status on the catalog sync failure?"),
        ("casual",          "Hey, remind me about the sync job situation"),
    ]

    # Embed everything
    all_texts = [target_memory] + [text for _, text in low_value_memories]
    all_vecs = embed(all_texts)
    target_vec = all_vecs[0]

    print(f"\n{'Query':<55}  {'Target':>7}  ", end="")
    for label, _ in low_value_memories:
        print(f"{label[:8]:>9}", end="")
    print()
    print("-" * (55 + 10 + len(low_value_memories) * 9))

    for qlabel, query_text in queries:
        qv = embed([query_text])[0]
        target_score = sim(qv, target_vec)
        print(f"{query_text:<55}  {target_score:>7.4f}  ", end="")
        for i, (label, _) in enumerate(low_value_memories):
            s = sim(qv, all_vecs[i + 1])
            marker = "!" if s >= target_score else " "
            print(f"{s:>8.4f}{marker}", end="")
        print()


def test_3_embedding_text_comparison():
    """Systematic comparison: current multi-field vs simplified single-field."""
    print("\n" + "=" * 80)
    print("TEST 3: CURRENT vs SIMPLIFIED build_embedding_text()")
    print("Systematic comparison across all memory types")
    print("=" * 80)

    comparisons = {
        "task_checkpoint": {
            "current": (
                "Task: Investigate catalog sync scheduled job failure "
                "Current state: Refreshed token, restarted sync, 412 of 580 records processed "
                "Next step: Monitor remaining batch completion by tomorrow morning "
                "Finding: API token expired after 90-day window "
                "Finding: Token rotation not applied to service accounts"
            ),
            "simplified": (
                "Catalog sync job failing due to expired nightly batch API token. "
                "Token rotation not applied to service accounts. "
                "Refreshed token, sync in progress, 412 of 580 processed."
            ),
        },
        "investigation_outcome": {
            "current": (
                "Investigation outcome: Duplicate hold entries caused by missing "
                "deduplication check in queue consumer "
                "Rationale: Backlog replay inserted duplicate holds for same patron-item pair"
            ),
            "simplified": (
                "Duplicate hold entries caused by missing deduplication in queue consumer. "
                "Backlog replay created duplicates for same patron-item pair."
            ),
        },
        "decision": {
            "current": (
                "Decision: Use event-time ordering for reservation priority during "
                "catalog sync delays "
                "Rationale: Wall-clock ordering penalizes patrons whose requests were "
                "queued before the sync delay"
            ),
            "simplified": (
                "Use event-time ordering for reservation priority when catalog sync "
                "is delayed, because wall-clock penalizes pre-delay patrons."
            ),
        },
        "thread_summary": {
            "current": (
                "Investigation into catalog sync failures. Found expired API token "
                "on nightly batch service account. Token rotation policy gap identified. "
                "Token refreshed, sync restarted with 412/580 records processed."
            ),
            "simplified": (
                "Catalog sync failure: expired API token on nightly batch. "
                "Token rotation gap. Refreshed, 412/580 processed."
            ),
        },
        "continuity_memory": {
            "current": (
                "Question: What is the status of the catalog sync? "
                "Answer: Token was refreshed, sync restarted, 412 of 580 records processed. "
                "Repeated question about catalog sync status"
            ),
            "simplified": (
                "What is the catalog sync status? Token refreshed, sync restarted, "
                "412 of 580 records processed."
            ),
        },
    }

    queries = [
        ("light",    "Where did things end up with the sync job?"),
        ("moderate", "What's the status on the catalog sync failure?"),
        ("domain",   "Did the catalog sync token rotation get fixed?"),
    ]

    # Distractor
    distractor = "Branch printer configuration updated to use new network gateway."
    dist_vec = embed([distractor])[0]

    print(f"\n{'MemType':<22} {'Variant':<12} {'Len':>4}  ", end="")
    for ql, _ in queries:
        print(f"  {ql:>10}", end="")
    print(f"  {'AvgMargin':>10}")
    print("-" * (22 + 12 + 6 + len(queries) * 12 + 12))

    for mem_type, variants in comparisons.items():
        for var_name, var_text in variants.items():
            var_vec = embed([var_text])[0]
            margins = []
            print(f"{mem_type:<22} {var_name:<12} {len(var_text):>4}  ", end="")
            for ql, qt in queries:
                qv = embed([qt])[0]
                target_sim = sim(qv, var_vec)
                dist_sim = sim(qv, dist_vec)
                margin = target_sim - dist_sim
                margins.append(margin)
                print(f"  {target_sim:>8.4f}({margin:+.2f})", end="")
            avg_margin = np.mean(margins)
            print(f"  {avg_margin:>+10.4f}")
        print()


def test_4_length_guard_calibration():
    """What would different length thresholds filter?"""
    print("\n" + "=" * 80)
    print("TEST 4: LENGTH GUARD CALIBRATION")
    print("What real memory texts would be filtered at each threshold?")
    print("=" * 80)

    test_texts = [
        ("good:full-checkpoint",    298, "Task: Investigate catalog sync... (full multi-field)"),
        ("good:summary",            137, "Investigation into catalog sync failures. Found expired API token..."),
        ("good:decision",           183, "Decision: Use event-time ordering for reservation priority..."),
        ("good:pattern",            119, "Recurring pattern: nightly batch jobs that accumulate backlogs..."),
        ("good:continuity",         168, "Question: What is the catalog sync status? Answer: Token was..."),
        ("marginal:short-decision",  52, "We decided to go with option B for the sync."),
        ("marginal:short-outcome",   46, "Token expired. Refreshed it. Sync resumed."),
        ("bad:vague-summary",        39, "We discussed options and moved forward."),
        ("bad:acknowledgment",       32, "Got it, I'll look into that."),
        ("bad:greeting",             29, "Hello! How can I help you today?"),
        ("bad:filler",               26, "Let me check on that."),
        ("bad:very-short",           15, "Sounds good."),
    ]

    thresholds = [20, 30, 40, 50, 60, 80]

    print(f"\n{'Label':<30} {'Len':>4}  ", end="")
    for t in thresholds:
        print(f"  >={t:<3}", end="")
    print(f"  {'EmbedQuality':>12}")
    print("-" * (30 + 6 + len(thresholds) * 7 + 14))

    query_vec = embed(["Where did things end up with the sync job?"])[0]

    for label, length, desc in test_texts:
        # Create a representative text of that length
        if "good:" in label or "marginal:" in label:
            # Use actual representative text
            texts_by_label = {
                "good:full-checkpoint": "Task: Investigate catalog sync scheduled job failure Current state: Refreshed token restarted sync 412 of 580 records processed Next step: Monitor remaining batch completion Finding: API token expired",
                "good:summary": "Investigation into catalog sync failures. Found expired API token on nightly batch service account. Token rotation policy gap identified.",
                "good:decision": "Decision: Use event-time ordering for reservation priority during catalog sync delays. Rationale: Wall-clock ordering penalizes patrons queued before delay.",
                "good:pattern": "Recurring pattern: nightly batch jobs that accumulate backlogs larger than 200 records cause downstream queue failures.",
                "good:continuity": "Question: What is the catalog sync status? Answer: Token was refreshed, sync restarted, 412 of 580 records processed.",
                "marginal:short-decision": "We decided to go with option B for the sync.",
                "marginal:short-outcome": "Token expired. Refreshed it. Sync resumed.",
            }
            text = texts_by_label.get(label, desc)
        else:
            texts_by_label = {
                "bad:vague-summary": "We discussed options and moved forward.",
                "bad:acknowledgment": "Got it, I'll look into that.",
                "bad:greeting": "Hello! How can I help you today?",
                "bad:filler": "Let me check on that.",
                "bad:very-short": "Sounds good.",
            }
            text = texts_by_label.get(label, desc)

        text_vec = embed([text])[0]
        quality = sim(query_vec, text_vec)

        real_len = len(text)
        print(f"{label:<30} {real_len:>4}  ", end="")
        for t in thresholds:
            kept = "KEEP" if real_len >= t else "DROP"
            print(f"  {kept:<5}", end="")
        print(f"  {quality:>10.4f}")


if __name__ == "__main__":
    print("=" * 80)
    print("NEGATIVE-CASE AND ASSUMPTION VALIDATION")
    print("=" * 80)
    init_model()
    test_1_false_positive_rate()
    test_2_low_value_distractor()
    test_3_embedding_text_comparison()
    test_4_length_guard_calibration()
    print("\n" + "=" * 80)
    print("ALL TESTS COMPLETE")
    print("=" * 80)
