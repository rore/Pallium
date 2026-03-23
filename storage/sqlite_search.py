from __future__ import annotations

import math
import re

from sqlalchemy import select

from core.filters import (
    matches_filters,
    target_visibility_and_container,
)
from core.models import QueryFilters
from core.visibility import VisibilityExclusion, is_visible
from storage.base import IndexSearchHit, IndexSearchResult
from storage.sqlite_schema import IndexEntryRecord


TOKEN_PATTERN = re.compile(r"[a-z0-9]+")

# Scale factor for converting float IDF sums to integer scores.
# Kept small so IDF scores remain in a similar range to raw token counts
# (1-10), preserving downstream routing weight balance.
_IDF_SCORE_SCALE = 1

class SQLiteSearchMixin:
    def search_index_entries(
        self,
        tokens: list[str],
        limit: int,
        filters: QueryFilters | None = None,
        *,
        query_container_ref: str | None = None,
        include_visibility_trace: bool = False,
    ) -> IndexSearchResult:
        with self._session_factory() as session:
            records = session.scalars(
                select(IndexEntryRecord).where(IndexEntryRecord.index_type == "lexical")
            ).all()
        hits: list[IndexSearchHit] = []
        exclusion_counts: dict[str, int] = {}
        unique_tokens = set(tokens)
        total_hits_before_visibility = 0
        total_hits_after_visibility = 0

        # Pre-filter records and tokenize; build document frequency for query tokens.
        filtered: list[tuple[object, set[str]]] = []
        doc_freq: dict[str, int] = {}
        for record in records:
            if not matches_filters(
                self.get_memory_object, self.get_source_item,
                self.get_evidence_for_memory_object,
                record.target_kind, record.target_id, filters,
            ):
                continue
            text_tokens = set(TOKEN_PATTERN.findall(record.text_view.lower()))
            filtered.append((record, text_tokens))
            for qt in unique_tokens:
                if qt in text_tokens:
                    doc_freq[qt] = doc_freq.get(qt, 0) + 1

        corpus_size = len(filtered)
        # Use effective_corpus_size >= 3 so the IDF formula produces meaningful
        # discrimination even with very small corpora.  With corpus=1, every
        # term has df=1 and IDF≈0 — mathematically correct but practically
        # useless.  A floor of 3 gives single-term matches score≈1 and
        # two-term matches score≈2, which is exactly the relevance floor.
        effective_corpus = max(corpus_size, 3)

        for record, text_tokens in filtered:
            matched_tokens = tuple(sorted(unique_tokens.intersection(text_tokens)))
            if not matched_tokens:
                continue
            idf_sum = sum(
                math.log(1.0 + (effective_corpus - doc_freq.get(t, 0) + 0.5) / (doc_freq.get(t, 0) + 0.5))
                for t in matched_tokens
            )
            score = max(round(idf_sum * _IDF_SCORE_SCALE), 1)
            if score <= 0:
                continue
            total_hits_before_visibility += 1
            candidate_visibility, candidate_container_ref, candidate_actor_ref = target_visibility_and_container(
                self.get_source_item, self.get_memory_object,
                record.target_kind, record.target_id,
            )
            if query_container_ref is not None and not is_visible(candidate_visibility, candidate_container_ref, query_container_ref, candidate_actor_ref):
                if include_visibility_trace:
                    reason = (
                        "candidate_visibility_missing"
                        if candidate_visibility is None
                        else "query_container_visibility_excludes_candidate"
                    )
                    exclusion_counts[reason] = exclusion_counts.get(reason, 0) + 1
                continue
            total_hits_after_visibility += 1
            hits.append(
                IndexSearchHit(
                    target_kind=record.target_kind,
                    target_id=record.target_id,
                    index_entry_id=record.id,
                    index_type=record.index_type,
                    text_view_name=record.text_view_name or "default",
                    score=score,
                    matched_tokens=matched_tokens,
                    provider_name=record.provider_name,
                    provider_version=record.provider_version,
                )
            )
        hits.sort(key=lambda item: (item.score, 1 if item.target_kind == "memory_object" else 0), reverse=True)
        exclusions = tuple(
            VisibilityExclusion(reason=reason, count=count)
            for reason, count in sorted(exclusion_counts.items())
        )
        return IndexSearchResult(
            hits=hits[:limit],
            visibility_exclusions=exclusions,
            total_hits_before_visibility=total_hits_before_visibility,
            total_hits_after_visibility=total_hits_after_visibility,
        )

