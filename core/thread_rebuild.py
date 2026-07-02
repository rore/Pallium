from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Callable

from capabilities.thread_aggregation import build_thread_aggregate
from capabilities.workstream_signals import parse_json_safe, signals_from_item
from capabilities.workstreams import (
    WorkstreamCapability,
    WorkstreamRegistry,
    assign_workstream_for_item,
    watermark_for,
)
from core.contracts import ProcessResult
from core.models import MemoryObject, SourceItem
from core.observability import IntegrationDebugLogger, OBSERVABILITY_METADATA_KEY
from core.vector_embed import VectorEmbedder
from core.visibility import visibility_matches_exact, visibility_label
from providers.llm.base import LLMProviderError
from semantic.base import SemanticPlugin, ThreadAggregationSemanticPlugin
from storage.base import StorageProvider, ThreadProcessingLease, ThreadProcessingScope
from storage.sqlite_codec import extract_memory_subject


# ── Failure classification constants (shared with core.processing) ──────────

FAILURE_CATEGORY_MISSING_USE_CASE = "missing_use_case"
FAILURE_CATEGORY_MISSING_VISIBILITY = "missing_visibility_context"
FAILURE_CATEGORY_UNKNOWN_USE_CASE = "unknown_use_case"
FAILURE_CATEGORY_MALFORMED_PAYLOAD = "malformed_payload"
FAILURE_CATEGORY_EXTRACTOR = "extractor_failure"
FAILURE_CATEGORY_LLM = "llm_failure"
FAILURE_CATEGORY_THREAD_REBUILD = "thread_rebuild_failure"
FAILURE_CATEGORY_STORAGE_COMMIT = "storage_commit_failure"
FAILURE_CATEGORY_UNEXPECTED = "unexpected_runtime_failure"

MAX_PROCESSING_ERROR_LENGTH = 1000

CONTAINER_SCOPE_RECENT_ITEMS = 200

THREAD_WINDOW_BUDGET_CHARS = 16000


# ── Shared module-level helpers ─────────────────────────────────────────────

def _preferred_active_summary_ref(memory_objects: list[MemoryObject]) -> dict[str, str] | None:
    if not memory_objects:
        return None
    preferred = min(
        memory_objects,
        key=lambda item: (item.created_at, item.id),
    )
    return {"kind": preferred.type, "id": preferred.id}


def classify_failure(error: Exception, *, phase: str) -> str:
    if isinstance(error, LLMProviderError):
        return FAILURE_CATEGORY_LLM
    if isinstance(error, (json.JSONDecodeError, ValueError, TypeError)):
        return FAILURE_CATEGORY_MALFORMED_PAYLOAD
    if phase == "thread_rebuild":
        return FAILURE_CATEGORY_THREAD_REBUILD
    if phase == "process_item":
        return FAILURE_CATEGORY_EXTRACTOR
    return FAILURE_CATEGORY_UNEXPECTED


def with_observability_metadata(
    existing_updates: dict[str, dict[str, Any]],
    source_item_id: str,
    patch: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    merged_updates = dict(existing_updates)
    source_updates = dict(merged_updates.get(source_item_id, {}))
    existing_observability = source_updates.get(OBSERVABILITY_METADATA_KEY)
    observability_state = dict(existing_observability) if isinstance(existing_observability, dict) else {}
    observability_state.update(patch)
    source_updates[OBSERVABILITY_METADATA_KEY] = observability_state
    merged_updates[source_item_id] = source_updates
    return merged_updates


def truncate_processing_error(error: Exception) -> str:
    text = str(error).strip() or error.__class__.__name__
    return text[:MAX_PROCESSING_ERROR_LENGTH]


def _envelope_to_dict(memory: MemoryObject) -> dict:
    """Render the memory envelope as a JSON-friendly dict for signal extraction."""
    env = memory.envelope
    if env is None:
        return {}
    scope = env.scope
    return {
        "scope": {
            "container_ref": scope.container_ref if scope else None,
            "thread_ref": scope.thread_ref if scope else None,
            "work_refs": list(scope.work_refs) if scope else [],
        },
        "subjects": [
            {"kind": s.kind, "value": s.value} for s in env.subjects
        ],
    }


def _max_created_at(items: list[SourceItem]) -> datetime:
    latest = max(item.created_at for item in items)
    if latest.tzinfo is None:
        from datetime import timezone as _tz
        return latest.replace(tzinfo=_tz.utc)
    return latest


def build_memory_provenance(
    result: ProcessResult,
    *,
    default_source_item_id: str | None = None,
    supersession_pairs: list[tuple[str, str]] | None = None,
) -> list[dict[str, Any]]:
    supported_by: dict[str, list[str]] = {}
    superseded_by_replacement: dict[str, list[str]] = {}
    for relation in result.relations:
        if relation.from_kind != "memory_object":
            continue
        if relation.relation_type == "supported_by" and relation.to_kind == "source_item":
            supported_by.setdefault(relation.from_id, []).append(relation.to_id)
        elif relation.relation_type == "supersedes" and relation.to_kind == "memory_object":
            superseded_by_replacement.setdefault(relation.from_id, []).append(relation.to_id)
    for superseded_id, replacement_id in supersession_pairs or []:
        superseded_by_replacement.setdefault(replacement_id, []).append(superseded_id)

    provenance: list[dict[str, Any]] = []
    for memory_object in result.memory_objects:
        source_item_ids = supported_by.get(memory_object.id, [])
        if not source_item_ids and default_source_item_id is not None:
            source_item_ids = [default_source_item_id]
        provenance.append(
            {
                "memory_object_id": memory_object.id,
                "memory_kind": memory_object.type,
                "source_item_ids": sorted(dict.fromkeys(source_item_ids)),
                "superseded_memory_ids": sorted(dict.fromkeys(superseded_by_replacement.get(memory_object.id, []))),
            }
        )
    return provenance


# ── ThreadRebuilder ─────────────────────────────────────────────────────────

class ThreadRebuilder:
    """Encapsulates thread rebuild logic extracted from PalliumService.

    Handles claiming thread rebuild leases, deciding whether to rebuild,
    building thread summaries via semantic plugins, and persisting results.
    """

    _MAX_THREAD_REBUILD_ITERATIONS = 15

    def __init__(
        self,
        storage: StorageProvider,
        semantic_plugins: dict[str, SemanticPlugin],
        vector_embedder: VectorEmbedder,
        observability: IntegrationDebugLogger,
        persist_fn: Callable[[ProcessResult], None],
        supersede_fn: Callable[[str, str], None],
        consolidation_fn: Callable[[str, str, list[str]], None] | None = None,
        workstream_capability: WorkstreamCapability | None = None,
    ) -> None:
        self._storage = storage
        self._semantic_plugins = semantic_plugins
        self._vector_embedder = vector_embedder
        self._observability = observability
        self._persist_fn = persist_fn
        self._supersede_fn = supersede_fn
        self._consolidation_fn = consolidation_fn
        self._workstream_capability = workstream_capability
        self._logger = logging.getLogger(__name__)

    def process_next_thread_rebuild(
        self,
        *,
        worker_id: str,
        lease_seconds: int,
    ) -> ThreadProcessingLease | None:
        lease = self._storage.claim_next_thread_processing_scope(
            worker_id=worker_id,
            lease_seconds=lease_seconds,
        )
        if lease is None:
            return None
        self._process_thread_rebuild_lease(lease, worker_id=worker_id, lease_seconds=lease_seconds)
        return lease

    def build_thread_processing_scope(
        self,
        *,
        plugin_name: str,
        plugin: SemanticPlugin,
        source_item: SourceItem,
    ) -> ThreadProcessingScope | None:
        if not isinstance(plugin, ThreadAggregationSemanticPlugin):
            return None
        if not plugin.supports_thread_aggregation(source_item):
            return None
        if not source_item.container_ref or not source_item.thread_ref:
            return None
        scope_key = json.dumps(
            {
                "use_case": plugin_name,
                "container_ref": source_item.container_ref,
                "thread_ref": source_item.thread_ref,
                "visibility": source_item.visibility,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return ThreadProcessingScope(
            scope_key=scope_key,
            use_case=plugin_name,
            container_ref=source_item.container_ref,
            thread_ref=source_item.thread_ref,
            visibility=source_item.visibility,
        )

    def build_container_processing_scope(
        self,
        *,
        plugin_name: str,
        plugin: SemanticPlugin,
        source_item: SourceItem,
    ) -> ThreadProcessingScope | None:
        if not isinstance(plugin, ThreadAggregationSemanticPlugin):
            return None
        if not plugin.supports_container_aggregation:
            return None
        if not plugin.supports_thread_aggregation(source_item):
            return None
        if not source_item.container_ref:
            return None
        scope_key = json.dumps(
            {
                "use_case": plugin_name,
                "container_ref": source_item.container_ref,
                "thread_ref": None,
                "visibility": source_item.visibility,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return ThreadProcessingScope(
            scope_key=scope_key,
            use_case=plugin_name,
            container_ref=source_item.container_ref,
            thread_ref=None,
            visibility=source_item.visibility,
        )

    def _process_thread_rebuild_lease(
        self,
        lease: ThreadProcessingLease,
        *,
        worker_id: str,
        lease_seconds: int,
    ) -> None:
        current_lease = lease
        for _iteration in range(self._MAX_THREAD_REBUILD_ITERATIONS):
            plugin = self._semantic_plugins[current_lease.use_case]
            thread_items: list[SourceItem] = []
            thread_result: ProcessResult | None = None
            supersession_pairs: list[tuple[str, str]] = []
            try:
                thread_result, supersede_plan, thread_items = self._maybe_rebuild_thread_summary(
                    plugin=plugin,
                    thread_scope=current_lease.as_scope(),
                    collection_watermark_at=current_lease.collection_watermark_at,
                )
                if thread_result is not None:
                    supersession_pairs = [
                        (superseded_id, replacement_id)
                        for replacement_id, superseded_ids in supersede_plan.items()
                        for superseded_id in superseded_ids
                    ]
                    metadata_updates = dict(thread_result.source_item_metadata_updates)
                    for thread_item in thread_items:
                        metadata_updates = with_observability_metadata(
                            metadata_updates,
                            thread_item.id,
                            {"thread_rebuild_completed": True},
                        )
                    thread_result = ProcessResult(
                        memory_objects=thread_result.memory_objects,
                        relations=thread_result.relations,
                        index_entries=thread_result.index_entries,
                        source_item_metadata_updates=metadata_updates,
                        supersession_hints=thread_result.supersession_hints,
                        promotion_hints=thread_result.promotion_hints,
                    )
                self._emit_thread_rebuild_outcome(
                    lease=current_lease,
                    thread_items=thread_items,
                    result=thread_result,
                    supersession_pairs=supersession_pairs,
                )
            except Exception as exc:
                self._observability.emit(
                    "thread_rebuild_outcome",
                    thread_ref=current_lease.thread_ref,
                    visibility_scope=visibility_label(current_lease.visibility),
                    visibility=current_lease.visibility,
                    processing_status="failed",
                    failure_category=classify_failure(exc, phase="thread_rebuild"),
                    error=truncate_processing_error(exc),
                )
                return

            if thread_result is not None:
                is_container_scope = current_lease.thread_ref is None
                items_watermark = (
                    max((item.created_at for item in thread_items), default=None)
                    if thread_items else None
                )
                try:
                    has_pending = self._storage.commit_process_result_and_complete_scope(
                        result=thread_result,
                        supersession_pairs=supersession_pairs,
                        scope_key=current_lease.scope_key,
                        worker_id=worker_id,
                        claimed_at=current_lease.processing_claimed_at,
                        collection_watermark_at=items_watermark,
                    )
                except Exception:
                    self._logger.warning(
                        "Thread rebuild commit failed for scope %s; lease will expire and scope will be re-claimed",
                        current_lease.scope_key,
                        exc_info=True,
                    )
                    raise
                if self._vector_embedder.embed_process_result(thread_result):
                    self._vector_embedder.save_vector_index()
                self._maybe_assign_workstreams(
                    thread_items=thread_items,
                    thread_result=thread_result,
                    container_ref=current_lease.container_ref,
                    visibility=current_lease.visibility,
                    prior_watermark=current_lease.collection_watermark_at,
                )
                self._maybe_trigger_fact_consolidation(
                    thread_result=thread_result,
                    use_case=current_lease.use_case,
                    container_ref=current_lease.container_ref,
                    current_thread_ref=current_lease.thread_ref,
                )
            else:
                try:
                    has_pending = self._storage.complete_thread_processing_scope(
                        scope_key=current_lease.scope_key,
                        worker_id=worker_id,
                        claimed_at=current_lease.processing_claimed_at,
                    )
                except Exception:
                    self._logger.warning(
                        "Thread rebuild scope completion failed for scope %s; lease will expire",
                        current_lease.scope_key,
                        exc_info=True,
                    )
                    raise
            if not has_pending:
                return
            next_lease = self._storage.claim_thread_processing_scope(
                scope=current_lease.as_scope(),
                worker_id=worker_id,
                lease_seconds=lease_seconds,
            )
            if next_lease is None:
                return
            current_lease = next_lease
        self._observability.emit(
            "thread_rebuild_iteration_limit",
            scope_key=current_lease.scope_key,
            thread_ref=current_lease.thread_ref,
        )

    def _maybe_assign_workstreams(
        self,
        *,
        thread_items: list[SourceItem],
        thread_result: ProcessResult,
        container_ref: str | None,
        visibility: str | None,
        prior_watermark: datetime | None,
    ) -> None:
        """Phase 4A — workstream assignment via M1 delayed mechanism.

        Runs the deterministic cascade against thread_items new since
        ``prior_watermark`` for ``(container_ref, visibility)``. Writes
        ``source_item_workstreams`` rows (idempotent on the composite PK)
        and ``memory_workstreams`` rows for memories whose source items
        just received a resolved id.

        Diagnostic-only — does NOT change any other behavior. See
        docs/designs/014-workstream-consolidation-rekey.md.
        """
        if self._workstream_capability is None:
            return
        if not container_ref or not visibility:
            return
        if not thread_items:
            return

        # Filter to items new since prior watermark (M1 delayed assignment).
        if prior_watermark is not None:
            new_items = [item for item in thread_items if item.created_at > prior_watermark]
        else:
            new_items = list(thread_items)
        if not new_items:
            return

        try:
            registry = self._workstream_capability.load_registry(
                container_ref=container_ref, visibility=visibility
            )

            # Pre-load memories attached to these source items so signal
            # extraction can use envelope subjects + payload titles.
            source_ids = [item.id for item in new_items]
            memories_by_source: dict[str, list[MemoryObject]] = (
                self._storage.list_memory_objects_for_source_items(source_ids)
            )

            # Track the (item -> assigned ws_id) tuples we wrote so we can
            # link memories afterwards.
            assigned_now: dict[str, str] = {}

            for item in sorted(new_items, key=lambda i: (i.created_at, i.id)):
                created_at = item.created_at
                memory_records = [
                    {
                        "type": mo.type,
                        "payload": mo.payload,
                        "envelope": _envelope_to_dict(mo),
                    }
                    for mo in memories_by_source.get(item.id, [])
                ]
                metadata_dict = item.metadata or {}
                if not isinstance(metadata_dict, dict):
                    metadata_dict = parse_json_safe(metadata_dict if isinstance(metadata_dict, str) else None)
                signals = signals_from_item(
                    content_text=item.content or "",
                    metadata_json=metadata_dict,
                    memory_records=memory_records,
                )
                wm = watermark_for(created_at)
                result = assign_workstream_for_item(
                    item_signals=signals,
                    container_ref=container_ref,
                    thread_ref=item.thread_ref,
                    visibility=visibility,
                    created_at=created_at,
                    watermark=wm,
                    registry=registry,
                )
                ws_id = result.workstream_id
                # Persist the registry row first so junction FKs resolve.
                if ws_id.kind == "unknown":
                    self._workstream_capability.record_unknown_workstream(
                        ws_id=ws_id,
                        container_ref=container_ref,
                        visibility=visibility,
                        opened_at=created_at,
                    )
                # Note: resolved-id rows are flushed via persist_registry()
                # at the end of the cascade run for this lease.
                self._workstream_capability.link_source_item(
                    source_item_id=item.id,
                    workstream_id=ws_id.id,
                    watermark=wm,
                    assigned_at=created_at,
                    stage=result.stage,
                )
                assigned_now[item.id] = ws_id.id

            # Flush the (now-mutated) registry — persists newly opened ws
            # rows + last_touched updates. INSERT OR UPSERT is idempotent.
            self._workstream_capability.persist_registry(registry, now=_max_created_at(new_items))

            # Link any memories whose source items received an assignment
            # (only for memories produced in this rebuild — safer to scope
            # to thread_result.memory_objects).
            self._link_thread_result_memories(thread_result, assigned_now)
        except Exception:  # never let workstream assignment break rebuild
            self._logger.warning(
                "Workstream assignment failed for container=%s visibility=%s; continuing",
                container_ref, visibility, exc_info=True,
            )

    def _link_thread_result_memories(
        self,
        thread_result: ProcessResult,
        assigned_now: dict[str, str],
    ) -> None:
        if self._workstream_capability is None or not assigned_now:
            return
        # Build supported_by mapping from the result's relations.
        memory_to_sources: dict[str, list[str]] = {}
        for relation in thread_result.relations:
            if relation.from_kind != "memory_object":
                continue
            if relation.relation_type != "supported_by":
                continue
            if relation.to_kind != "source_item":
                continue
            memory_to_sources.setdefault(relation.from_id, []).append(relation.to_id)
        for memory in thread_result.memory_objects:
            sources = memory_to_sources.get(memory.id, [])
            ws_ids: list[str] = []
            for sid in sources:
                ws_id = assigned_now.get(sid)
                if ws_id is None:
                    # Fall back to a lookup in case it was assigned by an
                    # earlier rebuild (carry-forward across watermarks).
                    looked_up = self._workstream_capability.lookup_query_source_item(sid)
                    if looked_up:
                        ws_id = looked_up
                if ws_id and ws_id not in ws_ids:
                    ws_ids.append(ws_id)
            # Prefer the resolved (non-unknown) id if the memory spans both.
            chosen = next((w for w in ws_ids if not w.startswith("unknown:")), None)
            if chosen is None and ws_ids:
                chosen = ws_ids[0]
            if chosen:
                self._workstream_capability.link_memory(
                    memory_object_id=memory.id,
                    workstream_id=chosen,
                    assigned_at=memory.created_at,
                )

    def _maybe_trigger_fact_consolidation(
        self,
        *,
        thread_result: ProcessResult,
        use_case: str,
        container_ref: str,
        current_thread_ref: str | None,
    ) -> None:
        """After thread rebuild, check if any extracted subjects need cross-thread consolidation."""
        if self._consolidation_fn is None:
            return

        # Collect subjects from newly created atomic_facts
        subjects: set[str] = set()
        for mo in thread_result.memory_objects:
            if mo.type != "atomic_fact":
                continue
            normalized = extract_memory_subject(mo)
            if normalized:
                subjects.add(normalized)

        if not subjects:
            return

        # For each subject, check if cross-thread facts or an existing fact_summary exist
        subjects_to_consolidate: list[str] = []
        for subject in subjects:
            existing = self._storage.list_memory_objects(
                memory_types=["atomic_fact", "fact_summary"],
                lifecycle="active",
                container_ref=container_ref,
                subject_in=[subject],
            )
            # Check for cross-thread matches: any fact from a different thread, or any fact_summary
            has_cross_thread = any(
                mo.type == "fact_summary"
                or (mo.payload.get("thread_ref") and mo.payload["thread_ref"] != current_thread_ref)
                for mo in existing
            )
            if has_cross_thread:
                subjects_to_consolidate.append(subject)

        if not subjects_to_consolidate:
            return

        try:
            self._consolidation_fn(use_case, container_ref, subjects_to_consolidate)
        except Exception:
            self._logger.warning(
                "Post-rebuild fact consolidation failed for %s (subjects: %s); will retry on next rebuild",
                container_ref, subjects_to_consolidate, exc_info=True,
            )

    def _maybe_rebuild_thread_summary(
        self,
        *,
        plugin: SemanticPlugin,
        thread_scope: ThreadProcessingScope,
        collection_watermark_at: datetime | None = None,
    ) -> tuple[ProcessResult | None, dict[str, list[str]], list[SourceItem]]:
        if not isinstance(plugin, ThreadAggregationSemanticPlugin):
            return None, {}, []

        is_container_scope = thread_scope.thread_ref is None
        all_content_size = 0
        all_thread_items: list[SourceItem] = []

        if is_container_scope:
            is_incremental = not plugin.rebuild_supersedes_prior
            if is_incremental and collection_watermark_at is not None:
                thread_items = [
                    item
                    for item in self._storage.list_top_level_messages_for_container(
                        thread_scope.container_ref,
                        after_created_at=collection_watermark_at,
                    )
                    if plugin.supports_thread_aggregation(item)
                ]
            else:
                thread_items = [
                    item
                    for item in self._storage.list_top_level_messages_for_container(
                        thread_scope.container_ref,
                        max_items=CONTAINER_SCOPE_RECENT_ITEMS,
                    )
                    if plugin.supports_thread_aggregation(item)
                ]
        else:
            all_thread_items = [
                item
                for item in self._storage.list_source_items_for_thread(thread_scope.container_ref, thread_scope.thread_ref)
                if plugin.supports_thread_aggregation(item)
            ]
            all_content_size = sum(len(item.content.strip()) for item in all_thread_items)
            if collection_watermark_at is not None and all_content_size > THREAD_WINDOW_BUDGET_CHARS:
                thread_items = [
                    item for item in all_thread_items
                    if item.created_at > collection_watermark_at
                ]
            else:
                thread_items = all_thread_items

        if plugin.requires_visibility_context:
            thread_items = [
                item
                for item in thread_items
                if visibility_matches_exact(item.visibility, thread_scope.visibility)
            ]

        if not is_container_scope and len(thread_items) < 2:
            if (all_content_size > THREAD_WINDOW_BUDGET_CHARS
                    and len(thread_items) >= 1):
                pass
            else:
                return None, {}, thread_items
        if is_container_scope and len(thread_items) < 1:
            return None, {}, thread_items

        if not is_container_scope:
            thread_items = self._apply_thread_window_budget(thread_items)

        prior_summary = self._get_prior_thread_summary(
            container_ref=thread_scope.container_ref,
            thread_ref=thread_scope.thread_ref,
            plugin=plugin,
            visibility=thread_scope.visibility,
        ) if not is_container_scope else None

        is_incremental = (
            not is_container_scope
            and collection_watermark_at is not None
            and all_content_size > THREAD_WINDOW_BUDGET_CHARS
        )

        memory_by_source = self._storage.list_memory_objects_for_source_items(
            [item.id for item in thread_items],
        )

        if is_incremental:
            all_memory_by_source = self._storage.list_memory_objects_for_source_items(
                [item.id for item in all_thread_items],
            )
            active_thread_memory_ids = self._find_active_thread_memory_ids(all_thread_items, all_memory_by_source)
        else:
            all_memory_by_source = memory_by_source
            active_thread_memory_ids = self._find_active_thread_memory_ids(thread_items, memory_by_source)

        aggregate = build_thread_aggregate(thread_items, container_scope=is_container_scope, prior_summary=prior_summary)
        conclusions = self._collect_thread_conclusions(thread_items, memory_by_source, conclusion_types=plugin.thread_conclusion_types)

        if is_incremental and prior_summary:
            prior_conclusions = self._collect_thread_conclusions(
                all_thread_items,
                all_memory_by_source,
                conclusion_types=plugin.thread_conclusion_types,
            )
            for conclusion in prior_conclusions:
                if conclusion.id not in {c.id for c in conclusions}:
                    conclusions.append(conclusion)

        thread_result = plugin.build_thread_summary(aggregate, conclusions)
        reconcile_process_result = getattr(plugin, "reconcile_process_result", None)
        if callable(reconcile_process_result) and thread_result is not None:
            thread_result = reconcile_process_result(
                thread_result,
                storage=self._storage,
                container_ref=thread_scope.container_ref,
                visibility=thread_scope.visibility,
            )
        supersede_plan: dict[str, list[str]] = {}
        if plugin.rebuild_supersedes_prior:
            non_superseding = plugin.non_superseding_types
            for memory_object in thread_result.memory_objects:
                if memory_object.type in non_superseding:
                    supersede_plan[memory_object.id] = []
                    continue
                key = (memory_object.type, memory_object.schema_id)
                supersede_plan[memory_object.id] = [
                    superseded_id
                    for superseded_id in active_thread_memory_ids.get(key, [])
                    if superseded_id != memory_object.id
                ]
        return thread_result, supersede_plan, thread_items

    def _apply_thread_window_budget(self, thread_items: list[SourceItem]) -> list[SourceItem]:
        """Trim thread items to fit within the window budget (char count).

        Takes items from the end (most recent) working backwards, stopping when
        adding the next item would exceed the budget. If a single item exceeds
        the budget, it is included alone (guaranteed progress).
        """
        total = 0
        window: list[SourceItem] = []
        for item in reversed(thread_items):
            item_chars = len(item.content.strip())
            if window and total + item_chars > THREAD_WINDOW_BUDGET_CHARS:
                break
            window.append(item)
            total += item_chars
        window.reverse()
        return window

    def _get_prior_thread_summary(
        self,
        *,
        container_ref: str,
        thread_ref: str | None,
        plugin: ThreadAggregationSemanticPlugin,
        visibility: str | None = None,
    ) -> str | None:
        """Fetch the most recent active thread_summary text for the given thread."""
        if thread_ref is None:
            return None
        summaries = self._storage.list_memory_objects(
            memory_types=["thread_summary"],
            lifecycle="active",
            container_ref=container_ref,
        )
        matching = [
            mo for mo in summaries
            if mo.payload.get("thread_ref") == thread_ref
            and mo.schema_id == plugin.thread_summary_schema_id
            and (visibility is None or mo.visibility == visibility)
        ]
        if not matching:
            return None
        latest = max(matching, key=lambda mo: (mo.created_at, mo.id))
        return latest.payload.get("summary") or None

    def _find_active_thread_memory_ids(
        self,
        thread_items: list[SourceItem],
        memory_by_source: dict[str, list[MemoryObject]],
    ) -> dict[tuple[str, str], list[str]]:
        seen: set[str] = set()
        ids: dict[tuple[str, str], list[str]] = {}
        for source_item in thread_items:
            for memory_object in memory_by_source.get(source_item.id, []):
                if memory_object.lifecycle != "active":
                    continue
                if memory_object.id in seen:
                    continue
                seen.add(memory_object.id)
                ids.setdefault((memory_object.type, memory_object.schema_id), []).append(memory_object.id)
        return ids

    def _collect_thread_conclusions(
        self,
        thread_items: list[SourceItem],
        memory_by_source: dict[str, list[MemoryObject]],
        *,
        conclusion_types: frozenset[str] = frozenset(),
    ) -> list[MemoryObject]:
        conclusions: dict[str, MemoryObject] = {}
        if not conclusion_types:
            return []
        for source_item in thread_items:
            for memory_object in memory_by_source.get(source_item.id, []):
                if memory_object.lifecycle != "active":
                    continue
                if memory_object.type not in conclusion_types:
                    continue
                conclusions[memory_object.id] = memory_object
        return list(conclusions.values())

    def _emit_thread_rebuild_outcome(
        self,
        *,
        lease: ThreadProcessingLease,
        thread_items: list[SourceItem],
        result: ProcessResult | None,
        supersession_pairs: list[tuple[str, str]],
    ) -> None:
        created_memory_kinds = [memory_object.type for memory_object in result.memory_objects] if result is not None else []
        active_summary_ref = _preferred_active_summary_ref(result.memory_objects if result is not None else [])
        self._observability.emit(
            "thread_rebuild_outcome",
            thread_ref=lease.thread_ref,
            visibility_scope=visibility_label(lease.visibility),
            visibility=lease.visibility,
            input_item_count_considered=len(thread_items),
            created_or_updated_memory_kinds=created_memory_kinds,
            superseded_memory_ids=[superseded_id for superseded_id, _replacement_id in supersession_pairs],
            superseded_memory_count=len(supersession_pairs),
            final_active_summary_kind=active_summary_ref["kind"] if active_summary_ref is not None else None,
            final_active_summary_id=active_summary_ref["id"] if active_summary_ref is not None else None,
            processing_status="completed",
        )
