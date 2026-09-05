from __future__ import annotations

from sqlalchemy import text as sa_text

from core.filters import matches_filters, target_visibility_and_container
from core.models import QueryFilters
from core.text import tokenize_text
from core.visibility import VisibilityExclusion, is_visible
from core.work_ref import _normalize_work_ref
from storage.base import IndexSearchHit, IndexSearchResult

LEXICAL_BM25_FLOOR = 0.0


class SQLiteSearchMixin:
    def search_index_entries(
        self,
        tokens: list[str],
        limit: int,
        filters: QueryFilters | None = None,
        *,
        query_container_ref: str | None = None,
        query_visibility: str | None = None,
        query_actor_ref: str | None = None,
        include_visibility_trace: bool = False,
        target_kind: str | None = None,
    ) -> IndexSearchResult:
        exact_source_work_query = bool(
            filters and filters.work_refs and target_kind == "source_item"
        )
        structural_work_ref_query = exact_source_work_query and not tokens
        if not tokens and not structural_work_ref_query:
            return IndexSearchResult(hits=[])

        quoted = ['"' + token.replace('"', '""') + '"' for token in tokens]
        match_expr = " OR ".join(quoted)
        work_ref_params: dict[str, str] = {}
        work_ref_clause = ""
        if exact_source_work_query:
            names = []
            for i, ref in enumerate(filters.work_refs):
                name = f"work_ref_{i}"
                names.append(f":{name}")
                work_ref_params[name] = ref
            work_ref_clause = (
                "AND target_kind = 'source_item' AND EXISTS ("
                "SELECT 1 FROM source_items si WHERE si.id = target_id "
                "AND json_valid(si.metadata_json) AND EXISTS ("
                "SELECT 1 FROM json_each(si.metadata_json, '$.pallium_work_refs') "
                "WHERE pallium_normalize_work_ref(json_each.value) IN (" + ", ".join(names) + "))) "
            )

        select_fts = (
            "SELECT index_entry_id, target_kind, target_id, text_view_name, "
            "text_view, bm25(lexical_fts) AS score FROM lexical_fts "
            "WHERE lexical_fts MATCH :match_expr "
        )
        hits: list[IndexSearchHit] = []
        exclusion_counts: dict[str, int] = {}
        unique_tokens = set(tokens)
        total_hits_before_visibility = 0
        total_hits_after_visibility = 0
        page_size = max(limit, 1)
        fts_order = (
            "ORDER BY score, index_entry_id"
            if exact_source_work_query
            else "ORDER BY score"
        )
        exact_rows = None
        if exact_source_work_query:
            def exact_pages():
                with self._session_factory() as session:
                    session.connection().connection.create_function(
                        "pallium_normalize_work_ref",
                        1,
                        lambda value: (
                            _normalize_work_ref(value)
                            if isinstance(value, str)
                            else None
                        ),
                    )
                    if structural_work_ref_query:
                        result = session.execute(
                            sa_text(
                                "SELECT si.id AS index_entry_id, 'source_item' AS target_kind, "
                                "si.id AS target_id, 'structural_work_ref' AS text_view_name, "
                                "'' AS text_view, 0.0 AS score FROM source_items si "
                                "WHERE json_valid(si.metadata_json) AND EXISTS ("
                                "SELECT 1 FROM json_each(si.metadata_json, '$.pallium_work_refs') "
                                "WHERE pallium_normalize_work_ref(json_each.value) IN (" + ", ".join(f":work_ref_{i}" for i, _ in enumerate(filters.work_refs)) + ")) "
                                "ORDER BY COALESCE(si.occurred_at, si.created_at) DESC, si.id DESC "
                                "LIMIT :limit OFFSET :offset"
                            ),
                            {"limit": -1, "offset": 0, **work_ref_params},
                        )
                    elif target_kind is not None:
                        result = session.execute(
                            sa_text(select_fts + work_ref_clause + "AND target_kind = :target_kind " + fts_order + " LIMIT :limit OFFSET :offset"),
                            {"match_expr": match_expr, "limit": -1, "offset": 0, "target_kind": target_kind, **work_ref_params},
                        )
                    else:
                        result = session.execute(
                            sa_text(select_fts + work_ref_clause + fts_order + " LIMIT :limit OFFSET :offset"),
                            {"match_expr": match_expr, "limit": -1, "offset": 0, **work_ref_params},
                        )
                    while rows := result.fetchmany(page_size):
                        yield rows

            exact_rows = exact_pages()
        seen: set[tuple[str, str]] = set()

        # Work-ref candidates are refilled after lifecycle/visibility gates.
        # The exact JSON membership predicate remains inside SQL before LIMIT.
        while len(hits) < limit:
            if exact_rows is not None:
                rows = next(exact_rows, None)
            else:
                with self._session_factory() as session:
                    if target_kind is not None:
                        rows = session.execute(
                            sa_text(select_fts + "AND target_kind = :target_kind " + fts_order + " LIMIT :limit OFFSET 0"),
                            {"match_expr": match_expr, "limit": page_size, "target_kind": target_kind},
                        ).fetchall()
                    else:
                        rows = session.execute(
                            sa_text(select_fts + fts_order + " LIMIT :limit OFFSET 0"),
                            {"match_expr": match_expr, "limit": page_size},
                        ).fetchall()
            if not rows:
                break

            prefetched = self.get_source_items(
                [row.target_id for row in rows if row.target_kind == "source_item"]
            )

            def get_source_item(source_item_id: str):
                return prefetched.get(source_item_id) or self.get_source_item(source_item_id)

            for row in rows:
                key = (row.target_kind, row.target_id)
                if exact_source_work_query and key in seen:
                    continue
                if exact_source_work_query:
                    seen.add(key)
                score = -row.score
                if not structural_work_ref_query and score < LEXICAL_BM25_FLOOR:
                    continue
                if not matches_filters(
                    self.get_memory_object,
                    get_source_item,
                    self.get_evidence_for_memory_object,
                    row.target_kind,
                    row.target_id,
                    filters,
                ):
                    continue
                text_tokens = set(tokenize_text(row.text_view))
                matched_tokens = tuple(sorted(unique_tokens & text_tokens))
                total_hits_before_visibility += 1
                candidate_visibility, candidate_container_ref, candidate_actor_ref = (
                    target_visibility_and_container(
                        get_source_item,
                        self.get_memory_object,
                        row.target_kind,
                        row.target_id,
                    )
                )
                if not is_visible(
                    candidate_visibility,
                    candidate_container_ref,
                    query_container_ref,
                    candidate_actor_ref,
                    query_visibility=query_visibility,
                    query_actor_ref=query_actor_ref,
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
                if len(hits) >= limit:
                    break

            if not exact_source_work_query or len(rows) < page_size:
                break

        hits.sort(
            key=lambda item: (item.score, 1 if item.target_kind == "memory_object" else 0),
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
