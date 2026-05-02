"""Analyze token document-frequency across active memory objects.

Outputs tokens appearing in >30% of documents, suitable for use as a
high-frequency content word set in the content-overlap gate.

Usage:
    python scripts/analyze_corpus_frequencies.py [--db PATH] [--threshold 0.3]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path

from sqlalchemy import create_engine, text

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from semantic.common import content_tokens


def _extract_text_from_payload(payload_json: str) -> str:
    """Extract searchable text from a memory object's payload."""
    try:
        payload = json.loads(payload_json)
    except (json.JSONDecodeError, TypeError):
        return ""
    parts = []
    for key in ("statement", "decision", "rationale", "summary", "finding", "subject", "category", "description"):
        val = payload.get(key)
        if val and isinstance(val, str):
            parts.append(val)
    return " ".join(parts)


def main() -> int:
    parser = argparse.ArgumentParser(description="Corpus token frequency analysis")
    parser.add_argument("--db", default=None, help="SQLite DB path")
    parser.add_argument("--threshold", type=float, default=0.3, help="Doc frequency threshold (default 0.3)")
    args = parser.parse_args()

    if args.db:
        db_path = args.db
    else:
        db_path = os.path.expanduser("~/.pallium/data/pallium.db")

    if not Path(db_path).exists():
        print(f"DB not found at {db_path}", file=sys.stderr)
        return 1

    engine = create_engine(f"sqlite:///{db_path}")

    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT payload_json FROM memory_objects WHERE lifecycle = 'active'
        """)).fetchall()

    if not rows:
        print("No active memory objects found.", file=sys.stderr)
        return 1

    total_docs = len(rows)
    doc_freq: Counter[str] = Counter()

    for (payload_json,) in rows:
        if not payload_json:
            continue
        text_content = _extract_text_from_payload(payload_json)
        if not text_content:
            continue
        tokens = content_tokens(text_content)
        for token in tokens:
            doc_freq[token] += 1

    threshold_count = int(total_docs * args.threshold)
    high_freq = sorted(
        [(token, count, count / total_docs) for token, count in doc_freq.items() if count > threshold_count],
        key=lambda x: -x[2],
    )

    print(f"Total documents: {total_docs}")
    print(f"Threshold: >{args.threshold:.0%} (>{threshold_count} docs)")
    print(f"\nTokens appearing in >{args.threshold:.0%} of documents:")
    print(f"{'Token':<30} {'DocFreq':>8} {'Pct':>8}")
    print("-" * 50)
    for token, count, pct in high_freq:
        print(f"{token:<30} {count:>8} {pct:>7.1%}")

    print(f"\n# Python frozenset for semantic/common.py:")
    token_strs = ', '.join(f'"{t}"' for t, _, _ in high_freq)
    print(f"HIGH_FREQUENCY_CONTENT_WORDS: frozenset[str] = frozenset({{{token_strs}}})")

    return 0


if __name__ == "__main__":
    sys.exit(main())
