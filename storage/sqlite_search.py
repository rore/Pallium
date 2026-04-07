from __future__ import annotations

from sqlalchemy import text as sa_text

from core.filters import (
    matches_filters,
    target_visibility_and_container,
)
from core.models import QueryFilters
from core.text import tokenize_text
from core.visibility import VisibilityExclusion, is_visible
from storage.base import IndexSearchHit, IndexSearchResult

# Minimum BM25 relevance score (after negation, so higher = better).
# Candidates below this floor are treated as noise.
# Calibrate from eval corpus BM25 score distribution.
LEXICAL_BM25_FLOOR = 0.0  # permissive default; tighten after eval calibration


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
        if not tokens:
            return IndexSearchResult(hits=[])

        # Build safe MATCH expression with OR semantics.
        # Quote each token to prevent FTS5 syntax injection (AND, OR, NOT, NEAR, *).
        # TOKEN_PATTERN only produces word characters and CJK ideographs, so tokens
        # cannot contain double quotes. The escape is defensive insurance.
        quoted = ['"' + token.replace('"', '""') + '"' for token in tokens]
        match_expr = " OR ".join(quoted)

        with self._session_factory() as session:
            rows = session.execute(
                sa_text(
                    "SELECT index_entry_id, target_kind, target_id, text_view_name, "
                    "text_view, bm25(lexical_fts) AS score "
                    "FROM lexical_fts "
                    "WHERE lexical_fts MATCH :match_expr "
                    "ORDER BY score "
                    "LIMIT :limit"
                ),
                {
                    "match_expr": match_expr,
                    "limit": limit,
                },
            ).fetchall()

        hits: list[IndexSearchHit] = []
        exclusion_counts: dict[str, int] = {}
        unique_tokens = set(tokens)
        total_hits_before_visibility = 0
        total_hits_after_visibility = 0

        for row in rows:
            # Negate BM25 score: FTS5 returns negative (lower = better),
            # we want higher = better to match existing codebase convention.
            score = -row.score

            # Post-FTS5 score floor: skip weak matches.
            if score < LEXICAL_BM25_FLOOR:
                continue

            # Lifecycle and field filtering.
            if not matches_filters(
                self.get_memory_object,
                self.get_source_item,
                self.get_evidence_for_memory_object,
                row.target_kind,
                row.target_id,
                filters,
            ):
                continue

            # Reconstruct matched_tokens (approximate, trace/debug only).
            text_tokens = set(tokenize_text(row.text_view))
            matched_tokens = tuple(sorted(unique_tokens & text_tokens))

            total_hits_before_visibility += 1

            # Visibility filtering.
            candidate_visibility, candidate_container_ref, candidate_actor_ref = (
                target_visibility_and_container(
                    self.get_source_item,
                    self.get_memory_object,
                    row.target_kind,
                    row.target_id,
                )
            )
            if query_container_ref is not None and not is_visible(
                candidate_visibility,
                candidate_container_ref,
                query_container_ref,
                candidate_actor_ref,
            ):
                if include_visibility_trace:
                    reason = (
                        "candidate_visibility_missing"
                        if candidate_visibility is None
                        else "query_visibility_excludes_candidate"
                    )
                    exclusion_counts[reason] = exclusion_counts.get(reason, 0) + 1
                continue

            total_hits_after_visibility += 1
            hits.append(
                IndexSearchHit(
                    target_kind=row.target_kind,
                    target_id=row.target_id,
                    index_entry_id=row.index_entry_id,
                    index_type="lexical",
                    text_view_name=row.text_view_name or "default",
                    score=score,
                    matched_tokens=matched_tokens,
                )
            )

        # Preserve memory_object tie-breaking at equal scores.
        hits.sort(
            key=lambda item: (
                item.score,
                1 if item.target_kind == "memory_object" else 0,
            ),
            reverse=True,
        )
        exclusions = tuple(
            VisibilityExclusion(reason=reason, count=count)
            for reason, count in sorted(exclusion_counts.items())
        )
        return IndexSearchResult(
            hits=hits,
            visibility_exclusions=exclusions,
            total_hits_before_visibility=total_hits_before_visibility,
            total_hits_after_visibility=total_hits_after_visibility,
        )
