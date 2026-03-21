"""Benchmark failure taxonomy analyzer.

Reads results.jsonl files from benchmark runs and classifies each failure
using a 6-type taxonomy:

    1. MISSING_MEMORY     — memory should have been injected but wasn't
    2. WRONG_MEMORY       — memory was injected but from wrong topic/type
    3. STALE_MEMORY       — older version used instead of updated one
    4. CONTRADICTION      — conflicting memories, wrong one chosen
    5. EXTRACTION_FAILURE — memory was never formed from source events
    6. ABSTENTION_FAILURE — system answered when it should abstain (or vice versa)

Usage:
    python -m tools.benchmark_failure_analyzer <dir> [<dir2> ...]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Failure taxonomy types
# ---------------------------------------------------------------------------

FAILURE_TYPES = [
    "MISSING_MEMORY",
    "WRONG_MEMORY",
    "STALE_MEMORY",
    "CONTRADICTION",
    "EXTRACTION_FAILURE",
    "ABSTENTION_FAILURE",
]

# Severity weights: wrong memory is actively harmful (agent acts on bad info),
# missing memory is suboptimal but safe (agent lacks context but isn't misled).
# For Pallium as a sidecar: injecting wrong memory > injecting stale memory >
# injecting nothing > not injecting when it should.
SEVERITY_WEIGHTS = {
    "WRONG_MEMORY": 3.0,       # Actively harmful — agent acts on bad info
    "STALE_MEMORY": 2.5,       # Harmful — agent acts on outdated info
    "CONTRADICTION": 2.5,      # Harmful — conflicting info injected
    "ABSTENTION_FAILURE": 1.5, # Over-injection is bad (1.5), false abstention is mild (0.5)
    "EXTRACTION_FAILURE": 1.0, # Write-path issue — memory never formed
    "MISSING_MEMORY": 0.5,     # Safe failure — agent lacks context but isn't misled
}

# Subcause-level severity overrides
SUBCAUSE_SEVERITY = {
    "over_injection": 2.0,     # Injecting when shouldn't = harmful
    "false_abstention": 0.5,   # Not injecting when should = mild
}


@dataclass
class ScenarioAnalysis:
    scenario_id: str
    passed: bool
    failure_type: str | None = None
    failure_subcause: str | None = None
    details: str = ""
    retrieval_rank: int | None = None
    expected_in_top_k: bool | None = None
    memories_retrieved: int = 0
    memories_relevant: int = 0
    wrong_memories_injected: int = 0


# ---------------------------------------------------------------------------
# Pass / fail detection (works across benchmark formats)
# ---------------------------------------------------------------------------

def _scenario_passed(r: dict[str, Any]) -> bool:
    """Determine whether a scenario fully passed.

    Different benchmarks express success differently:
    - memory_routing: answer_success AND policy_success
    - work_resumption: no failure_families/gap_signals AND guard checks pass
    We detect the suite and apply the appropriate rule.
    """
    suite = r.get("suite_id", "")

    if suite == "work_resumption":
        # Work-resumption uses failure_families as the primary failure signal.
        # A scenario passes when there are no failure families AND the
        # targeted guards (stale, wrong_memory, boundary) all succeed.
        # non_value_guard_success is a quality metric that is currently
        # false across the board, so we exclude it from the pass gate.
        failure_families = r.get("failure_families", [])
        gap_signals = r.get("gap_signals", [])
        if failure_families or gap_signals:
            return False

        # Check targeted guards (excluding non_value_guard)
        guards = [
            r.get("stale_guard_success"),
            r.get("wrong_memory_guard_success"),
            r.get("thin_agent_boundary_success"),
        ]
        present = [g for g in guards if g is not None]
        if present and not all(present):
            return False

        return True

    # Default (memory_routing, noisy-baseline, etc.)
    answer_ok = r.get("answer_success", True)
    policy_ok = r.get("policy_success", True)
    return bool(answer_ok and policy_ok)


# ---------------------------------------------------------------------------
# Retrieval helpers
# ---------------------------------------------------------------------------

def _retrieval_types(r: dict[str, Any]) -> list[str]:
    """Extract ordered list of memory types from retrieval results."""
    mbr = r.get("memory_backed_retrieval", [])
    types: list[str] = []
    for hit in mbr:
        t = hit.get("type")
        if t:
            types.append(t)
    return types


def _injected_types(r: dict[str, Any]) -> list[str]:
    """Memory types that were actually injected."""
    blocks = r.get("injectable_blocks", [])
    return [b.get("memory_type") for b in blocks if b.get("memory_type")]


def _expected_types(r: dict[str, Any]) -> list[str]:
    """Expected memory types — tries multiple field names."""
    types = r.get("expected_memory_types", [])
    if not types:
        types = r.get("expected_top_memory_types", [])
    if not types:
        exp_top = r.get("expected_top_layer")
        if exp_top:
            types = [exp_top]
    # Also include higher-level expectations
    higher = r.get("expected_higher_level_memory_types", [])
    combined = list(types) + [h for h in higher if h not in types]
    return combined


def _find_expected_rank(r: dict[str, Any]) -> int | None:
    """Find position (1-based) of the first expected memory type in retrieval."""
    expected = set(_expected_types(r))
    if not expected:
        return None
    mbr = r.get("memory_backed_retrieval", [])
    for idx, hit in enumerate(mbr):
        if hit.get("type") in expected:
            return idx + 1
    return None


def _count_relevant(r: dict[str, Any]) -> int:
    """Count how many retrieval hits are of an expected type."""
    expected = set(_expected_types(r))
    mbr = r.get("memory_backed_retrieval", [])
    return sum(1 for h in mbr if h.get("type") in expected)


def _count_wrong_injected(r: dict[str, Any]) -> int:
    """Count injected blocks that are not an expected type."""
    expected = set(_expected_types(r))
    if not expected:
        return 0
    injected = _injected_types(r)
    return sum(1 for t in injected if t not in expected)


# ---------------------------------------------------------------------------
# Classification engine
# ---------------------------------------------------------------------------

def classify_failure(r: dict[str, Any]) -> ScenarioAnalysis:
    """Classify a failed scenario into one of the 6 failure types."""

    sid = r.get("scenario_id", "unknown")
    analysis = ScenarioAnalysis(
        scenario_id=sid,
        passed=False,
        memories_retrieved=len(r.get("memory_backed_retrieval", [])),
        memories_relevant=_count_relevant(r),
        wrong_memories_injected=_count_wrong_injected(r),
        retrieval_rank=_find_expected_rank(r),
    )
    if analysis.retrieval_rank is not None:
        analysis.expected_in_top_k = analysis.retrieval_rank <= 5

    # --- Type 6: ABSTENTION_FAILURE ---
    # Over-injection: should_memory_help=false but memory was injected
    should_help = r.get("should_memory_help")
    should_inject = r.get("should_inject")
    expected_should_inject = r.get("expected_should_inject")

    if should_help is False and should_inject is True:
        analysis.failure_type = "ABSTENTION_FAILURE"
        analysis.failure_subcause = "over_injection"
        analysis.details = (
            "System injected memory when should_memory_help=false."
        )
        return analysis

    if expected_should_inject is False and should_inject is True:
        analysis.failure_type = "ABSTENTION_FAILURE"
        analysis.failure_subcause = "over_injection"
        analysis.details = (
            "System injected memory when expected_should_inject=false."
        )
        return analysis

    # False abstention: should inject but didn't
    if expected_should_inject is True and should_inject is False:
        analysis.failure_type = "ABSTENTION_FAILURE"
        analysis.failure_subcause = "false_abstention"
        analysis.details = (
            "System declined to inject memory when it should have."
        )
        return analysis

    # no_value_overreach: work_resumption guard
    non_value_guard = r.get("non_value_guard_success")
    if non_value_guard is False and should_help is False:
        analysis.failure_type = "ABSTENTION_FAILURE"
        analysis.failure_subcause = "over_injection"
        analysis.details = (
            "non_value_guard_success=false and should_memory_help=false."
        )
        return analysis

    # --- Type 5: EXTRACTION_FAILURE ---
    expected = set(_expected_types(r))
    available = set(r.get("available_memory_types", []))
    available_layers = set(r.get("available_layers", []))
    returned = set(r.get("returned_memory_types", []))

    if expected and available:
        # Only flag types that are truly absent — not layer names that
        # appear in available_layers (e.g. source_evidence is a layer,
        # not a memory type).
        missing_from_available = expected - available - available_layers
        if missing_from_available:
            analysis.failure_type = "EXTRACTION_FAILURE"
            analysis.failure_subcause = "promotion_miss"
            analysis.details = (
                f"Expected types {sorted(missing_from_available)} never created. "
                f"Available: {sorted(available)}."
            )
            return analysis

    # --- Type 3: STALE_MEMORY ---
    failure_families = r.get("failure_families", [])
    if "stale_memory_failure" in failure_families:
        analysis.failure_type = "STALE_MEMORY"
        analysis.failure_subcause = "supersession_miss"
        analysis.details = "stale_memory_failure in failure_families."
        return analysis

    stale_guard = r.get("stale_guard_success")
    if stale_guard is False:
        analysis.failure_type = "STALE_MEMORY"
        analysis.failure_subcause = "temporal_ordering_wrong"
        analysis.details = "stale_guard_success=false."
        return analysis

    # --- Type 2: WRONG_MEMORY ---
    top_layer_match = r.get("top_layer_match")
    top_type_match = r.get("top_memory_type_match")
    forbidden_found = r.get("forbidden_terms_found", [])
    forbidden_layers_hit = r.get("forbidden_layers_hit", [])
    wrong_guard = r.get("wrong_memory_guard_success")

    if forbidden_layers_hit:
        analysis.failure_type = "WRONG_MEMORY"
        analysis.failure_subcause = "wrong_layer"
        analysis.details = (
            f"Forbidden layers hit: {forbidden_layers_hit}."
        )
        return analysis

    if forbidden_found:
        analysis.failure_type = "WRONG_MEMORY"
        analysis.failure_subcause = "topic_contamination"
        analysis.details = (
            f"Forbidden terms found: {forbidden_found}."
        )
        return analysis

    if wrong_guard is False:
        analysis.failure_type = "WRONG_MEMORY"
        analysis.failure_subcause = "wrong_type"
        analysis.details = "wrong_memory_guard_success=false."
        return analysis

    if top_layer_match is False:
        expected_top = r.get("expected_top_layer", "?")
        actual_top = r.get("top_layer", "?")
        analysis.failure_type = "WRONG_MEMORY"
        analysis.failure_subcause = "wrong_layer"
        analysis.details = (
            f"Expected top layer '{expected_top}' but got '{actual_top}'."
        )
        return analysis

    if top_type_match is False:
        expected_type = r.get("expected_top_memory_types", ["?"])
        actual_type = r.get("top_memory_type", "?")
        analysis.failure_type = "WRONG_MEMORY"
        analysis.failure_subcause = "wrong_type"
        analysis.details = (
            f"Expected top type {expected_type} but got '{actual_type}'."
        )
        return analysis

    # Check if expected types are in returned types
    if expected and returned:
        missing_returned = expected - returned
        if missing_returned:
            # Types exist (available) but not returned => retrieval miss
            missing_but_available = missing_returned & available
            if missing_but_available:
                analysis.failure_type = "MISSING_MEMORY"
                analysis.failure_subcause = "filtered_out"
                analysis.details = (
                    f"Expected types {sorted(missing_but_available)} exist but were "
                    f"not in returned results. Returned: {sorted(returned)}."
                )
                return analysis

    # --- Type 4: CONTRADICTION ---
    # Multiple memory types returned with conflicting content and wrong one selected
    if len(returned) > 2 and top_layer_match is False:
        analysis.failure_type = "CONTRADICTION"
        analysis.failure_subcause = "conflict_resolution_fail"
        analysis.details = (
            f"Multiple types returned ({sorted(returned)}), "
            f"wrong one selected as primary."
        )
        return analysis

    # --- Type 1: MISSING_MEMORY ---
    if should_inject and not r.get("injectable_blocks"):
        analysis.failure_type = "MISSING_MEMORY"
        analysis.failure_subcause = "retrieval_miss"
        analysis.details = "Should inject but no injectable blocks produced."
        return analysis

    # Fallback: check failure_families for hints
    if "retrieval_recall_failure" in failure_families:
        analysis.failure_type = "MISSING_MEMORY"
        analysis.failure_subcause = "below_threshold"
        analysis.details = "retrieval_recall_failure in failure_families."
        return analysis

    if "routing_layer_choice_failure" in failure_families:
        analysis.failure_type = "WRONG_MEMORY"
        analysis.failure_subcause = "wrong_layer"
        analysis.details = "routing_layer_choice_failure in failure_families."
        return analysis

    if "compact_task_state_failure" in failure_families:
        # Task checkpoint content issue — typically wrong/incomplete memory
        analysis.failure_type = "WRONG_MEMORY"
        analysis.failure_subcause = "wrong_type"
        analysis.details = "compact_task_state_failure in failure_families."
        return analysis

    # If policy failed but answer succeeded, classify based on what went wrong
    policy_ok = r.get("policy_success")
    answer_ok = r.get("answer_success")
    if answer_ok and not policy_ok:
        intent_match = r.get("intent_match")
        if intent_match is False:
            analysis.failure_type = "WRONG_MEMORY"
            analysis.failure_subcause = "wrong_layer"
            routing = r.get("routing_intent", "?")
            expected_intent = r.get("expected_intent", "?")
            analysis.details = (
                f"Intent misclassified: expected '{expected_intent}' "
                f"but routed as '{routing}'. Policy failed."
            )
            return analysis
        # Default: policy failure with correct answer
        analysis.failure_type = "WRONG_MEMORY"
        analysis.failure_subcause = "wrong_layer"
        analysis.details = "Policy check failed despite correct answer."
        return analysis

    # Non-value guard failure with should_memory_help=True
    if non_value_guard is False and should_help is True:
        # This is a quality gap, not abstention
        if failure_families:
            analysis.failure_type = "WRONG_MEMORY"
            analysis.failure_subcause = "wrong_type"
            analysis.details = (
                f"non_value_guard_success=false with should_memory_help=true. "
                f"Failure families: {failure_families}."
            )
            return analysis

    # Last resort
    analysis.failure_type = "WRONG_MEMORY"
    analysis.failure_subcause = "wrong_type"
    analysis.details = (
        f"Unclassified failure. failure_families={failure_families}"
    )
    return analysis


# ---------------------------------------------------------------------------
# Analyze a full results directory
# ---------------------------------------------------------------------------

@dataclass
class DirectoryAnalysis:
    path: str
    scenarios: list[ScenarioAnalysis] = field(default_factory=list)
    total: int = 0
    passed_count: int = 0
    failed_count: int = 0
    # Intent classification stats
    intent_correct: int = 0
    intent_total: int = 0
    intent_misclass: dict[str, int] = field(default_factory=lambda: Counter())


def _find_results_files(directory: str) -> list[Path]:
    """Recursively find all results.jsonl in directory."""
    root = Path(directory)
    if not root.exists():
        return []
    return sorted(root.rglob("results.jsonl"))


def analyze_directory(directory: str) -> DirectoryAnalysis:
    """Read all results.jsonl files under directory and classify failures."""
    result = DirectoryAnalysis(path=directory)
    files = _find_results_files(directory)

    if not files:
        print(f"  WARNING: No results.jsonl files found in {directory}",
              file=sys.stderr)
        return result

    for fpath in files:
        with open(fpath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                r = json.loads(line)
                result.total += 1

                passed = _scenario_passed(r)

                # Intent classification tracking
                expected_intent = r.get("expected_intent")
                routing_intent = r.get("routing_intent")
                if expected_intent and routing_intent:
                    result.intent_total += 1
                    if r.get("intent_match", expected_intent == routing_intent):
                        result.intent_correct += 1
                    else:
                        key = f"as_{routing_intent}"
                        result.intent_misclass[key] += 1

                if passed:
                    result.passed_count += 1
                    result.scenarios.append(ScenarioAnalysis(
                        scenario_id=r.get("scenario_id", "unknown"),
                        passed=True,
                        memories_retrieved=len(r.get("memory_backed_retrieval", [])),
                        memories_relevant=_count_relevant(r),
                        retrieval_rank=_find_expected_rank(r),
                    ))
                else:
                    result.failed_count += 1
                    analysis = classify_failure(r)
                    result.scenarios.append(analysis)

    return result


# ---------------------------------------------------------------------------
# Recall / precision computation
# ---------------------------------------------------------------------------

def _compute_recall_at_k(scenarios: list[ScenarioAnalysis], k: int) -> float | None:
    """Fraction of scenarios where expected memory is in top-k results."""
    eligible = [s for s in scenarios if s.retrieval_rank is not None]
    if not eligible:
        return None
    hit = sum(1 for s in eligible if s.retrieval_rank <= k)
    return hit / len(eligible)


def _compute_precision_at_k(scenarios: list[ScenarioAnalysis], k: int) -> float | None:
    """Average fraction of top-k results that are relevant."""
    eligible = [s for s in scenarios if s.memories_retrieved > 0]
    if not eligible:
        return None
    values = []
    for s in eligible:
        top_k_total = min(s.memories_retrieved, k)
        if top_k_total == 0:
            continue
        # Approximate: relevant / retrieved (we only have total counts)
        relevant_in_top = min(s.memories_relevant, top_k_total)
        values.append(relevant_in_top / top_k_total)
    return sum(values) / len(values) if values else None


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------

def format_report(analysis: DirectoryAnalysis) -> str:
    """Format the aggregate analysis report."""
    lines: list[str] = []
    lines.append(f"=== Failure Analysis: {analysis.path} ===")
    lines.append("")

    if analysis.total == 0:
        lines.append("No scenarios found.")
        return "\n".join(lines)

    pct_pass = analysis.passed_count / analysis.total * 100
    lines.append(f"Total scenarios: {analysis.total}")
    lines.append(f"Passed: {analysis.passed_count} ({pct_pass:.0f}%)")
    lines.append(f"Failed: {analysis.failed_count} ({100 - pct_pass:.0f}%)")
    lines.append("")

    # Failure type distribution
    type_counts: Counter = Counter()
    subcause_counts: Counter = Counter()
    for s in analysis.scenarios:
        if not s.passed and s.failure_type:
            type_counts[s.failure_type] += 1
            if s.failure_subcause:
                subcause_counts[s.failure_subcause] += 1

    lines.append("Failure type distribution:")
    for ft in FAILURE_TYPES:
        count = type_counts.get(ft, 0)
        if analysis.failed_count > 0 and count > 0:
            pct = count / analysis.failed_count * 100
            lines.append(f"  {ft:25s} {count} ({pct:.0f}%)")
        else:
            lines.append(f"  {ft:25s} {count}")
    lines.append("")

    if subcause_counts:
        lines.append("By subcause:")
        for sc, count in subcause_counts.most_common():
            lines.append(f"  {sc:25s} {count}")
        lines.append("")

    # Retrieval quality
    lines.append("Retrieval quality:")
    for k in [1, 3, 5]:
        recall = _compute_recall_at_k(analysis.scenarios, k)
        if recall is not None:
            lines.append(f"  recall@{k}: {recall:.2f}")
        else:
            lines.append(f"  recall@{k}: n/a")

    precision = _compute_precision_at_k(analysis.scenarios, 5)
    if precision is not None:
        lines.append(f"  precision@5: {precision:.2f}")
    else:
        lines.append(f"  precision@5: n/a")
    lines.append("")

    # Safety-adjusted score (wrong memory penalized more than missing)
    total_severity = 0.0
    max_severity = analysis.total * max(SEVERITY_WEIGHTS.values())
    wrong_memory_rate = 0.0
    harmful_count = 0
    for s in analysis.scenarios:
        if not s.passed and s.failure_type:
            subcause_weight = SUBCAUSE_SEVERITY.get(s.failure_subcause)
            type_weight = SEVERITY_WEIGHTS.get(s.failure_type, 1.0)
            weight = subcause_weight if subcause_weight is not None else type_weight
            total_severity += weight
            if s.failure_type in ("WRONG_MEMORY", "STALE_MEMORY", "CONTRADICTION"):
                harmful_count += 1

    if analysis.total > 0:
        safety_score = 1.0 - (total_severity / max_severity)
        wrong_memory_rate = harmful_count / analysis.total
    else:
        safety_score = 1.0
        wrong_memory_rate = 0.0

    lines.append("Safety metrics:")
    lines.append(f"  safety_score: {safety_score:.2f}  (1.0 = perfect, penalizes wrong > missing)")
    lines.append(f"  wrong_memory_rate: {wrong_memory_rate:.2f}  (fraction with harmful injection)")
    lines.append(f"  harmful_failures: {harmful_count}/{analysis.total}")
    lines.append(f"  safe_failures: {analysis.failed_count - harmful_count}/{analysis.total}  (missing/extraction = safe)")
    lines.append("")

    # Intent classification
    if analysis.intent_total > 0:
        pct_intent = analysis.intent_correct / analysis.intent_total * 100
        lines.append("Intent classification:")
        lines.append(
            f"  Correct: {analysis.intent_correct}/{analysis.intent_total} "
            f"({pct_intent:.0f}%)"
        )
        for key, count in sorted(analysis.intent_misclass.items()):
            label = key.replace("as_", "Misclassified as ")
            lines.append(f"  {label}: {count}")
        lines.append("")

    return "\n".join(lines)


def format_per_scenario(analysis: DirectoryAnalysis, failures_only: bool = True) -> str:
    """Format per-scenario JSONL output."""
    lines: list[str] = []
    for s in analysis.scenarios:
        if failures_only and s.passed:
            continue
        obj = {
            "scenario_id": s.scenario_id,
            "passed": s.passed,
        }
        if not s.passed:
            obj.update({
                "failure_type": s.failure_type,
                "failure_subcause": s.failure_subcause,
                "details": s.details,
                "retrieval_rank": s.retrieval_rank,
                "expected_in_top_k": s.expected_in_top_k,
                "memories_retrieved": s.memories_retrieved,
                "memories_relevant": s.memories_relevant,
                "wrong_memories_injected": s.wrong_memories_injected,
            })
        lines.append(json.dumps(obj))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Comparison mode
# ---------------------------------------------------------------------------

def format_comparison(analyses: list[DirectoryAnalysis]) -> str:
    """Show deltas between multiple runs."""
    if len(analyses) < 2:
        return ""

    lines: list[str] = []
    lines.append("=== Comparison ===")
    lines.append("")

    # Header
    # Use shortest unique suffixes for column names
    raw_names = [a.path.rstrip("/\\") for a in analyses]
    basenames = [os.path.basename(n) for n in raw_names]
    if len(set(basenames)) == len(basenames):
        names = basenames
    else:
        # Include parent components for disambiguation
        names = []
        for n in raw_names:
            parts = n.replace("\\", "/").split("/")
            # Walk from the end until we have a unique name
            for depth in range(2, len(parts) + 1):
                candidate = "/".join(parts[-depth:])
                others = [
                    "/".join(o.replace("\\", "/").split("/")[-depth:])
                    for o in raw_names if o != n
                ]
                if candidate not in others:
                    names.append(candidate)
                    break
            else:
                names.append(n)
    col_width = max(len(n) for n in names) + 2
    header = f"{'':30s}" + "".join(f"{n:>{col_width}s}" for n in names)
    lines.append(header)
    lines.append("-" * len(header))

    # Pass rate
    row = f"{'Pass rate':30s}"
    for a in analyses:
        if a.total > 0:
            pct = a.passed_count / a.total * 100
            row += f"{pct:>{col_width - 1}.0f}%"
        else:
            row += f"{'n/a':>{col_width}s}"
    lines.append(row)

    # Safety score
    row = f"{'Safety score':30s}"
    for a in analyses:
        total_sev = 0.0
        for s in a.scenarios:
            if not s.passed and s.failure_type:
                sw = SUBCAUSE_SEVERITY.get(s.failure_subcause)
                tw = SEVERITY_WEIGHTS.get(s.failure_type, 1.0)
                total_sev += sw if sw is not None else tw
        max_sev = a.total * max(SEVERITY_WEIGHTS.values()) if a.total > 0 else 1.0
        score = 1.0 - (total_sev / max_sev) if a.total > 0 else 1.0
        row += f"{score:>{col_width}.2f}"
    lines.append(row)

    # Wrong memory rate (harmful injection rate)
    row = f"{'Wrong memory rate':30s}"
    for a in analyses:
        harmful = sum(1 for s in a.scenarios if not s.passed and s.failure_type in ("WRONG_MEMORY", "STALE_MEMORY", "CONTRADICTION"))
        rate = harmful / a.total if a.total > 0 else 0.0
        row += f"{rate:>{col_width}.2f}"
    lines.append(row)

    # Failure type counts
    for ft in FAILURE_TYPES:
        row = f"{ft:30s}"
        for a in analyses:
            count = sum(
                1 for s in a.scenarios
                if not s.passed and s.failure_type == ft
            )
            row += f"{count:>{col_width}d}"
        lines.append(row)

    # Recall@1
    row = f"{'recall@1':30s}"
    for a in analyses:
        recall = _compute_recall_at_k(a.scenarios, 1)
        if recall is not None:
            row += f"{recall:>{col_width - 1}.2f} "
        else:
            row += f"{'n/a':>{col_width}s}"
    lines.append(row)

    # Intent accuracy
    row = f"{'Intent accuracy':30s}"
    for a in analyses:
        if a.intent_total > 0:
            pct = a.intent_correct / a.intent_total * 100
            row += f"{pct:>{col_width - 1}.0f}%"
        else:
            row += f"{'n/a':>{col_width}s}"
    lines.append(row)

    lines.append("")

    # Deltas (first run = baseline)
    baseline = analyses[0]
    if baseline.total > 0:
        lines.append(f"Deltas vs {names[0]}:")
        for i, a in enumerate(analyses[1:], 1):
            if a.total == 0:
                continue
            base_pct = baseline.passed_count / baseline.total * 100
            curr_pct = a.passed_count / a.total * 100
            delta = curr_pct - base_pct
            sign = "+" if delta >= 0 else ""
            lines.append(f"  {names[i]}: {sign}{delta:.1f}pp pass rate")

            # Per-type deltas
            for ft in FAILURE_TYPES:
                base_ct = sum(
                    1 for s in baseline.scenarios
                    if not s.passed and s.failure_type == ft
                )
                curr_ct = sum(
                    1 for s in a.scenarios
                    if not s.passed and s.failure_type == ft
                )
                d = curr_ct - base_ct
                if d != 0:
                    sign = "+" if d > 0 else ""
                    lines.append(f"    {ft}: {sign}{d}")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Analyze benchmark failures using 6-type taxonomy."
    )
    parser.add_argument(
        "directories",
        nargs="+",
        help="One or more benchmark output directories to analyze.",
    )
    parser.add_argument(
        "--jsonl",
        action="store_true",
        help="Also print per-scenario JSONL for failures.",
    )
    args = parser.parse_args()

    analyses: list[DirectoryAnalysis] = []
    for d in args.directories:
        a = analyze_directory(d)
        analyses.append(a)

    # Print individual reports
    for a in analyses:
        print(format_report(a))
        if args.jsonl:
            per_scenario = format_per_scenario(a)
            if per_scenario:
                print("--- Per-scenario failures ---")
                print(per_scenario)
                print()

    # Print comparison if multiple directories
    if len(analyses) > 1:
        print(format_comparison(analyses))


if __name__ == "__main__":
    main()
