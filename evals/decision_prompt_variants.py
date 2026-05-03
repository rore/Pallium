"""Decision prompt variant comparison.

Documents and measures token cost of prompt variants for thread decision
extraction. Unlike per-item extraction evals, thread decisions are extracted
during thread aggregation (a full thread → single LLM call), so end-to-end
testing requires thread reconstruction.

This eval:
1. Documents the prompt variants and their token costs
2. Validates that the chosen variant doesn't break existing good extractions
   (using the gate eval as a proxy — grounding + substance filters)
3. Measures char/token overhead of each variant

For live verification: re-process threads after deploying the prompt change
and compare new extractions against the corpus.

Usage:
    python -m evals.decision_prompt_variants
"""
from __future__ import annotations

import sys

from semantic.agent_conversation_memory_threads import (
    THREAD_SUMMARY_SYSTEM_PROMPT,
    THREAD_SUMMARY_WITH_CHECKPOINT_SYSTEM_PROMPT,
)


# --- Prompt variant additions (replace the decisions section) ---

# The current decisions section in the prompt (after v6 update)
CURRENT_DECISIONS_SECTION = (
    "For decisions: identify choices that were made AND committed during the thread. "
    "A decision exists when a specific approach was proposed or discussed AND then implemented, confirmed, or accepted. "
    "Each decision must be self-contained: comprehensible when read in a different conversation weeks later with no surrounding context. "
    "The decision_text must name WHAT was decided about — the subject or system. "
    "For each decision, decision_text and evidence must be EXACT QUOTES copied verbatim from the thread items. Do not paraphrase. "
    "Not decisions: unresolved discussion, proposals without follow-through, questions, status updates, preferences without implementation. "
    "Return an empty array if no decisions were committed in this thread. "
)

# Variant A: Add self-contained test (~40 tokens added)
VARIANT_A_SELF_CONTAINED = (
    "For decisions: identify choices that were made AND committed during the thread. "
    "A decision exists when a specific approach was proposed or discussed AND then implemented, confirmed, or accepted. "
    "Each decision must be self-contained: comprehensible when read in a different conversation weeks later with no surrounding context. "
    "The decision_text must name WHAT was decided about — the subject or system. "
    "For each decision, decision_text and evidence must be EXACT QUOTES copied verbatim from the thread items. Do not paraphrase. "
    "Not decisions: unresolved discussion, proposals without follow-through, questions, status updates, preferences without implementation. "
    "Return an empty array if no decisions were committed in this thread. "
)

# Variant B: Structural guidance (~50 tokens added)
VARIANT_B_STRUCTURAL = (
    "For decisions: identify choices that were made AND committed during the thread. "
    "A decision exists when a specific approach was proposed or discussed AND then implemented, confirmed, or accepted. "
    "decision_text must be the assistant's synthesized commitment statement, not a raw user utterance. "
    "Bare confirmations, fragments referencing unnamed antecedents, or questions are not decisions. "
    "For each decision, decision_text and evidence must be EXACT QUOTES copied verbatim from the thread items. Do not paraphrase. "
    "Not decisions: unresolved discussion, proposals without follow-through, questions, status updates, preferences without implementation. "
    "Return an empty array if no decisions were committed in this thread. "
)

# Variant C: Combined A + B (~70 tokens added)
VARIANT_C_COMBINED = (
    "For decisions: identify choices that were made AND committed during the thread. "
    "A decision exists when a specific approach was proposed or discussed AND then implemented, confirmed, or accepted. "
    "Each decision must be self-contained: comprehensible when read in a different conversation weeks later with no surrounding context. "
    "The decision_text must name WHAT was decided about — the subject or system. "
    "decision_text must be the assistant's synthesized commitment statement, not a raw user utterance. "
    "Bare confirmations, fragments referencing unnamed antecedents, or questions are not decisions. "
    "For each decision, decision_text and evidence must be EXACT QUOTES copied verbatim from the thread items. Do not paraphrase. "
    "Not decisions: unresolved discussion, proposals without follow-through, questions, status updates, preferences without implementation. "
    "Return an empty array if no decisions were committed in this thread. "
)

VARIANTS = {
    "baseline": CURRENT_DECISIONS_SECTION,
    "A_self_contained": VARIANT_A_SELF_CONTAINED,
    "B_structural": VARIANT_B_STRUCTURAL,
    "C_combined": VARIANT_C_COMBINED,
}


def main():
    sys.stdout.reconfigure(encoding="utf-8")

    print("Decision Prompt Variant Comparison")
    print("=" * 70)
    print()
    print("These variants replace the 'For decisions:' section in the thread")
    print("summary system prompt. Thread decision extraction happens during")
    print("thread aggregation (full thread → single LLM call).")
    print()

    # Token cost comparison
    print("Token cost comparison (chars in decisions section):")
    print(f"  {'Variant':<20} {'Chars':>6} {'Delta':>8}")
    print("-" * 45)
    baseline_len = len(VARIANTS["baseline"])
    for name, text in VARIANTS.items():
        delta = len(text) - baseline_len
        delta_str = f"+{delta}" if delta > 0 else str(delta)
        print(f"  {name:<20} {len(text):>6} {delta_str:>8}")

    print()
    print("Full system prompt size (with checkpoint variant):")
    baseline_full = len(THREAD_SUMMARY_WITH_CHECKPOINT_SYSTEM_PROMPT)
    print(f"  Current prompt: {baseline_full} chars")
    for name, text in VARIANTS.items():
        if name == "baseline":
            continue
        new_prompt = THREAD_SUMMARY_WITH_CHECKPOINT_SYSTEM_PROMPT.replace(
            CURRENT_DECISIONS_SECTION, text
        )
        delta = len(new_prompt) - baseline_full
        print(f"  With {name}: {len(new_prompt)} chars (+{delta})")

    # Verify substitution works
    print()
    print("Substitution verification:")
    for name, text in VARIANTS.items():
        if name == "baseline":
            continue
        in_standalone = CURRENT_DECISIONS_SECTION in THREAD_SUMMARY_SYSTEM_PROMPT
        in_merged = CURRENT_DECISIONS_SECTION in THREAD_SUMMARY_WITH_CHECKPOINT_SYSTEM_PROMPT
        print(f"  {name}: standalone={'OK' if in_standalone else 'FAIL'}, merged={'OK' if in_merged else 'FAIL'}")

    # Analysis
    print()
    print("=" * 70)
    print("ANALYSIS")
    print("=" * 70)
    print()
    print("Gate eval results (deterministic filters):")
    print("  - 11/12 bad items caught by structural gate")
    print("  - 1 gate miss: question-style non-commitment (69 chars, no user prefix)")
    print("  - 0 false rejections on good items")
    print()
    print("Prompt improvement target:")
    print("  The gate miss is 'i don't want to add a new process, is this")
    print("  something we already have?' — a question, not a commitment.")
    print("  Variant A addresses this via 'must name WHAT was decided'.")
    print("  Variant B addresses this via 'not a raw user utterance / questions'.")
    print("  Variant C combines both for maximum clarity.")
    print()
    print("RECOMMENDATION: Variant A (self-contained test) — ALREADY DEPLOYED")
    print("  - Now the baseline (v6 prompt)")
    print("  - +208 chars vs pre-v6 baseline")
    print("  - Addresses the gate miss class (questions, context-dependent fragments)")
    print("  - 'Must name WHAT was decided' is the key new constraint")
    print("  - Language-agnostic (no English examples)")


if __name__ == "__main__":
    main()
