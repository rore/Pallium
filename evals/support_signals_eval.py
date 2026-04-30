"""Evaluate proposed support_signals for extraction quality scoring.

Reads existing semantic regression result files (JSONL) and computes
the three proposed signals against each promoted memory object:

  - evidence_token_overlap: fraction of tokens in the primary extracted
    text field that appear in the source content
  - evidence_span_ratio: char-length ratio of evidence_text to
    source_content (decision/investigation only)
  - source_signal_density: count of non-null semantic signals, bucketed
    into low/medium/high

Reports distributions by memory type, identifies whether signals
discriminate between good and weak extractions, and flags cases where
current type-based confidence would disagree with signal-based quality.

Usage:
    python -m evals.support_signals_eval [--result-files FILE ...]

Defaults to gate-pass-winner + regression-post-constraint-refactor +
constraint regression results.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from statistics import mean, median, stdev

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.text import tokenize_text


# ── Signal computation ──────────────────────────────────────────────

SEMANTIC_SIGNAL_FIELDS = (
    "subject_hints",
    "work_refs",
    "key_finding_text",
    "progress_text",
    "blocker_text",
    "next_step_text",
    "constraint_text",
)

PRIMARY_TEXT_FIELD = {
    "decision": "decision_text",
    "investigation_outcome": "investigation_text",
    "interest": "interest_text",
    "constraint_memory": "constraint_text",
    "turn_summary": "summary",
    "thread_summary": "summary",
    "task_checkpoint": "summary",
    "pattern_memory": "summary",
    "continuity_memory": "summary",
}

EVIDENCE_TEXT_FIELD = {
    "decision": "decision_evidence_text",
    "investigation_outcome": "investigation_evidence_text",
}

TYPE_BASED_CONFIDENCE = {
    "decision": "high",
    "investigation_outcome": "high",
    "constraint_memory": "medium",
    "task_checkpoint": "medium",
    "thread_summary": "medium",
    "continuity_memory": "medium",
    "pattern_memory": "medium",
    "interest": "medium",
    "turn_summary": "low",
}


@dataclass
class SupportSignals:
    memory_type: str
    source_id: str
    evidence_token_overlap: float | None
    evidence_span_ratio: float | None
    source_signal_density: str  # low / medium / high
    signal_count: int
    type_confidence: str
    primary_text: str
    source_content: str


def compute_evidence_token_overlap(
    primary_text: str | None, source_content: str
) -> float | None:
    if not primary_text:
        return None
    primary_tokens = set(tokenize_text(primary_text))
    if not primary_tokens:
        return None
    source_tokens = set(tokenize_text(source_content))
    if not source_tokens:
        return 0.0
    overlap = primary_tokens & source_tokens
    return len(overlap) / len(primary_tokens)


def compute_evidence_span_ratio(
    evidence_text: str | None, source_content: str
) -> float | None:
    if not evidence_text:
        return None
    source_len = len(source_content.strip())
    if source_len == 0:
        return None
    return len(evidence_text.strip()) / source_len


def compute_signal_density(extraction: dict) -> tuple[str, int]:
    count = 0
    for field in SEMANTIC_SIGNAL_FIELDS:
        value = extraction.get(field)
        if value:
            if isinstance(value, (list, tuple)) and len(value) > 0:
                count += 1
            elif isinstance(value, str) and value.strip():
                count += 1
    if count >= 4:
        return "high", count
    elif count >= 2:
        return "medium", count
    else:
        return "low", count


def analyze_record(record: dict) -> list[SupportSignals]:
    source_item = record.get("source_item", {})
    source_content = source_item.get("content", "")
    source_id = source_item.get("source_id", "unknown")
    extraction = record.get("normalized_extraction", {})
    artifacts = record.get("artifacts", {})
    memory_objects = artifacts.get("memory_objects", [])

    results = []
    for mo in memory_objects:
        mtype = mo.get("type", "unknown")
        primary_field = PRIMARY_TEXT_FIELD.get(mtype, "summary")
        primary_text = extraction.get(primary_field) or mo.get("payload", {}).get(primary_field, "")
        if mtype == "turn_summary" and not primary_text:
            primary_text = extraction.get("summary", "")

        evidence_field = EVIDENCE_TEXT_FIELD.get(mtype)
        evidence_text = extraction.get(evidence_field) if evidence_field else None

        token_overlap = compute_evidence_token_overlap(primary_text, source_content)
        span_ratio = compute_evidence_span_ratio(evidence_text, source_content)
        density_bucket, signal_count = compute_signal_density(extraction)

        type_conf = TYPE_BASED_CONFIDENCE.get(mtype, "unknown")
        if mtype == "turn_summary" and signal_count > 0:
            type_conf = "medium"

        results.append(SupportSignals(
            memory_type=mtype,
            source_id=source_id,
            evidence_token_overlap=token_overlap,
            evidence_span_ratio=span_ratio,
            source_signal_density=density_bucket,
            signal_count=signal_count,
            type_confidence=type_conf,
            primary_text=primary_text or "",
            source_content=source_content,
        ))
    return results


# ── Reporting ──────────────────────────────────────────────────────

def fmt(val: float | None, decimals: int = 3) -> str:
    if val is None:
        return "  n/a "
    return f"{val:6.{decimals}f}"


def distribution_stats(values: list[float]) -> str:
    if not values:
        return "no data"
    n = len(values)
    mn = min(values)
    mx = max(values)
    avg = mean(values)
    med = median(values)
    sd = stdev(values) if n > 1 else 0.0
    return f"n={n:3d}  min={mn:.3f}  max={mx:.3f}  mean={avg:.3f}  median={med:.3f}  stdev={sd:.3f}"


def report(all_signals: list[SupportSignals]) -> None:
    print("=" * 80)
    print("SUPPORT SIGNALS EVALUATION")
    print(f"Total promoted memory objects analyzed: {len(all_signals)}")
    print("=" * 80)

    # Group by memory type
    by_type: dict[str, list[SupportSignals]] = {}
    for s in all_signals:
        by_type.setdefault(s.memory_type, []).append(s)

    # 1. Evidence token overlap distribution by type
    print("\n-- Evidence Token Overlap (fraction of primary-text tokens found in source) --\n")
    all_overlaps: list[float] = []
    for mtype in sorted(by_type):
        overlaps = [s.evidence_token_overlap for s in by_type[mtype] if s.evidence_token_overlap is not None]
        all_overlaps.extend(overlaps)
        print(f"  {mtype:30s}  {distribution_stats(overlaps)}")
    print(f"  {'ALL':30s}  {distribution_stats(all_overlaps)}")

    # 2. Evidence span ratio distribution (decision/investigation only)
    print("\n-- Evidence Span Ratio (evidence_text length / source_content length) --\n")
    all_spans: list[float] = []
    for mtype in sorted(by_type):
        spans = [s.evidence_span_ratio for s in by_type[mtype] if s.evidence_span_ratio is not None]
        all_spans.extend(spans)
        if spans:
            print(f"  {mtype:30s}  {distribution_stats(spans)}")
    if all_spans:
        print(f"  {'ALL':30s}  {distribution_stats(all_spans)}")
    else:
        print("  No types with evidence_text fields in this dataset.")

    # 3. Signal density distribution by type
    print("\n-- Source Signal Density (count of non-null semantic signals) --\n")
    for mtype in sorted(by_type):
        counts = [s.signal_count for s in by_type[mtype]]
        buckets = [s.source_signal_density for s in by_type[mtype]]
        low_n = buckets.count("low")
        med_n = buckets.count("medium")
        high_n = buckets.count("high")
        avg_count = mean(counts) if counts else 0
        print(f"  {mtype:30s}  n={len(counts):3d}  avg_signals={avg_count:.1f}  low={low_n}  medium={med_n}  high={high_n}")

    # 4. Discrimination analysis: do the signals vary meaningfully?
    print("\n-- Discrimination Analysis --\n")

    overlap_values = [s.evidence_token_overlap for s in all_signals if s.evidence_token_overlap is not None]
    if overlap_values:
        sd = stdev(overlap_values) if len(overlap_values) > 1 else 0
        print(f"  evidence_token_overlap:  stdev={sd:.3f}  range=[{min(overlap_values):.3f}, {max(overlap_values):.3f}]")
        if sd < 0.05:
            print("    WARNING: Low variance -- this signal may not discriminate between good and weak extractions")
        else:
            print("    OK: Meaningful variance -- this signal can discriminate")

    span_values = [s.evidence_span_ratio for s in all_signals if s.evidence_span_ratio is not None]
    if span_values:
        sd = stdev(span_values) if len(span_values) > 1 else 0
        print(f"  evidence_span_ratio:     stdev={sd:.3f}  range=[{min(span_values):.3f}, {max(span_values):.3f}]")
        if sd < 0.05:
            print("    WARNING: Low variance -- this signal may not discriminate between good and weak extractions")
        else:
            print("    OK: Meaningful variance -- this signal can discriminate")

    density_counts = [s.signal_count for s in all_signals]
    if density_counts:
        sd = stdev(density_counts) if len(density_counts) > 1 else 0
        print(f"  source_signal_density:   stdev={sd:.1f}  range=[{min(density_counts)}, {max(density_counts)}]")
        if sd < 0.5:
            print("    WARNING: Low variance -- this signal may not discriminate")
        else:
            print("    OK: Meaningful variance -- this signal can discriminate")

    # 5. Cross-reference: type-based confidence vs signal quality
    print("\n-- Confidence Disagreement (type confidence vs signal-based quality) --\n")
    print("  Cases where type says 'high' confidence but token overlap is low (<0.5):")
    flagged = 0
    for s in all_signals:
        if s.type_confidence == "high" and s.evidence_token_overlap is not None and s.evidence_token_overlap < 0.5:
            flagged += 1
            print(f"    {s.source_id:30s}  type={s.memory_type:25s}  overlap={s.evidence_token_overlap:.3f}")
            print(f"      primary_text: {s.primary_text[:120]}")
            print(f"      source:       {s.source_content[:120]}")
    if flagged == 0:
        print("    None found -- all high-confidence types have good token overlap")

    print("\n  Cases where type says 'low' confidence but signals are rich (density=high):")
    flagged = 0
    for s in all_signals:
        if s.type_confidence == "low" and s.source_signal_density == "high":
            flagged += 1
            print(f"    {s.source_id:30s}  type={s.memory_type:25s}  signals={s.signal_count}  overlap={fmt(s.evidence_token_overlap)}")
    if flagged == 0:
        print("    None found")

    print("\n  Cases where type says 'low' confidence but token overlap is high (>0.8):")
    flagged = 0
    for s in all_signals:
        if s.type_confidence == "low" and s.evidence_token_overlap is not None and s.evidence_token_overlap > 0.8:
            flagged += 1
            print(f"    {s.source_id:30s}  type={s.memory_type:25s}  overlap={s.evidence_token_overlap:.3f}  signals={s.signal_count}")
    if flagged == 0:
        print("    None found")

    # 6. Per-record detail table
    print("\n-- Per-Record Detail --\n")
    print(f"  {'source_id':30s}  {'type':25s}  {'overlap':>8s}  {'span':>8s}  {'density':>8s}  {'#sig':>4s}  {'conf':>6s}")
    print(f"  {'-'*30}  {'-'*25}  {'-'*8}  {'-'*8}  {'-'*8}  {'-'*4}  {'-'*6}")
    for s in all_signals:
        print(
            f"  {s.source_id:30s}  {s.memory_type:25s}  "
            f"{fmt(s.evidence_token_overlap)}  "
            f"{fmt(s.evidence_span_ratio)}  "
            f"{s.source_signal_density:>8s}  "
            f"{s.signal_count:>4d}  "
            f"{s.type_confidence:>6s}"
        )

    # 7. Bottom-line verdict
    print("\n-- Verdict --\n")
    useful_signals = []
    if overlap_values and (stdev(overlap_values) if len(overlap_values) > 1 else 0) >= 0.05:
        useful_signals.append("evidence_token_overlap")
    if span_values and (stdev(span_values) if len(span_values) > 1 else 0) >= 0.05:
        useful_signals.append("evidence_span_ratio")
    if density_counts and (stdev(density_counts) if len(density_counts) > 1 else 0) >= 0.5:
        useful_signals.append("source_signal_density")

    if useful_signals:
        print(f"  Discriminative signals: {', '.join(useful_signals)}")
        print("  -> Proceed to implementation: these signals separate good extractions from weak ones.")
    else:
        print("  No signals showed sufficient variance to discriminate.")
        print("  -> Do NOT proceed to implementation without redesigning the signals.")


# ── Main ──────────────────────────────────────────────────────────

DEFAULT_RESULT_FILES = [
    "evals/semantic/output/gate-pass-winner/results.jsonl",
    "evals/semantic/output/constraint/regression-constraint-items/results.jsonl",
    "evals/semantic/output/regression-post-constraint-refactor/results.jsonl",
]


def load_results(paths: list[str]) -> list[dict]:
    records = []
    seen_source_ids: set[str] = set()
    for path_str in paths:
        path = PROJECT_ROOT / path_str
        if not path.exists():
            print(f"  Warning: {path} not found, skipping", file=sys.stderr)
            continue
        with open(path) as f:
            for line in f:
                record = json.loads(line)
                source_id = record.get("source_item", {}).get("source_id", "")
                if source_id in seen_source_ids:
                    continue
                seen_source_ids.add(source_id)
                records.append(record)
    return records


def main():
    parser = argparse.ArgumentParser(description="Evaluate proposed support signals for extraction quality")
    parser.add_argument(
        "--result-files",
        nargs="+",
        default=DEFAULT_RESULT_FILES,
        help="Paths to JSONL result files (relative to project root)",
    )
    args = parser.parse_args()

    print(f"Loading results from {len(args.result_files)} file(s)...")
    records = load_results(args.result_files)
    print(f"Loaded {len(records)} unique records\n")

    all_signals: list[SupportSignals] = []
    for record in records:
        all_signals.extend(analyze_record(record))

    if not all_signals:
        print("No promoted memory objects found in results.")
        return

    report(all_signals)


if __name__ == "__main__":
    main()
