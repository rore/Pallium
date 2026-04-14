"""Retrieval experiment harness for fact consolidation architecture investigation.

Runs the LoCoMo QA phase against modified copies of cached DBs to compare
different retrieval configurations. No LLM extraction needed — only the
QA evaluation phase runs, reusing eval LLM cache for near-instant results.

Experiments:
  A: Baseline (current behavior) — already completed
  B: Soft lifecycle — superseded atomic_facts restored to index with score penalty
  C: No consolidation — fact_summaries removed, all atomic_facts active
  D: Capped summaries — split large fact_summaries, superseded AFs remain superseded
  E: Fragment indexing — add per-fact index entries to existing fact_summaries

Usage:
    python -m evals.retrieval_experiments --experiments B C D E \
        --conversations conv-26 conv-43 conv-44 \
        --cache-dir .local/llm-cache --rate-limit 20
"""
from __future__ import annotations

import argparse
import json
import logging
import shutil
import sqlite3
import uuid
from pathlib import Path
from collections import Counter, defaultdict

logger = logging.getLogger(__name__)

SOURCE_DB_CACHE = Path("evals/locomo/db_cache")
EXPERIMENT_DIR = Path("evals/locomo/experiments")
BASELINE_RESULTS = Path(
    "evals/locomo/output/locomo-benchmark__anthropic-claude__anthropic--claude-sonnet-latest__20260412T134928Z/results.jsonl"
)

# Conversations chosen for diversity: high (68%), mid (54%), low (46%) accuracy
DEFAULT_CONVERSATIONS = ["conv-26", "conv-43", "conv-44"]


# ---------------------------------------------------------------------------
# DB modification helpers
# ---------------------------------------------------------------------------


def _copy_db_cache(src_dir: Path, dst_dir: Path, conversations: list[str]) -> None:
    """Copy cached DBs + vector indexes to experiment directory."""
    dst_dir.mkdir(parents=True, exist_ok=True)
    for conv in conversations:
        for suffix in [".db", ".vector.index", ".vector.index.idmap.json", ".vector.index.meta.json"]:
            src = src_dir / f"{conv}{suffix}"
            dst = dst_dir / f"{conv}{suffix}"
            if src.exists():
                shutil.copy2(src, dst)


def _get_superseded_atomic_facts(conn: sqlite3.Connection) -> list[dict]:
    """Get all superseded atomic_facts with their payload."""
    rows = conn.execute("""
        SELECT id, payload_json, subject, container_ref
        FROM memory_objects
        WHERE type = 'atomic_fact' AND lifecycle = 'superseded'
    """).fetchall()
    results = []
    for mid, pjson, subject, container_ref in rows:
        payload = json.loads(pjson)
        results.append({
            "id": mid,
            "subject": subject or "",
            "statement": payload.get("statement", ""),
            "category": payload.get("category", ""),
            "container_ref": container_ref or "",
            "payload": payload,
        })
    return results


def _create_index_entries_for_facts(
    conn: sqlite3.Connection,
    facts: list[dict],
    text_view_prefix: str = "memory_object",
) -> int:
    """Create lexical FTS + vector embedding index entries for atomic_facts.

    Creates two index entries per fact (statement for FTS, embedding for vector).
    Returns count of entries created.
    """
    count = 0
    for fact in facts:
        entry_id_stmt = str(uuid.uuid4())
        entry_id_emb = str(uuid.uuid4())
        statement = fact["statement"]
        subject = fact["subject"]
        container = fact["container_ref"]

        # Lexical: normalized lowercase text for FTS
        lexical_text = statement.lower()
        # Embedding: "Subject: statement" format (matches agent_conversation_memory_embedding.py)
        embedding_text = f"{subject}: {statement}" if subject else statement

        # Insert index_entries for lexical
        conn.execute("""
            INSERT INTO index_entries (id, target_kind, target_id, index_type,
                                       text_view, text_view_name, provider_name, provider_version)
            VALUES (?, 'memory_object', ?, 'lexical', ?, ?, '', '')
        """, (entry_id_stmt, fact["id"], lexical_text, f"{text_view_prefix}.fact_statement"))

        # Insert FTS row
        conn.execute("""
            INSERT INTO lexical_fts (text_view, index_entry_id, target_kind, target_id,
                                      text_view_name, container_ref)
            VALUES (?, ?, 'memory_object', ?, ?, ?)
        """, (lexical_text, entry_id_stmt, fact["id"],
              f"{text_view_prefix}.fact_statement", container))

        # Insert index_entries for embedding (vector index needs reconciliation)
        conn.execute("""
            INSERT INTO index_entries (id, target_kind, target_id, index_type,
                                       text_view, text_view_name, provider_name, provider_version)
            VALUES (?, 'memory_object', ?, 'embedding', ?, ?, '', '')
        """, (entry_id_emb, fact["id"], embedding_text, f"{text_view_prefix}.fact_embedding"))

        count += 2

    conn.commit()
    return count


# ---------------------------------------------------------------------------
# Experiment B: Soft lifecycle
# ---------------------------------------------------------------------------


def prepare_experiment_b(db_dir: Path, conversations: list[str]) -> None:
    """Restore superseded atomic_facts to searchable state.

    - Sets lifecycle='active' on superseded atomic_facts
    - Creates new index entries for them (FTS + embedding)
    - Keeps fact_summaries active too (both are searchable)
    """
    for conv in conversations:
        db_path = db_dir / f"{conv}.db"
        conn = sqlite3.connect(str(db_path))

        # Get superseded atomic_facts before changing lifecycle
        facts = _get_superseded_atomic_facts(conn)

        # Restore lifecycle to active
        conn.execute("""
            UPDATE memory_objects SET lifecycle = 'active'
            WHERE type = 'atomic_fact' AND lifecycle = 'superseded'
        """)

        # Create index entries for them
        count = _create_index_entries_for_facts(conn, facts)
        total_restored = len(facts)

        conn.commit()
        conn.close()
        print(f"  Exp B [{conv}]: restored {total_restored} atomic_facts, created {count} index entries")


# ---------------------------------------------------------------------------
# Experiment C: No consolidation (atomic_facts only)
# ---------------------------------------------------------------------------


def prepare_experiment_c(db_dir: Path, conversations: list[str]) -> None:
    """Remove fact_summaries, restore all atomic_facts.

    - Sets lifecycle='superseded' on all fact_summaries
    - Sets lifecycle='active' on all atomic_facts
    - Removes index entries pointing to fact_summaries
    - Creates new index entries for atomic_facts
    """
    for conv in conversations:
        db_path = db_dir / f"{conv}.db"
        conn = sqlite3.connect(str(db_path))

        # Get all superseded atomic_facts
        facts = _get_superseded_atomic_facts(conn)

        # Supersede all fact_summaries
        conn.execute("""
            UPDATE memory_objects SET lifecycle = 'superseded'
            WHERE type = 'fact_summary'
        """)

        # Remove their index entries
        conn.execute("""
            DELETE FROM index_entries
            WHERE target_id IN (
                SELECT id FROM memory_objects WHERE type = 'fact_summary'
            )
        """)
        # Remove their FTS entries
        conn.execute("""
            DELETE FROM lexical_fts
            WHERE target_id IN (
                SELECT id FROM memory_objects WHERE type = 'fact_summary'
            )
        """)

        # Activate all atomic_facts
        conn.execute("""
            UPDATE memory_objects SET lifecycle = 'active'
            WHERE type = 'atomic_fact'
        """)

        # Create index entries for restored atomic_facts
        count = _create_index_entries_for_facts(conn, facts)

        conn.commit()
        conn.close()
        print(f"  Exp C [{conv}]: superseded fact_summaries, restored {len(facts)} AFs, {count} index entries")


# ---------------------------------------------------------------------------
# Experiment D: Capped summaries (max N facts per summary)
# ---------------------------------------------------------------------------

MAX_FACTS_PER_SUMMARY = 5


def prepare_experiment_d(db_dir: Path, conversations: list[str]) -> None:
    """Split large fact_summaries into smaller chunks.

    For each fact_summary with >MAX_FACTS_PER_SUMMARY constituent facts:
    - Split the summary text by comma/semicolon into chunks
    - Create new fact_summary records for each chunk
    - Supersede the original
    - Keep atomic_facts superseded (as current behavior)
    """
    for conv in conversations:
        db_path = db_dir / f"{conv}.db"
        conn = sqlite3.connect(str(db_path))

        rows = conn.execute("""
            SELECT id, payload_json, subject, container_ref, visibility, actor_ref
            FROM memory_objects
            WHERE type = 'fact_summary' AND lifecycle = 'active'
        """).fetchall()

        split_count = 0
        new_summaries = 0

        for mid, pjson, subject, container_ref, visibility, actor_ref in rows:
            payload = json.loads(pjson)
            summary = payload.get("summary", "")

            # Split by semicolons (fact_summary uses "; " as delimiter between facts)
            parts = [p.strip() for p in summary.split(";") if p.strip()]

            if len(parts) <= MAX_FACTS_PER_SUMMARY:
                continue  # Small enough, keep as-is

            # Split into chunks of MAX_FACTS_PER_SUMMARY
            chunks = []
            for i in range(0, len(parts), MAX_FACTS_PER_SUMMARY):
                chunk_parts = parts[i:i + MAX_FACTS_PER_SUMMARY]
                chunks.append("; ".join(chunk_parts))

            # Supersede the original
            conn.execute("UPDATE memory_objects SET lifecycle = 'superseded' WHERE id = ?", (mid,))

            # Remove old index entries
            old_ie_ids = [r[0] for r in conn.execute(
                "SELECT id FROM index_entries WHERE target_id = ?", (mid,)
            ).fetchall()]
            for ie_id in old_ie_ids:
                conn.execute("DELETE FROM lexical_fts WHERE index_entry_id = ?", (ie_id,))
            conn.execute("DELETE FROM index_entries WHERE target_id = ?", (mid,))

            # Create new fact_summaries for each chunk
            category = payload.get("category", "")
            for chunk in chunks:
                new_id = str(uuid.uuid4())
                new_payload = {**payload, "summary": chunk}
                conn.execute("""
                    INSERT INTO memory_objects (id, type, schema_id, schema_version,
                        payload_json, lifecycle, visibility, container_ref,
                        actor_ref, subject, created_at)
                    VALUES (?, 'fact_summary', 'fact_summary', 'v1', ?, 'active',
                            ?, ?, ?, ?, datetime('now'))
                """, (new_id, json.dumps(new_payload), visibility, container_ref,
                      actor_ref, subject))

                # Create index entries
                lexical_text = chunk.lower()
                embedding_text = f"{subject}: {chunk}" if subject else chunk

                ie_stmt = str(uuid.uuid4())
                ie_emb = str(uuid.uuid4())

                conn.execute("""
                    INSERT INTO index_entries (id, target_kind, target_id, index_type,
                                               text_view, text_view_name, provider_name, provider_version)
                    VALUES (?, 'memory_object', ?, 'lexical', ?, 'memory_object.fact_summary_statement', '', '')
                """, (ie_stmt, new_id, lexical_text))

                conn.execute("""
                    INSERT INTO lexical_fts (text_view, index_entry_id, target_kind, target_id,
                                              text_view_name, container_ref)
                    VALUES (?, ?, 'memory_object', ?, 'memory_object.fact_summary_statement', ?)
                """, (lexical_text, ie_stmt, new_id, container_ref))

                conn.execute("""
                    INSERT INTO index_entries (id, target_kind, target_id, index_type,
                                               text_view, text_view_name, provider_name, provider_version)
                    VALUES (?, 'memory_object', ?, 'embedding', ?, 'memory_object.fact_summary_embedding', '', '')
                """, (ie_emb, new_id, embedding_text))

                new_summaries += 1

            split_count += 1

        conn.commit()
        conn.close()
        print(f"  Exp D [{conv}]: split {split_count} large summaries into {new_summaries} capped summaries")


# ---------------------------------------------------------------------------
# Experiment E: Fragment indexing
# ---------------------------------------------------------------------------


def prepare_experiment_e(db_dir: Path, conversations: list[str]) -> None:
    """Add per-fact index entries to existing fact_summaries.

    For each active fact_summary, parse individual facts from the summary text
    and create additional index entries for each fact fragment.
    Keeps the original summary index entry too.
    """
    for conv in conversations:
        db_path = db_dir / f"{conv}.db"
        conn = sqlite3.connect(str(db_path))

        rows = conn.execute("""
            SELECT id, payload_json, subject, container_ref
            FROM memory_objects
            WHERE type = 'fact_summary' AND lifecycle = 'active'
        """).fetchall()

        total_fragments = 0

        for mid, pjson, subject, container_ref in rows:
            payload = json.loads(pjson)
            summary = payload.get("summary", "")

            # Split by semicolons into individual fact fragments
            parts = [p.strip() for p in summary.split(";") if p.strip() and len(p.strip()) > 10]

            for part in parts:
                frag_id_stmt = str(uuid.uuid4())
                frag_id_emb = str(uuid.uuid4())

                lexical_text = part.lower()
                embedding_text = f"{subject}: {part}" if subject else part

                # Lexical index entry pointing to the PARENT fact_summary
                conn.execute("""
                    INSERT INTO index_entries (id, target_kind, target_id, index_type,
                                               text_view, text_view_name, provider_name, provider_version)
                    VALUES (?, 'memory_object', ?, 'lexical', ?, 'memory_object.fact_fragment_statement', '', '')
                """, (frag_id_stmt, mid, lexical_text))

                conn.execute("""
                    INSERT INTO lexical_fts (text_view, index_entry_id, target_kind, target_id,
                                              text_view_name, container_ref)
                    VALUES (?, ?, 'memory_object', ?, 'memory_object.fact_fragment_statement', ?)
                """, (lexical_text, frag_id_stmt, mid, container_ref))

                # Embedding index entry
                conn.execute("""
                    INSERT INTO index_entries (id, target_kind, target_id, index_type,
                                               text_view, text_view_name, provider_name, provider_version)
                    VALUES (?, 'memory_object', ?, 'embedding', ?, 'memory_object.fact_fragment_embedding', '', '')
                """, (frag_id_emb, mid, embedding_text))

                total_fragments += 1

        conn.commit()
        conn.close()
        print(f"  Exp E [{conv}]: added {total_fragments} fragment index entries")


# ---------------------------------------------------------------------------
# Experiment F: Envelope bridge (populate envelopes on fact types)
# ---------------------------------------------------------------------------


def prepare_experiment_f(db_dir: Path, conversations: list[str]) -> None:
    """Populate MemoryEnvelope on atomic_fact and fact_summary objects.

    Simulates what the code change in conversational_knowledge.py produces
    by updating the envelope_json column on existing memory objects.
    """
    import json as _json

    ENVELOPE_TEMPLATE = {
        "schema_id": "core.memory_envelope",
        "schema_version": "v1",
        "kind": "finding",
        "confidence": "medium",
    }

    for conv in conversations:
        db_path = db_dir / f"{conv}.db"
        conn = sqlite3.connect(str(db_path))

        # Update atomic_facts
        rows = conn.execute("""
            SELECT id, payload_json, container_ref
            FROM memory_objects
            WHERE type IN ('atomic_fact', 'fact_summary')
            AND envelope_json IS NULL
        """).fetchall()

        updated = 0
        for mid, pjson, container_ref in rows:
            payload = json.loads(pjson)
            subject = str(payload.get("subject") or "").strip()

            subjects = []
            if subject:
                subjects.append({"kind": "surface", "value": subject})

            # Determine thread_ref and producer_kind from type
            mtype = conn.execute(
                "SELECT type FROM memory_objects WHERE id = ?", (mid,)
            ).fetchone()[0]

            thread_ref = payload.get("thread_ref")  # atomic_fact has this
            producer_kind = "item_extraction" if mtype == "atomic_fact" else "consolidation"

            envelope = {
                **ENVELOPE_TEMPLATE,
                "scope": {
                    "container_ref": container_ref or "",
                    "thread_ref": thread_ref,
                },
                "derivation": {
                    "producer_kind": producer_kind,
                    "producer_schema_id": "fact_extraction" if mtype == "atomic_fact" else "fact_consolidation",
                    "producer_schema_version": "v2" if mtype == "atomic_fact" else "v1",
                },
                "subjects": subjects,
            }

            conn.execute(
                "UPDATE memory_objects SET envelope_json = ? WHERE id = ?",
                (_json.dumps(envelope), mid),
            )
            updated += 1

        conn.commit()
        conn.close()
        print(f"  Exp F [{conv}]: populated envelopes on {updated} fact objects")


# ---------------------------------------------------------------------------
# Run benchmark QA phase
# ---------------------------------------------------------------------------


def run_experiment(
    experiment_name: str,
    db_cache_dir: Path,
    conversations: list[str],
    output_dir: Path,
    *,
    cache_dir: Path | None = None,
    rate_limit: int = 20,
    max_workers: int = 4,
) -> Path:
    """Run LoCoMo QA evaluation with a specific DB cache configuration."""
    from app.config import AppConfig
    from evals.locomo_benchmark import run_locomo_benchmark

    run_dir = run_locomo_benchmark(
        dataset_path=Path("evals/locomo/datasets/locomo10.json"),
        output_root=output_dir,
        config=AppConfig.from_env(),
        run_name=f"experiment-{experiment_name}",
        conversation_ids=conversations,
        db_cache_dir=db_cache_dir,
        cache_dir=cache_dir,
        verbose_results=True,
        rate_limit=rate_limit,
        max_workers=max_workers,
        no_eval_cache=False,
        separate_judge=False,
    )
    return run_dir


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------


def load_results(results_path: Path) -> list[dict]:
    results = []
    with open(results_path) as f:
        for line in f:
            if line.strip():
                results.append(json.loads(line))
    return results


def analyze_results(results: list[dict], label: str) -> dict:
    """Compute per-category metrics for a set of results."""
    total = len(results)
    correct = sum(1 for r in results if r["correct"])
    gic = sum(1 for r in results if r.get("gold_in_context", False))

    by_cat = defaultdict(lambda: {"total": 0, "correct": 0, "gic": 0})
    for r in results:
        cat = r["category_name"]
        by_cat[cat]["total"] += 1
        if r["correct"]:
            by_cat[cat]["correct"] += 1
        if r.get("gold_in_context", False):
            by_cat[cat]["gic"] += 1

    # Result diversity: unique memory texts per query
    unique_per_query = []
    for r in results:
        texts = set()
        for rr in r.get("retrieved_results", []):
            if rr.get("kind") == "memory_hit":
                texts.add(rr.get("text", "")[:80])
        unique_per_query.append(len(texts))
    avg_diversity = sum(unique_per_query) / len(unique_per_query) if unique_per_query else 0

    # Searchable items: count unique memory texts across ALL queries
    all_memory_texts = set()
    for r in results:
        for rr in r.get("retrieved_results", []):
            if rr.get("kind") == "memory_hit":
                all_memory_texts.add(rr.get("text", "")[:80])

    return {
        "label": label,
        "total": total,
        "correct": correct,
        "accuracy": correct / total * 100 if total else 0,
        "gic": gic,
        "gic_rate": gic / total * 100 if total else 0,
        "avg_diversity": avg_diversity,
        "unique_facts_seen": len(all_memory_texts),
        "by_category": dict(by_cat),
    }


def print_comparison(all_analyses: list[dict]) -> None:
    """Print comparison table across experiments."""
    cats = ["single_hop", "multi_hop", "open_domain", "temporal"]

    print("\n" + "=" * 100)
    print("EXPERIMENT COMPARISON")
    print("=" * 100)

    # Overall
    header = f"{'Experiment':<20} | {'Accuracy':>8} | {'GiC Rate':>8} | {'Diversity':>9} | {'Unique Facts':>12}"
    print(f"\n{header}")
    print("-" * len(header))
    for a in all_analyses:
        print(f"{a['label']:<20} | {a['accuracy']:>7.1f}% | {a['gic_rate']:>7.1f}% | {a['avg_diversity']:>9.1f} | {a['unique_facts_seen']:>12}")

    # Per category: accuracy
    print(f"\n{'ACCURACY by category':<20}", end="")
    for cat in cats:
        print(f" | {cat:>12}", end="")
    print()
    print("-" * (20 + 15 * len(cats)))
    for a in all_analyses:
        print(f"{a['label']:<20}", end="")
        for cat in cats:
            bc = a["by_category"].get(cat, {"total": 0, "correct": 0})
            acc = bc["correct"] / bc["total"] * 100 if bc["total"] else 0
            print(f" | {acc:>11.1f}%", end="")
        print()

    # Per category: gold-in-context
    print(f"\n{'GiC RATE by category':<20}", end="")
    for cat in cats:
        print(f" | {cat:>12}", end="")
    print()
    print("-" * (20 + 15 * len(cats)))
    for a in all_analyses:
        print(f"{a['label']:<20}", end="")
        for cat in cats:
            bc = a["by_category"].get(cat, {"total": 0, "gic": 0})
            gic = bc["gic"] / bc["total"] * 100 if bc["total"] else 0
            print(f" | {gic:>11.1f}%", end="")
        print()

    # Delta from baseline
    if len(all_analyses) > 1:
        baseline = all_analyses[0]
        print(f"\n{'DELTA vs baseline':<20}", end="")
        for cat in cats:
            print(f" | {cat:>12}", end="")
        print()
        print("-" * (20 + 15 * len(cats)))
        for a in all_analyses[1:]:
            print(f"{a['label']:<20}", end="")
            for cat in cats:
                bc = a["by_category"].get(cat, {"total": 0, "correct": 0})
                bb = baseline["by_category"].get(cat, {"total": 0, "correct": 0})
                acc_a = bc["correct"] / bc["total"] * 100 if bc["total"] else 0
                acc_b = bb["correct"] / bb["total"] * 100 if bb["total"] else 0
                delta = acc_a - acc_b
                sign = "+" if delta >= 0 else ""
                print(f" | {sign}{delta:>10.1f}%", end="")
            print()


# ---------------------------------------------------------------------------
# Scale projections
# ---------------------------------------------------------------------------


def compute_scale_projections(conversations: list[str]) -> None:
    """Project index size and growth rate for each experiment config."""
    print("\n" + "=" * 100)
    print("SCALE PROJECTIONS")
    print("=" * 100)

    for conv in conversations:
        db_path = SOURCE_DB_CACHE / f"{conv}.db"
        conn = sqlite3.connect(str(db_path))

        n_turns = conn.execute("SELECT COUNT(*) FROM source_items").fetchone()[0]
        af_total = conn.execute("SELECT COUNT(*) FROM memory_objects WHERE type='atomic_fact'").fetchone()[0]
        af_active = conn.execute("SELECT COUNT(*) FROM memory_objects WHERE type='atomic_fact' AND lifecycle='active'").fetchone()[0]
        fs_active = conn.execute("SELECT COUNT(*) FROM memory_objects WHERE type='fact_summary' AND lifecycle='active'").fetchone()[0]

        # Count how many fact_summaries would be split (>5 semicolons)
        rows = conn.execute("""
            SELECT payload_json FROM memory_objects
            WHERE type = 'fact_summary' AND lifecycle = 'active'
        """).fetchall()
        split_summaries = 0
        total_after_split = 0
        total_fragments = 0
        for (pjson,) in rows:
            payload = json.loads(pjson)
            summary = payload.get("summary", "")
            parts = [p.strip() for p in summary.split(";") if p.strip()]
            total_fragments += len(parts)
            if len(parts) > MAX_FACTS_PER_SUMMARY:
                split_summaries += 1
                total_after_split += -(-len(parts) // MAX_FACTS_PER_SUMMARY)  # ceil div
            else:
                total_after_split += 1

        conn.close()

        config_a = af_active + fs_active
        config_b = af_total + fs_active
        config_c = af_total
        config_d = af_active + total_after_split
        config_e = config_a  # same objects, just more index entries

        print(f"\n  {conv} ({n_turns} turns, {af_total} atomic_facts, {fs_active} active summaries):")
        print(f"    {'Config':<25} | {'Searchable':>10} | {'Per turn':>8} | {'At 1K turns':>11} | {'At 5K turns':>11}")
        print(f"    {'-'*25}-+-{'-'*10}-+-{'-'*8}-+-{'-'*11}-+-{'-'*11}")
        for label, items in [
            ("A (current)", config_a),
            ("B (soft lifecycle)", config_b),
            ("C (no consolidation)", config_c),
            ("D (capped summaries)", config_d),
            ("E (fragment index)", config_e),
        ]:
            per_turn = items / n_turns
            at_1k = int(per_turn * 1000)
            at_5k = int(per_turn * 5000)
            print(f"    {label:<25} | {items:>10} | {per_turn:>8.2f} | {at_1k:>11} | {at_5k:>11}")

        print(f"    Note: Exp E adds {total_fragments} fragment index entries (same objects, more entry points)")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description="Run retrieval architecture experiments")
    parser.add_argument(
        "--experiments", nargs="*", default=["B", "C", "D", "E"],
        help="Experiments to run (B, C, D, E). A is always included as baseline.",
    )
    parser.add_argument(
        "--conversations", nargs="*", default=DEFAULT_CONVERSATIONS,
        help="Conversations to evaluate on.",
    )
    parser.add_argument("--cache-dir", type=Path, default=None)
    parser.add_argument("--rate-limit", type=int, default=20)
    parser.add_argument("--max-workers", type=int, default=4)
    parser.add_argument("--skip-run", action="store_true", help="Skip benchmark runs, just analyze existing results")
    args = parser.parse_args()

    experiments = [e.upper() for e in args.experiments]
    conversations = args.conversations

    print(f"Experiments: A (baseline) + {experiments}")
    print(f"Conversations: {conversations}")

    # -----------------------------------------------------------------------
    # Step 1: Prepare baseline (filter from existing full results)
    # -----------------------------------------------------------------------
    print("\n--- Baseline (A): Loading from existing results ---")
    if BASELINE_RESULTS.exists():
        all_baseline = load_results(BASELINE_RESULTS)
        baseline_results = [r for r in all_baseline if r["sample_id"] in conversations]
        print(f"  Loaded {len(baseline_results)} questions from baseline ({len(all_baseline)} total)")
    else:
        print(f"  ERROR: Baseline results not found at {BASELINE_RESULTS}")
        return 1

    all_analyses = [analyze_results(baseline_results, "A (baseline)")]

    if args.skip_run:
        # Just analyze existing experiment results
        for exp in experiments:
            exp_output = EXPERIMENT_DIR / f"experiment-{exp}"
            results_files = list(exp_output.rglob("results.jsonl")) if exp_output.exists() else []
            if results_files:
                exp_results = load_results(results_files[0])
                exp_results = [r for r in exp_results if r["sample_id"] in conversations]
                all_analyses.append(analyze_results(exp_results, f"{exp}"))
                print(f"  Loaded {len(exp_results)} results for experiment {exp}")
            else:
                print(f"  No results found for experiment {exp}")
        print_comparison(all_analyses)
        compute_scale_projections(conversations)
        return 0

    # -----------------------------------------------------------------------
    # Step 2: Prepare and run each experiment
    # -----------------------------------------------------------------------
    exp_configs = {
        "B": ("Soft lifecycle", prepare_experiment_b),
        "C": ("No consolidation", prepare_experiment_c),
        "D": ("Capped summaries", prepare_experiment_d),
        "E": ("Fragment indexing", prepare_experiment_e),
        "F": ("Envelope bridge", prepare_experiment_f),
    }

    for exp in experiments:
        if exp not in exp_configs:
            print(f"  Unknown experiment: {exp}")
            continue

        label, prepare_fn = exp_configs[exp]
        exp_db_dir = EXPERIMENT_DIR / f"db_cache_{exp}"
        exp_output = EXPERIMENT_DIR / f"experiment-{exp}"

        print(f"\n--- Experiment {exp}: {label} ---")

        # Copy cached DBs
        print(f"  Copying DB cache...")
        _copy_db_cache(SOURCE_DB_CACHE, exp_db_dir, conversations)

        # Apply modifications
        print(f"  Preparing DB modifications...")
        prepare_fn(exp_db_dir, conversations)

        # Run benchmark QA phase
        print(f"  Running benchmark QA phase...")
        try:
            run_dir = run_experiment(
                experiment_name=exp,
                db_cache_dir=exp_db_dir,
                conversations=conversations,
                output_dir=exp_output,
                cache_dir=args.cache_dir,
                rate_limit=args.rate_limit,
                max_workers=args.max_workers,
            )
            print(f"  Results: {run_dir}")

            # Load and analyze
            results_file = run_dir / "results.jsonl"
            if results_file.exists():
                exp_results = load_results(results_file)
                all_analyses.append(analyze_results(exp_results, f"{exp} ({label})"))
            else:
                print(f"  WARNING: No results.jsonl in {run_dir}")
        except Exception as e:
            print(f"  ERROR running experiment {exp}: {e}")
            import traceback
            traceback.print_exc()

    # -----------------------------------------------------------------------
    # Step 3: Compare and report
    # -----------------------------------------------------------------------
    print_comparison(all_analyses)
    compute_scale_projections(conversations)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
