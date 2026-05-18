"""Thread decision dedup eval.

Tests whether `_evidence_canonical_key` from
`semantic.agent_conversation_memory_threads` correctly collapses paraphrase
clusters whose evidence text is the same modulo role-prefix drift, while
NOT colliding distinct decisions across domains.

Modes:
- BEFORE code change: function not yet implemented, eval reports baseline
  failure for every cluster (function not yet implemented; baseline failing).
- AFTER code change: each cluster collapses to a single canonical key.

Usage:
    python -m evals.thread_decision_dedup_eval
    python -m evals.thread_decision_dedup_eval --verbose
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path


CORPUS_PATH = Path(__file__).parent / "thread_decision_dedup_corpus.jsonl"

# Categories whose clusters are exercised in the eval but DO NOT gate pass/fail.
# Each represents a class of evidence drift that is intentionally out of scope
# for the current `_evidence_canonical_key` plan:
#
#   - multiline_prefix_pair: role-prefix sits on a non-leading line; the planned
#     `^[a-z_]+/[a-z_]+:\s*` regex anchors at start-of-string only.
#   - plural_stem_pair:      pluralization drift ("batch" vs "batches"); the
#     planned tokenizer deliberately does NOT call `content_tokens` (no stem
#     expansion) to avoid the lexical-overlap instability documented in P3.
#   - preamble_drift_tracked: conversational preamble before the decision quote
#     ("a couple of things regarding this:\n1. ..."); extra preamble tokens
#     defeat any pure tokenset key — needs LLM-side help, not canonical-key.
TRACKED_ONLY_CATEGORIES = {
    "multiline_prefix_pair",
    "plural_stem_pair",
    "preamble_drift_tracked",
}


def load_corpus() -> list[dict]:
    return [json.loads(line) for line in open(CORPUS_PATH, encoding="utf-8") if line.strip()]


def _try_import_key_fn():
    """Attempt to import the production canonical-key function."""
    try:
        from semantic.agent_conversation_memory_threads import (  # type: ignore[attr-defined]
            _evidence_canonical_key,
        )
        return _evidence_canonical_key, True
    except (ImportError, AttributeError):
        return None, False


def _baseline_key(evidence: str | None) -> str | None:
    """Baseline placeholder: raw normalized evidence text.

    This is what the dedup looks like WITHOUT the new function — paraphrase
    clusters that differ only by role prefix WILL diverge under this baseline.
    """
    if not evidence:
        return None
    return evidence.strip().lower()


# ---------------------------------------------------------------------------
# Cluster collapse eval
# ---------------------------------------------------------------------------

def run_cluster_eval(
    corpus: list[dict],
    key_fn,
    fn_available: bool,
    verbose: bool = False,
) -> dict:
    """For each cluster, compute keys and assert all items collapse to one."""
    clusters: dict[str, list[dict]] = defaultdict(list)
    for item in corpus:
        if item.get("cluster_id"):
            clusters[item["cluster_id"]].append(item)

    results: dict = {
        "fn_available": fn_available,
        "clusters_tested": 0,
        "clusters_collapsed": 0,
        "tracked_only_clusters": 0,
        "tracked_only_collapsed": 0,
        "details": {},
    }

    for cluster_id, items in clusters.items():
        category = items[0].get("category", "")
        is_tracked_only = category in TRACKED_ONLY_CATEGORIES

        keys = [key_fn(it["evidence_text"]) for it in items]
        unique_keys = set(keys)
        collapsed = len(unique_keys) == 1

        if is_tracked_only:
            # Tracked-only categories (multiline prefix, plural stem, preamble
            # drift): documented out-of-scope for the planned canonical-key fix.
            # Report whether they happen to collapse; do not block the eval.
            results["tracked_only_clusters"] += 1
            if collapsed:
                results["tracked_only_collapsed"] += 1
        else:
            results["clusters_tested"] += 1
            if collapsed:
                results["clusters_collapsed"] += 1

        results["details"][cluster_id] = {
            "category": category,
            "items": len(items),
            "unique_keys": len(unique_keys),
            "collapsed": collapsed,
            "tracked_only": is_tracked_only,
            "keys": keys if verbose else None,
        }

    return results


# ---------------------------------------------------------------------------
# Good-unique cross-cluster collision check
# ---------------------------------------------------------------------------

def run_good_unique_check(corpus: list[dict], key_fn) -> dict:
    """Verify good_unique baselines do NOT share a canonical key with anyone."""
    good_items = [it for it in corpus if it.get("category") == "good_unique"]
    cluster_items = [it for it in corpus if it.get("category") == "paraphrase_cluster"]

    good_keys = [(it, key_fn(it["evidence_text"])) for it in good_items]
    cluster_keys = [(it, key_fn(it["evidence_text"])) for it in cluster_items]

    collisions: list[dict] = []

    # good vs good
    for i in range(len(good_keys)):
        for j in range(i + 1, len(good_keys)):
            ki, kj = good_keys[i][1], good_keys[j][1]
            if ki is not None and ki == kj:
                collisions.append({
                    "kind": "good_vs_good",
                    "a": good_keys[i][0]["decision_text"][:60],
                    "b": good_keys[j][0]["decision_text"][:60],
                    "key": ki,
                })

    # good vs paraphrase clusters
    for it_g, kg in good_keys:
        for it_c, kc in cluster_keys:
            if kg is not None and kg == kc:
                collisions.append({
                    "kind": "good_vs_cluster",
                    "a": it_g["decision_text"][:60],
                    "b": it_c["decision_text"][:60],
                    "key": kg,
                })

    return {
        "good_count": len(good_items),
        "false_collisions": len(collisions),
        "collisions": collisions,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Thread decision dedup eval")
    parser.add_argument("--verbose", action="store_true", help="Show per-item canonical keys")
    args = parser.parse_args()

    if not CORPUS_PATH.exists():
        print(f"ERROR: Corpus not found at {CORPUS_PATH}")
        return 1

    corpus = load_corpus()
    cluster_count = len(set(c["cluster_id"] for c in corpus if c.get("cluster_id")))
    good_count = sum(1 for c in corpus if c.get("category") == "good_unique")

    print(f"Corpus: {len(corpus)} items "
          f"({cluster_count} clusters, {good_count} good_unique baselines)")
    print()

    fn, fn_available = _try_import_key_fn()
    if not fn_available:
        print("STATUS: _evidence_canonical_key NOT IMPLEMENTED YET")
        print("        function not yet implemented; baseline failing")
        print("        (using raw stripped evidence as baseline placeholder)")
        print()
        key_fn = _baseline_key
    else:
        print("STATUS: _evidence_canonical_key available — exercising production logic")
        print()
        key_fn = fn

    # -----------------------------------------------------------------------
    # 1. Cluster collapse
    # -----------------------------------------------------------------------
    print("=" * 60)
    print("1. CLUSTER COLLAPSE (paraphrase + plural-stem)")
    print("=" * 60)

    cluster_results = run_cluster_eval(corpus, key_fn, fn_available, verbose=args.verbose)

    for cluster_id, detail in cluster_results["details"].items():
        if detail["tracked_only"]:
            tag = "TRACK"  # tracked-only, doesn't fail eval
        else:
            tag = "PASS" if detail["collapsed"] else "FAIL"
        print(f"  [{tag}] {cluster_id} ({detail['category']}): "
              f"{detail['unique_keys']} unique key(s) across {detail['items']} item(s)")
        if args.verbose and detail["keys"] is not None:
            for k in detail["keys"]:
                print(f"        key={k!r}")

    print()
    print(f"  Required clusters collapsed: "
          f"{cluster_results['clusters_collapsed']}/{cluster_results['clusters_tested']}")
    print(f"  Tracked-only clusters collapsed: "
          f"{cluster_results['tracked_only_collapsed']}/{cluster_results['tracked_only_clusters']} "
          f"(known-limitation; not blocking)")

    cluster_pass = (
        cluster_results["clusters_collapsed"] == cluster_results["clusters_tested"]
    )
    print(f"\n  RESULT: {'PASS' if cluster_pass else 'FAIL'}")

    # -----------------------------------------------------------------------
    # 2. Good-unique non-collision
    # -----------------------------------------------------------------------
    print()
    print("=" * 60)
    print("2. GOOD-UNIQUE NON-COLLISION CHECK")
    print("=" * 60)

    unique_results = run_good_unique_check(corpus, key_fn)
    print(f"  Good-unique items: {unique_results['good_count']}")
    print(f"  False collisions: {unique_results['false_collisions']}")
    if unique_results["collisions"]:
        for c in unique_results["collisions"]:
            print(f"    [{c['kind']}] key={c['key']!r}")
            print(f"      a={c['a']!r}")
            print(f"      b={c['b']!r}")
    unique_pass = unique_results["false_collisions"] == 0
    print(f"\n  RESULT: {'PASS' if unique_pass else 'FAIL'}")

    # -----------------------------------------------------------------------
    # Summary
    # -----------------------------------------------------------------------
    print()
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)

    if not fn_available:
        print("  _evidence_canonical_key:  NOT IMPLEMENTED (baseline run)")
    else:
        print("  _evidence_canonical_key:  available")

    print(f"  Cluster collapse:         {'PASS' if cluster_pass else 'FAIL'} "
          f"({cluster_results['clusters_collapsed']}/{cluster_results['clusters_tested']} required)")
    print(f"  Tracked-only clusters:    "
          f"{cluster_results['tracked_only_collapsed']}/{cluster_results['tracked_only_clusters']} "
          f"collapsed (informational; out-of-scope for planned fix)")
    print(f"  Non-collision:            {'PASS' if unique_pass else 'FAIL'} "
          f"({unique_results['false_collisions']} collisions)")

    if not fn_available:
        print()
        print("  Baseline regression count for good_unique: "
              f"{unique_results['false_collisions']}")
        print("  (Baseline mode: each paraphrase cluster fails to collapse "
              "until the production fix lands.)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
