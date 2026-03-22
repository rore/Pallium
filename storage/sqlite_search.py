from __future__ import annotations

import re

from sqlalchemy import select

from core.models import EvidenceReference, QueryFilters, SourceItem
from core.visibility import VisibilityExclusion, is_visible
from storage.base import IndexSearchHit, IndexSearchResult
from storage.sqlite_schema import IndexEntryRecord


TOKEN_PATTERN = re.compile(r"[a-z0-9]+")


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
        for record in records:
            if not self._matches_filters(record.target_kind, record.target_id, filters):
                continue
            text_tokens = set(TOKEN_PATTERN.findall(record.text_view.lower()))
            matched_tokens = tuple(sorted(unique_tokens.intersection(text_tokens)))
            score = len(matched_tokens)
            if score == 0:
                continue
            total_hits_before_visibility += 1
            candidate_visibility, candidate_container_ref = self._target_visibility(record.target_kind, record.target_id)
            if query_container_ref is not None and not is_visible(candidate_visibility, candidate_container_ref, query_container_ref):
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

    def _matches_filters(self, target_kind: str, target_id: str, filters: QueryFilters | None) -> bool:
        if target_kind == "memory_object":
            memory_object = self.get_memory_object(target_id)
            if memory_object.lifecycle != "active":
                return False
        if filters is None:
            return True
        if target_kind == "source_item":
            return self._source_item_matches_filters(self.get_source_item(target_id), filters)
        if target_kind == "memory_object":
            evidence = self.get_evidence_for_memory_object(target_id)
            return any(self._evidence_matches_filters(item, filters) for item in evidence)
        return True

    def _target_visibility(self, target_kind: str, target_id: str) -> tuple[str | None, str | None]:
        if target_kind == "source_item":
            item = self.get_source_item(target_id)
            return item.container_visibility, item.container_ref
        if target_kind == "memory_object":
            obj = self.get_memory_object(target_id)
            container_ref = obj.container_ref
            if container_ref is None and obj.envelope is not None:
                container_ref = obj.envelope.scope.container_ref
            return obj.container_visibility, container_ref
        return None, None

    def _source_item_matches_filters(self, source_item: SourceItem, filters: QueryFilters) -> bool:
        if filters.source_type is not None and source_item.source_type != filters.source_type:
            return False
        if filters.role is not None and source_item.role != filters.role:
            return False
        if filters.artifact_kind is not None and source_item.artifact_kind != filters.artifact_kind:
            return False
        if filters.container_ref is not None and source_item.container_visibility != "public" and source_item.container_ref != filters.container_ref:
            return False
        if filters.thread_ref is not None and source_item.thread_ref != filters.thread_ref:
            return False
        return True

    def _evidence_matches_filters(self, evidence: EvidenceReference, filters: QueryFilters) -> bool:
        if filters.source_type is not None and evidence.source_type != filters.source_type:
            return False
        if filters.role is not None and evidence.role != filters.role:
            return False
        if filters.artifact_kind is not None and evidence.artifact_kind != filters.artifact_kind:
            return False
        if filters.container_ref is not None and evidence.container_visibility != "public" and evidence.container_ref != filters.container_ref:
            return False
        if filters.thread_ref is not None and evidence.thread_ref != filters.thread_ref:
            return False
        return True
