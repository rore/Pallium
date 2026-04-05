"""Vector retrieval mock-backed diagnostic harness.

Deterministic stub harness that verifies provider plumbing and scenario
structure for the vector retrieval recall gap.  Uses pre-computed mock
embeddings and a mock VectorIndex — does NOT exercise the actual
fastembed/usearch pipeline.

This harness proves:
- The retrieval provider correctly surfaces vector candidates
- Scenarios capture the right abstract-paraphrase failure classes
- Lexical retrieval produces zero results for zero-overlap queries

It does NOT prove:
- That real fastembed embeddings have sufficient quality to close the gap
- That the usearch index produces correct ANN results on real vectors

Live embedding quality testing requires a separate integration path with
fastembed and usearch installed.

Scenarios are loaded from ``evals/vector_retrieval/scenarios.json``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from core.models import (
    IndexEntry,
    MemoryObject,
    QueryFilters,
    Relation,
    SourceItem,
)
from providers.embedding.base import EmbeddingProvider
from retrieval.base import RetrievalQueryResult
from retrieval.lexical import LexicalRetrievalProvider
from retrieval.vector import VectorRetrievalProvider
from storage.base import StorageProvider
from storage.sqlite import SQLiteStorageProvider


DEFAULT_SCENARIO_FILE = Path("evals/vector_retrieval/scenarios.json")
DEFAULT_MIN_SIMILARITY = 0.3
MOCK_DIMENSIONS = 4


# ---------------------------------------------------------------------------
# Mock embedding + vector index (no fastembed / usearch dependency)
# ---------------------------------------------------------------------------


class MockEmbeddingProvider(EmbeddingProvider):
    """Returns a fixed vector for every input text.

    Different vectors can be registered per text to simulate real embedding
    proximity. Unregistered texts get the ``default_vector``.
    """

    def __init__(
        self,
        default_vector: list[float] | None = None,
        text_vectors: dict[str, list[float]] | None = None,
        dims: int = MOCK_DIMENSIONS,
    ) -> None:
        self._default_vector = default_vector or [0.1, 0.2, 0.3, 0.4]
        self._text_vectors = text_vectors or {}
        self._dims = dims

    def embed(self, texts: list[str], **kwargs: object) -> list[list[float]]:
        return [
            self._text_vectors.get(t, self._default_vector)[:]
            for t in texts
        ]

    def dimensions(self) -> int:
        return self._dims

    def model_name(self) -> str:
        return "mock-embedding-model"


class MockVectorIndex:
    """In-memory mock replacing usearch-backed VectorIndex.

    Pre-loaded with ``(entry_id, similarity)`` pairs that the ``search``
    method returns for *any* query vector.  This lets us deterministically
    control what the vector path finds.
    """

    def __init__(self, hits: list[tuple[str, float]] | None = None) -> None:
        self._hits = hits or []
        self._removed: list[str] = []
        self._saved = False

    def search(self, query_vector: list[float], k: int) -> list[tuple[str, float]]:
        return self._hits[:k]

    def add(self, entry_id: str, vector: list[float]) -> None:
        pass  # no-op for stub

    def remove(self, entry_id: str) -> None:
        self._removed.append(entry_id)

    def save(self) -> None:
        self._saved = True


# ---------------------------------------------------------------------------
# Per-scenario result
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ScenarioResult:
    scenario_id: str
    scenario_family: str
    expected_memory_types: list[str]
    lexical_found: bool
    vector_found: bool
    vector_cosine_similarity: float | None
    vector_above_threshold: bool
    expected_gap_confirmed: bool


# ---------------------------------------------------------------------------
# Aggregate summary
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BenchmarkSummary:
    total_scenarios: int
    vector_recall_rate: float
    lexical_recall_rate: float
    gap_confirmation_rate: float
    threshold_pass_rate: float
    scenario_results: list[ScenarioResult]


# ---------------------------------------------------------------------------
# Scenario helpers
# ---------------------------------------------------------------------------


def load_scenarios(scenario_file: Path | None = None) -> list[dict[str, Any]]:
    path = scenario_file or DEFAULT_SCENARIO_FILE
    return json.loads(path.read_text(encoding="utf-8"))


def _parse_occurred_at(raw: str | None) -> datetime | None:
    if raw is None:
        return None
    return datetime.fromisoformat(raw.replace("Z", "+00:00"))


def _parse_visibility(raw: dict[str, Any] | str | None) -> str:
    if raw is None:
        return "public"
    if isinstance(raw, str):
        return raw
    # Legacy dict format: {"kind": "public", "id": None}
    kind = raw.get("kind", "public")
    if kind == "user":
        return "private"
    return kind


# ---------------------------------------------------------------------------
# Core runner
# ---------------------------------------------------------------------------


def _setup_storage_for_scenario(
    storage: StorageProvider,
    scenario: dict[str, Any],
) -> tuple[list[str], list[str]]:
    """Ingest prior_events and memory_objects into storage.

    Returns (source_item_ids, memory_object_ids) for index entry creation.
    """
    source_item_ids: list[str] = []
    for event in scenario["prior_events"]:
        container_vis = _parse_visibility(
            event.get("visibility")
        )
        si = SourceItem(
            source_type=event["source_type"],
            source_id=event["source_id"],
            content_type=event["content_type"],
            content=event["content"],
            metadata=event.get("metadata"),
            occurred_at=_parse_occurred_at(event.get("occurred_at")),
            actor_ref=event.get("actor_ref"),
            role=event.get("role"),
            container_ref=event.get("container_ref"),
            thread_ref=event.get("thread_ref"),
            source_ref=event.get("source_ref"),
            artifact_kind=event.get("artifact_kind"),
            visibility=container_vis,
        )
        storage.create_source_item(si)
        source_item_ids.append(si.id)

    memory_object_ids: list[str] = []
    for mo_spec in scenario.get("memory_objects", []):
        mo = MemoryObject(
            id=mo_spec["memory_id"],
            type=mo_spec["type"],
            schema_id="vector_retrieval_benchmark",
            schema_version="1",
            payload=mo_spec["payload"],
            visibility="public",
        )
        storage.create_memory_object(mo)
        memory_object_ids.append(mo.id)

        # Link evidence via supported_by relation to the first source item
        if source_item_ids:
            relation = Relation(
                from_kind="memory_object",
                from_id=mo.id,
                relation_type="supported_by",
                to_kind="source_item",
                to_id=source_item_ids[0],
            )
            storage.create_relation(relation)

        # Create lexical index entries from text_views
        for text_view in mo_spec.get("text_views", []):
            idx_entry = IndexEntry(
                target_kind="memory_object",
                target_id=mo.id,
                index_type="lexical",
                text_view=text_view,
                text_view_name="summary",
                provider_name="lexical",
                provider_version="v1",
            )
            storage.create_index_entry(idx_entry)

    return source_item_ids, memory_object_ids


def _build_vector_index_for_scenario(
    storage: StorageProvider,
    scenario: dict[str, Any],
    memory_object_ids: list[str],
    mock_similarity: float = 0.85,
) -> tuple[MockVectorIndex, dict[str, str]]:
    """Build a MockVectorIndex with pre-computed hits for memory objects.

    Returns (mock_index, {entry_id: memory_object_id}).
    """
    hits: list[tuple[str, float]] = []
    entry_map: dict[str, str] = {}

    for i, mo_spec in enumerate(scenario.get("memory_objects", [])):
        mo_id = mo_spec["memory_id"]
        entry_id = f"vidx-{mo_id}"

        # Create a vector index entry in storage so VectorRetrievalProvider
        # can resolve entry_id -> IndexEntry
        for text_view in mo_spec.get("text_views", []):
            idx_entry = IndexEntry(
                id=entry_id,
                target_kind="memory_object",
                target_id=mo_id,
                index_type="vector",
                text_view=text_view,
                text_view_name="summary",
                provider_name="mock-embedding-model",
                provider_version="v1",
            )
            storage.create_index_entry(idx_entry)
            break  # one entry per memory object for the mock

        hits.append((entry_id, mock_similarity))
        entry_map[entry_id] = mo_id

    return MockVectorIndex(hits=hits), entry_map


def _check_lexical_recall(
    result: RetrievalQueryResult,
    expected_types: list[str],
) -> bool:
    """Check if lexical retrieval found any result matching expected_memory_types."""
    for item in result.results:
        if item.result_kind == "memory_hit" and item.type in expected_types:
            return True
    return False


def _check_vector_recall(
    result: RetrievalQueryResult,
    expected_types: list[str],
) -> tuple[bool, float | None]:
    """Check vector retrieval results. Returns (found, best_similarity)."""
    best_similarity: float | None = None
    found = False

    for item in result.results:
        if item.result_kind == "memory_hit" and item.type in expected_types:
            found = True
            # Extract cosine_similarity from trace if available
            if result.trace and result.trace.stages:
                for stage in result.trace.stages:
                    for hit in stage.selected_hits:
                        if hit.target_id == item.memory_object_id and hit.cosine_similarity is not None:
                            if best_similarity is None or hit.cosine_similarity > best_similarity:
                                best_similarity = hit.cosine_similarity

    return found, best_similarity


def run_scenario(
    scenario: dict[str, Any],
    *,
    min_similarity: float = DEFAULT_MIN_SIMILARITY,
    mock_vector_similarity: float = 0.85,
) -> ScenarioResult:
    """Run a single benchmark scenario with a fresh in-memory DB.

    Uses SQLiteStorageProvider with an in-memory database, real
    LexicalRetrievalProvider, and mock-backed VectorRetrievalProvider.
    """
    storage = SQLiteStorageProvider("sqlite:///:memory:")

    # 1. Set up storage: ingest events, create memory objects + index entries
    source_ids, memory_ids = _setup_storage_for_scenario(storage, scenario)

    # 2. Build mock vector index
    mock_index, entry_map = _build_vector_index_for_scenario(
        storage, scenario, memory_ids, mock_similarity=mock_vector_similarity,
    )

    # 3. Build providers
    mock_embedding = MockEmbeddingProvider()
    lexical_provider = LexicalRetrievalProvider(storage)
    vector_provider = VectorRetrievalProvider(
        storage, mock_index, mock_embedding, min_similarity=min_similarity,
    )

    # 4. Run queries
    query = scenario["current_query"]
    query_text = query["text"]
    query_limit = query.get("limit", 4)
    container_vis = _parse_visibility(query.get("visibility"))
    container_ref = query.get("container_ref")
    filters = QueryFilters(container_ref=container_ref) if container_ref else None

    lexical_result = lexical_provider.query(
        query_text,
        query_limit,
        filters=filters,
        visibility=container_vis,
        include_trace=True,
    )
    vector_result = vector_provider.query(
        query_text,
        query_limit,
        filters=filters,
        visibility=container_vis,
        include_trace=True,
    )

    # 5. Evaluate results
    expected_types = scenario["expected_memory_types"]
    lexical_found = _check_lexical_recall(lexical_result, expected_types)
    vector_found, best_sim = _check_vector_recall(vector_result, expected_types)
    vector_above_threshold = best_sim is not None and best_sim >= min_similarity
    expected_gap_confirmed = (not lexical_found) and vector_found

    return ScenarioResult(
        scenario_id=scenario["scenario_id"],
        scenario_family=scenario["scenario_family"],
        expected_memory_types=expected_types,
        lexical_found=lexical_found,
        vector_found=vector_found,
        vector_cosine_similarity=best_sim,
        vector_above_threshold=vector_above_threshold,
        expected_gap_confirmed=expected_gap_confirmed,
    )


def run_benchmark(
    scenario_file: Path | None = None,
    *,
    min_similarity: float = DEFAULT_MIN_SIMILARITY,
    mock_vector_similarity: float = 0.85,
) -> BenchmarkSummary:
    """Run all scenarios and compute aggregate metrics."""
    scenarios = load_scenarios(scenario_file)
    results: list[ScenarioResult] = []

    for scenario in scenarios:
        result = run_scenario(
            scenario,
            min_similarity=min_similarity,
            mock_vector_similarity=mock_vector_similarity,
        )
        results.append(result)

    total = len(results)
    if total == 0:
        return BenchmarkSummary(
            total_scenarios=0,
            vector_recall_rate=0.0,
            lexical_recall_rate=0.0,
            gap_confirmation_rate=0.0,
            threshold_pass_rate=0.0,
            scenario_results=[],
        )

    vector_recall = sum(1 for r in results if r.vector_found) / total
    lexical_recall = sum(1 for r in results if r.lexical_found) / total
    gap_confirmed = sum(1 for r in results if r.expected_gap_confirmed) / total
    threshold_pass = sum(1 for r in results if r.vector_found and r.vector_above_threshold) / total

    return BenchmarkSummary(
        total_scenarios=total,
        vector_recall_rate=vector_recall,
        lexical_recall_rate=lexical_recall,
        gap_confirmation_rate=gap_confirmed,
        threshold_pass_rate=threshold_pass,
        scenario_results=results,
    )


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Run the vector retrieval gap benchmark."
    )
    parser.add_argument(
        "--scenario-file",
        type=Path,
        default=DEFAULT_SCENARIO_FILE,
    )
    parser.add_argument(
        "--min-similarity",
        type=float,
        default=DEFAULT_MIN_SIMILARITY,
    )
    args = parser.parse_args()

    summary = run_benchmark(
        scenario_file=args.scenario_file,
        min_similarity=args.min_similarity,
    )

    print(f"Total scenarios:        {summary.total_scenarios}")
    print(f"Vector recall rate:     {summary.vector_recall_rate:.1%}")
    print(f"Lexical recall rate:    {summary.lexical_recall_rate:.1%}")
    print(f"Gap confirmation rate:  {summary.gap_confirmation_rate:.1%}")
    print(f"Threshold pass rate:    {summary.threshold_pass_rate:.1%}")
    print()

    for r in summary.scenario_results:
        gap_mark = "CONFIRMED" if r.expected_gap_confirmed else "NOT CONFIRMED"
        print(
            f"  {r.scenario_id}: "
            f"lexical={'HIT' if r.lexical_found else 'MISS'} "
            f"vector={'HIT' if r.vector_found else 'MISS'} "
            f"sim={r.vector_cosine_similarity} "
            f"gap={gap_mark}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
