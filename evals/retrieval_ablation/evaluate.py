"""Scoring logic for retrieval ablation eval.

Matches feedback ratings to candidate memories and computes precision/coverage
for each variant strategy.
"""
from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any


@dataclass
class FeedbackEntry:
    memory_object_id: str
    rating: str  # "relevant" | "not_relevant"
    query_context: str
    memory_type: str


@dataclass
class QueryVariantResult:
    """Result of applying a variant strategy to one query."""
    query_id: int
    query_text: str
    injected_ids: set[str]


@dataclass
class VariantMetrics:
    """Aggregate metrics for a variant across all queries."""
    name: str
    total_queries: int = 0
    total_injected: int = 0
    rated_relevant: int = 0
    rated_not_relevant: int = 0
    rated_unknown: int = 0
    # Coverage: how many memories with "relevant" feedback does this variant surface
    relevant_memories_surfaced: int = 0
    total_relevant_memories: int = 0
    # Per memory_type breakdown
    type_relevant: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    type_not_relevant: dict[str, int] = field(default_factory=lambda: defaultdict(int))

    @property
    def precision(self) -> float:
        """Precision among rated memories only."""
        denom = self.rated_relevant + self.rated_not_relevant
        return self.rated_relevant / denom if denom else 0.0

    @property
    def coverage(self) -> float:
        """Fraction of all relevant-rated memories surfaced by this variant."""
        return (self.relevant_memories_surfaced / self.total_relevant_memories
                if self.total_relevant_memories else 0.0)

    @property
    def avg_injected(self) -> float:
        return self.total_injected / self.total_queries if self.total_queries else 0.0

    @property
    def rated_count(self) -> int:
        return self.rated_relevant + self.rated_not_relevant


def build_feedback_index(
    feedback_rows: list[dict[str, Any]],
) -> dict[str, list[FeedbackEntry]]:
    """Build memory_object_id -> list of feedback entries."""
    index: dict[str, list[FeedbackEntry]] = defaultdict(list)
    for row in feedback_rows:
        entry = FeedbackEntry(
            memory_object_id=row["memory_object_id"],
            rating=row["rating"],
            query_context=row.get("query_context", ""),
            memory_type=row.get("memory_type", "unknown"),
        )
        index[entry.memory_object_id].append(entry)
    return index


def majority_rating(entries: list[FeedbackEntry]) -> str | None:
    """Return majority rating for a memory, or None if no feedback."""
    if not entries:
        return None
    relevant = sum(1 for e in entries if e.rating == "relevant")
    not_relevant = sum(1 for e in entries if e.rating == "not_relevant")
    if relevant > not_relevant:
        return "relevant"
    elif not_relevant > relevant:
        return "not_relevant"
    # Tie: default to not_relevant (conservative)
    return "not_relevant"


def get_candidate_type(
    memory_id: str, candidates: list[dict[str, Any]]
) -> str:
    """Look up memory_type from candidate list."""
    for c in candidates:
        if c.get("memory_object_id") == memory_id:
            return c.get("memory_type", "unknown")
    return "unknown"


def evaluate_variant(
    variant_name: str,
    query_results: list[QueryVariantResult],
    feedback_index: dict[str, list[FeedbackEntry]],
    all_candidates_by_query: dict[int, list[dict[str, Any]]],
) -> VariantMetrics:
    """Score a variant across all queries using feedback data."""
    # All memory_object_ids that have "relevant" feedback anywhere
    all_relevant_ids: set[str] = set()
    for mem_id, entries in feedback_index.items():
        if majority_rating(entries) == "relevant":
            all_relevant_ids.add(mem_id)

    metrics = VariantMetrics(
        name=variant_name,
        total_relevant_memories=len(all_relevant_ids),
    )

    surfaced_relevant: set[str] = set()

    for qr in query_results:
        metrics.total_queries += 1
        metrics.total_injected += len(qr.injected_ids)
        candidates = all_candidates_by_query.get(qr.query_id, [])

        for mem_id in qr.injected_ids:
            entries = feedback_index.get(mem_id, [])
            rating = majority_rating(entries)
            mem_type = get_candidate_type(mem_id, candidates)

            if rating == "relevant":
                metrics.rated_relevant += 1
                metrics.type_relevant[mem_type] += 1
                surfaced_relevant.add(mem_id)
            elif rating == "not_relevant":
                metrics.rated_not_relevant += 1
                metrics.type_not_relevant[mem_type] += 1
            else:
                metrics.rated_unknown += 1

    metrics.relevant_memories_surfaced = len(surfaced_relevant)
    return metrics
