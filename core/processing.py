from __future__ import annotations

import dataclasses
import logging
from datetime import timedelta
from typing import Any, Callable

from core.contracts import ItemProcessingResult, ProcessResult
from core.models import SourceItem, utc_now
from core.observability import IntegrationDebugLogger, OBSERVABILITY_METADATA_KEY
from core.thread_rebuild import (
    FAILURE_CATEGORY_MISSING_USE_CASE,
    FAILURE_CATEGORY_MISSING_VISIBILITY,
    FAILURE_CATEGORY_UNKNOWN_USE_CASE,
    ThreadRebuilder,
    build_memory_provenance,
    classify_failure,
    truncate_processing_error,
    with_observability_metadata,
)
from core.vector_embed import VectorEmbedder
from semantic.base import SemanticPlugin
from storage.base import StorageProvider, ThreadProcessingScope

# Re-export shared constants so external callers (app/worker.py, tests) that
# import from core.service continue to work via the re-export in service.py.
from core.thread_rebuild import (  # noqa: F811
    FAILURE_CATEGORY_EXTRACTOR,
    FAILURE_CATEGORY_LLM,
    FAILURE_CATEGORY_MALFORMED_PAYLOAD,
    FAILURE_CATEGORY_STORAGE_COMMIT,
    FAILURE_CATEGORY_THREAD_REBUILD,
    FAILURE_CATEGORY_UNEXPECTED,
    MAX_PROCESSING_ERROR_LENGTH,
)


DEFAULT_PROCESSING_LEASE_SECONDS = 15 * 60
DEFAULT_PROCESSING_MAX_ATTEMPTS = 3
DEFAULT_RETRY_BACKOFF_SECONDS = 5
MAX_RETRY_BACKOFF_SECONDS = 5 * 60
REBUILD_ITEM_COUNT_THRESHOLD = 6
REBUILD_TIME_THRESHOLD_SECONDS = 30 * 60
REBUILD_TIME_MIN_ITEMS = 1


def _observability_state(source_item: SourceItem) -> dict[str, Any]:
    metadata = source_item.metadata or {}
    if not isinstance(metadata, dict):
        return {}
    state = metadata.get(OBSERVABILITY_METADATA_KEY)
    return dict(state) if isinstance(state, dict) else {}


class ItemProcessor:
    """Encapsulates source item processing logic extracted from PalliumService.

    Handles claiming source items from the processing queue, running semantic
    extraction via plugins, persisting results, and managing failure/backoff.
    """

    def __init__(
        self,
        storage: StorageProvider,
        semantic_plugins: dict[str, SemanticPlugin],
        default_use_case: str,
        vector_embedder: VectorEmbedder,
        thread_rebuilder: ThreadRebuilder,
        observability: IntegrationDebugLogger,
        persist_fn: Callable[[ProcessResult], None],
        supersede_fn: Callable[[str, str], None],
        get_item_processing_fn: Callable[[str], ItemProcessingResult],
        get_item_processing_summary_fn: Callable[[str], ItemProcessingResult] | None = None,
        metrics_store=None,
        shadow_llm_provider=None,
    ) -> None:
        self._storage = storage
        self._semantic_plugins = semantic_plugins
        self._default_use_case = default_use_case
        self._vector_embedder = vector_embedder
        self._thread_rebuilder = thread_rebuilder
        self._observability = observability
        self._persist_fn = persist_fn
        self._supersede_fn = supersede_fn
        self._get_item_processing = get_item_processing_fn
        self._get_item_processing_summary = get_item_processing_summary_fn or get_item_processing_fn
        self._metrics_store = metrics_store
        # W5 PR 3: shadow-extraction provider. None when the
        # [features] typed_extraction_shadow flag is off — the wired
        # shadow call becomes a no-op. Provider is injected rather
        # than looked up so the flag off-state doesn't touch the
        # semantic module at all.
        self._shadow_llm_provider = shadow_llm_provider
        self._logger = logging.getLogger(__name__)

    def process_next_source_item(
        self,
        *,
        worker_id: str,
        lease_seconds: int = DEFAULT_PROCESSING_LEASE_SECONDS,
        max_attempts: int = DEFAULT_PROCESSING_MAX_ATTEMPTS,
    ) -> ItemProcessingResult | None:
        return self._process_next_source_item(
            worker_id=worker_id,
            lease_seconds=lease_seconds,
            max_attempts=max_attempts,
            summary_only=False,
        )

    def process_next_source_item_summary(
        self,
        *,
        worker_id: str,
        lease_seconds: int = DEFAULT_PROCESSING_LEASE_SECONDS,
        max_attempts: int = DEFAULT_PROCESSING_MAX_ATTEMPTS,
    ) -> ItemProcessingResult | None:
        return self._process_next_source_item(
            worker_id=worker_id,
            lease_seconds=lease_seconds,
            max_attempts=max_attempts,
            summary_only=True,
        )

    def _process_next_source_item(
        self,
        *,
        worker_id: str,
        lease_seconds: int,
        max_attempts: int,
        summary_only: bool,
    ) -> ItemProcessingResult | None:
        get_processing_result = self._get_item_processing_summary if summary_only else self._get_item_processing

        # Try multi-package task first: process ALL pending packages for one source_item
        first_task = self._storage.claim_next_package_task(
            worker_id=worker_id,
            lease_seconds=lease_seconds,
            max_attempts=max_attempts,
        )
        if first_task is not None:
            source_item, package_name, package_attempts = first_task
            source_item_id = source_item.id
            packages_processed = [package_name]
            self._process_source_item(
                source_item,
                max_attempts=max_attempts,
                worker_id=worker_id,
                package_name=package_name,
                package_attempts=package_attempts,
            )
            # Process remaining packages for the same source_item
            while True:
                next_task = self._storage.claim_next_package_task_for_item(
                    source_item_id=source_item_id,
                    worker_id=worker_id,
                    lease_seconds=lease_seconds,
                    max_attempts=max_attempts,
                )
                if next_task is None:
                    break
                next_package, next_attempts = next_task
                packages_processed.append(next_package)
                # Re-fetch source_item in case metadata changed
                next_item = self._storage.get_source_item(source_item_id)
                self._process_source_item(
                    next_item,
                    max_attempts=max_attempts,
                    worker_id=worker_id,
                    package_name=next_package,
                    package_attempts=next_attempts,
                )
            result = get_processing_result(source_item_id)
            return dataclasses.replace(result, packages_processed=packages_processed)

        # Legacy path: claim from source_items table (for items without
        # package_processing_status rows, e.g. pre-migration data)
        source_item = self._storage.claim_next_source_item(
            worker_id=worker_id,
            lease_seconds=lease_seconds,
            max_attempts=max_attempts,
        )
        if source_item is None:
            return None
        self._process_source_item(
            source_item,
            max_attempts=max_attempts,
            worker_id=worker_id,
        )
        return get_processing_result(source_item.id)

    def drain_processing_queue(
        self,
        *,
        worker_id: str = "local-drain",
        lease_seconds: int = DEFAULT_PROCESSING_LEASE_SECONDS,
        max_attempts: int = DEFAULT_PROCESSING_MAX_ATTEMPTS,
        limit: int | None = None,
    ) -> list[ItemProcessingResult]:
        results: list[ItemProcessingResult] = []
        while limit is None or len(results) < limit:
            result = self.process_next_source_item(
                worker_id=worker_id,
                lease_seconds=lease_seconds,
                max_attempts=max_attempts,
            )
            if result is not None:
                results.append(result)
                continue
            thread_lease = self._thread_rebuilder.process_next_thread_rebuild(
                worker_id=worker_id,
                lease_seconds=lease_seconds,
            )
            if thread_lease is None:
                break
        return results

    def _process_source_item(
        self,
        source_item: SourceItem,
        *,
        max_attempts: int,
        worker_id: str | None = None,
        package_name: str | None = None,
        package_attempts: int | None = None,
    ) -> None:
        worker_label = worker_id or source_item.processing_claimed_by or "source-item-worker"
        # Multi-package path: package_name is explicit; legacy path: read from source_item.use_case
        plugin_name = package_name or source_item.use_case or self._default_use_case
        using_package_tracking = package_name is not None
        # Use package-specific attempt count when available, else source_item's
        current_attempts = package_attempts if package_attempts is not None else source_item.processing_attempts
        if source_item.use_case is None and not self._default_use_case and not using_package_tracking:
            failure_category = FAILURE_CATEGORY_MISSING_USE_CASE
            error = "missing_use_case"
            self._storage.fail_source_item_processing(
                source_item.id,
                error=error,
                next_attempt_at=None,
                final=True,
                metadata_updates={OBSERVABILITY_METADATA_KEY: {"failure_category": failure_category}},
            )
            self._emit_processing_failure(source_item, worker_id=worker_label, failure_category=failure_category, error=error)
            return

        plugin = self._semantic_plugins.get(plugin_name)
        if plugin is None:
            failure_category = FAILURE_CATEGORY_UNKNOWN_USE_CASE
            error = f"unknown_use_case:{plugin_name}"
            if using_package_tracking:
                self._storage.fail_package_task(
                    source_item.id, plugin_name,
                    error=error, next_attempt_at=None, final=True,
                )
            else:
                self._storage.fail_source_item_processing(
                    source_item.id,
                    error=error,
                    next_attempt_at=None,
                    final=True,
                    metadata_updates={OBSERVABILITY_METADATA_KEY: {"failure_category": failure_category}},
                )
            self._emit_processing_failure(source_item, worker_id=worker_label, failure_category=failure_category, error=error)
            return

        if plugin.requires_visibility_context and source_item.container_ref is None:
            failure_category = FAILURE_CATEGORY_MISSING_VISIBILITY
            error = "visibility_context_required"
            if using_package_tracking:
                self._storage.fail_package_task(
                    source_item.id, plugin_name,
                    error=error, next_attempt_at=None, final=True,
                )
            else:
                self._storage.fail_source_item_processing(
                    source_item.id,
                    error=error,
                    next_attempt_at=None,
                    final=True,
                    metadata_updates={OBSERVABILITY_METADATA_KEY: {"failure_category": failure_category}},
                )
            self._emit_processing_failure(source_item, worker_id=worker_label, failure_category=failure_category, error=error)
            return

        source_vector_entry = self._vector_embedder.build_source_item_vector_entry(plugin, source_item)

        memory_vectors_added = False
        try:
            direct_result = plugin.process_item(source_item)
            reconcile_process_result = getattr(plugin, "reconcile_process_result", None)
            if callable(reconcile_process_result):
                direct_result = reconcile_process_result(
                    direct_result,
                    storage=self._storage,
                    container_ref=source_item.container_ref,
                    visibility=source_item.visibility,
                )
            thread_rebuild_scope = None
            container_rebuild_scope = None
            if direct_result.thread_rebuild_requested:
                thread_rebuild_scope = self._thread_rebuilder.build_thread_processing_scope(
                    plugin_name=plugin_name,
                    plugin=plugin,
                    source_item=source_item,
                )
                container_rebuild_scope = self._thread_rebuilder.build_container_processing_scope(
                    plugin_name=plugin_name,
                    plugin=plugin,
                    source_item=source_item,
                )
            if thread_rebuild_scope is None:
                thread_rebuild_scope = self._should_force_rebuild_by_threshold(
                    plugin_name=plugin_name,
                    plugin=plugin,
                    source_item=source_item,
                )
            observability_patch: dict[str, Any] = {
                "thread_rebuild_completed": False,
            }
            if using_package_tracking:
                # In multi-package mode, accumulate rather than overwrite:
                # - memory_object_types: extend (each package adds its types)
                # - thread_rebuild_requested: OR (true if any package requested)
                # - failure_category: preserve first failure
                existing_obs = _observability_state(source_item)
                existing_types = list(existing_obs.get("memory_object_types", []))
                new_types = [memory_object.type for memory_object in direct_result.memory_objects]
                observability_patch["memory_object_types"] = existing_types + new_types
                if thread_rebuild_scope is not None or existing_obs.get("thread_rebuild_requested"):
                    observability_patch["thread_rebuild_requested"] = True
                else:
                    observability_patch["thread_rebuild_requested"] = False
                if existing_obs.get("thread_rebuild_completed"):
                    observability_patch["thread_rebuild_completed"] = True
            else:
                # Legacy single-package path: overwrite cleanly
                observability_patch["memory_object_types"] = [memory_object.type for memory_object in direct_result.memory_objects]
                observability_patch["thread_rebuild_requested"] = thread_rebuild_scope is not None
                observability_patch["failure_category"] = None
            metadata_updates = with_observability_metadata(
                direct_result.source_item_metadata_updates,
                source_item.id,
                observability_patch,
            )
            direct_result = ProcessResult(
                memory_objects=direct_result.memory_objects,
                relations=direct_result.relations,
                index_entries=direct_result.index_entries,
                source_item_metadata_updates=metadata_updates,
                thread_rebuild_requested=direct_result.thread_rebuild_requested,
                supersession_hints=direct_result.supersession_hints,
                promotion_hints=direct_result.promotion_hints,
            )
            if using_package_tracking:
                # Multi-package path: persist results without marking source_item as completed.
                # Source_item completion happens when ALL packages are done.
                supersession_pairs = self._storage.commit_package_process_result(
                    source_item_id=source_item.id,
                    result=direct_result,
                    thread_rebuild_scope=thread_rebuild_scope,
                    container_rebuild_scope=container_rebuild_scope,
                )
                self._storage.complete_package_task(source_item.id, plugin_name)
            else:
                supersession_pairs = self._storage.commit_processed_source_item(
                    source_item_id=source_item.id,
                    result=direct_result,
                    thread_rebuild_scope=thread_rebuild_scope,
                    container_rebuild_scope=container_rebuild_scope,
                )
            memory_vectors_added = self._vector_embedder.embed_process_result(direct_result)
            memory_provenance = build_memory_provenance(
                direct_result,
                default_source_item_id=source_item.id,
                supersession_pairs=supersession_pairs,
            )
            self._storage.update_source_item_metadata(
                source_item.id,
                {OBSERVABILITY_METADATA_KEY: {"produced_memory_provenance": memory_provenance}},
            )
            self._emit_processing_outcome(
                source_item=source_item,
                result=direct_result,
                thread_rebuild_scope=thread_rebuild_scope,
            )
            self._emit_memory_creation_provenance(
                source_item=source_item,
                provenance=memory_provenance,
            )
            # W5 PR 3: shadow extraction. Runs after the live extractor
            # has fully committed. Guaranteed non-fatal: the safe-wrapper
            # swallows every exception so shadow failures never propagate
            # up the live path.
            self._run_shadow_extraction_safely(
                source_item=source_item,
                plugin_name=plugin_name,
            )
        except Exception as exc:
            failure_category = classify_failure(exc, phase="process_item")
            error = truncate_processing_error(exc)
            if using_package_tracking:
                final_failure = current_attempts >= max_attempts
                next_attempt_at = None
                if not final_failure:
                    backoff_seconds = self._queue_backoff_seconds(current_attempts)
                    next_attempt_at = utc_now() + timedelta(seconds=backoff_seconds)
                self._storage.fail_package_task(
                    source_item.id, plugin_name,
                    error=error, next_attempt_at=next_attempt_at, final=final_failure,
                )
                # Update source_item metadata for observability
                self._storage.update_source_item_metadata(
                    source_item.id,
                    {OBSERVABILITY_METADATA_KEY: {"failure_category": failure_category}},
                )
            else:
                final_failure = current_attempts >= max_attempts
                next_attempt_at = None
                if not final_failure and source_item.processing_claimed_at is not None:
                    backoff_seconds = self._queue_backoff_seconds(current_attempts)
                    next_attempt_at = source_item.processing_claimed_at + timedelta(seconds=backoff_seconds)
                self._storage.fail_source_item_processing(
                    source_item.id,
                    error=error,
                    next_attempt_at=next_attempt_at,
                    final=final_failure,
                    metadata_updates={OBSERVABILITY_METADATA_KEY: {"failure_category": failure_category}},
                )
            self._emit_processing_failure(
                source_item,
                worker_id=worker_label,
                failure_category=failure_category,
                error=error,
            )

        source_vector_added = False
        if source_vector_entry is not None:
            source_vector_added = self._vector_embedder.embed_and_persist_vector_entry(source_vector_entry)

        if memory_vectors_added or source_vector_added:
            self._vector_embedder.save_vector_index()

    def _should_force_rebuild_by_threshold(
        self,
        *,
        plugin_name: str,
        plugin: SemanticPlugin,
        source_item: SourceItem,
    ) -> ThreadProcessingScope | None:
        scope = self._thread_rebuilder.build_thread_processing_scope(
            plugin_name=plugin_name,
            plugin=plugin,
            source_item=source_item,
        )
        if scope is None:
            return None
        lease = self._storage.get_thread_processing_lease(scope.scope_key)
        if lease is None or lease.collection_watermark_at is None:
            return None
        count = self._storage.count_source_items_for_thread_after(
            container_ref=scope.container_ref,
            thread_ref=source_item.thread_ref or "",
            after_created_at=lease.collection_watermark_at,
        )
        if count >= REBUILD_ITEM_COUNT_THRESHOLD:
            return scope
        elapsed = utc_now() - lease.collection_watermark_at
        if elapsed >= timedelta(seconds=REBUILD_TIME_THRESHOLD_SECONDS) and count >= REBUILD_TIME_MIN_ITEMS:
            return scope
        return None

    @staticmethod
    def _queue_backoff_seconds(attempt_count: int) -> int:
        return min(MAX_RETRY_BACKOFF_SECONDS, DEFAULT_RETRY_BACKOFF_SECONDS * (2 ** max(attempt_count - 1, 0)))

    def _emit_processing_outcome(
        self,
        *,
        source_item: SourceItem,
        result: ProcessResult,
        thread_rebuild_scope: ThreadProcessingScope | None,
    ) -> None:
        self._observability.emit(
            "source_item_processing_outcome",
            source_item_id=source_item.id,
            source_type=source_item.source_type,
            artifact_kind=source_item.artifact_kind,
            use_case=source_item.use_case,
            processing_status="completed",
            produced_memory_kinds=[memory_object.type for memory_object in result.memory_objects],
            thread_rebuild_ran=thread_rebuild_scope is not None,
        )
        if self._metrics_store is not None:
            self._metrics_store.record(
                "processing", "item_processed",
                container_ref=source_item.container_ref,
                thread_ref=source_item.thread_ref,
                payload={
                    "package": source_item.use_case or self._default_use_case,
                    "memory_types_created": [mo.type for mo in result.memory_objects],
                },
            )
            for mo in result.memory_objects:
                if mo.schema_id == "agent_work_trace.task_trace":
                    payload_data = mo.payload if isinstance(mo.payload, dict) else {}
                    self._metrics_store.record(
                        "work_trace", "thread_rebuild",
                        container_ref=mo.container_ref,
                        thread_ref=source_item.thread_ref,
                        value=float(payload_data.get("turn_count", 0)),
                        payload={
                            "exploratory_file_count": len(payload_data.get("exploratory_files", [])),
                            "productive_file_count": len(payload_data.get("productive_files", [])),
                            "commands_succeeded": len(payload_data.get("commands_succeeded", [])),
                            "commands_failed": len(payload_data.get("commands_failed", [])),
                            "has_outcome": "outcome" in payload_data,
                            "subject": payload_data.get("subject", ""),
                        },
                    )

    def _emit_processing_failure(
        self,
        source_item: SourceItem,
        *,
        worker_id: str,
        failure_category: str,
        error: str,
    ) -> None:
        self._observability.emit(
            "source_item_processing_failure",
            source_item_id=source_item.id,
            source_type=source_item.source_type,
            artifact_kind=source_item.artifact_kind,
            use_case=source_item.use_case,
            processing_status="failed",
            worker_id=worker_id,
            failure_category=failure_category,
            error=error,
        )
        if self._metrics_store is not None:
            self._metrics_store.record(
                "processing", "extraction_failed",
                container_ref=source_item.container_ref,
                thread_ref=source_item.thread_ref,
                payload={
                    "package": source_item.use_case or self._default_use_case,
                    "error": str(error)[:500],
                },
            )

    def _run_shadow_extraction_safely(
        self,
        *,
        source_item: SourceItem,
        plugin_name: str,
    ) -> None:
        """W5 PR 3: run the shadow extractor on a committed source item.

        Every failure mode is caught and dropped — the shadow must
        never propagate errors to the live path. Feature flag is
        expressed as ``self._shadow_llm_provider is None``: when the
        flag is off, no provider is injected and this method is a
        cheap no-op (early return, no import of the shadow module).
        """
        if self._shadow_llm_provider is None:
            return
        try:
            # Imported lazily so flag-off processes pay no import cost.
            from semantic.extraction_typed_shadow import (
                run_typed_shadow_extraction,
            )

            extraction = run_typed_shadow_extraction(
                source_item, provider=self._shadow_llm_provider,
            )
            rows = self._build_shadow_rows(
                source_item=source_item,
                plugin_name=plugin_name,
                extraction=extraction,
            )
            if not rows:
                return
            insert = getattr(self._storage, "insert_shadow_extraction", None)
            if insert is None:
                return
            insert(rows=rows)
        except Exception as exc:  # noqa: BLE001 -- shadow must never break live
            self._logger.warning(
                "shadow_extraction_dropped",
                extra={
                    "source_item_id": source_item.id,
                    "error": repr(exc)[:500],
                },
            )

    def _build_shadow_rows(
        self,
        *,
        source_item: SourceItem,
        plugin_name: str,
        extraction,
    ) -> list:
        """Convert a TypedShadowExtraction into MemoryObjectShadowRecord rows.

        One row per extracted item; if parse_status != 'ok' and no items
        came back, one '_shadow_marker' row is written so the failure-
        rate query has evidence.
        """
        import json as _json
        from datetime import datetime, timezone

        from core.models import new_id
        from storage.sqlite_schema import MemoryObjectShadowRecord

        now = datetime.now(timezone.utc)
        provider = self._shadow_llm_provider
        provider_name = getattr(provider, "provider_name", "unknown")
        provider_kind = getattr(provider, "provider_kind", "unknown")
        model = getattr(provider, "model", "unknown")

        rows: list[MemoryObjectShadowRecord] = []
        metadata_json = None
        if extraction.llm_call_metadata is not None:
            meta = extraction.llm_call_metadata
            metadata_json = _json.dumps({
                "provider_name": getattr(meta, "provider_name", None),
                "model": getattr(meta, "model", None),
                "attempt_count": getattr(meta, "attempt_count", None),
                "retry_count": getattr(meta, "retry_count", None),
            })

        def _push(mtype: str, payload: dict, subject: str) -> None:
            rows.append(MemoryObjectShadowRecord(
                id=new_id(),
                source_item_id=source_item.id,
                package_name=plugin_name,
                shadow_run_id=extraction.shadow_run_id,
                shadow_run_at=now,
                prompt_version=extraction.prompt_version,
                provider_name=provider_name,
                provider_kind=provider_kind,
                model=model,
                type=mtype,
                schema_id=f"typed_shadow.{mtype}",
                schema_version="1",
                payload_json=_json.dumps(payload, ensure_ascii=False),
                subject=subject or None,
                container_ref=source_item.container_ref,
                actor_ref=source_item.actor_ref,
                visibility=source_item.visibility,
                live_counterpart_ids_json=None,
                llm_call_metadata_json=metadata_json,
                parse_status=extraction.parse_status,
                parse_error=extraction.parse_error,
                created_at=now,
            ))

        for d in extraction.decisions:
            _push("decision", {
                "subject": d.subject, "statement": d.statement,
                "rationale": d.rationale, "evidence_span": d.evidence_span,
                "alternatives_rejected": list(d.alternatives_rejected),
            }, d.subject)
        for i in extraction.investigations:
            _push("investigation_outcome", {
                "subject": i.subject, "hypothesis": i.hypothesis,
                "outcome": i.outcome, "resolution": i.resolution,
                "evidence_span": i.evidence_span,
            }, i.subject)
        for c in extraction.constraints:
            _push("constraint_memory", {
                "subject": c.subject, "modality": c.modality,
                "action": c.action, "statement": c.statement,
                "evidence_span": c.evidence_span,
            }, c.subject)
        for f in extraction.operational_facts:
            _push("operational_fact", {
                "command_family": f.command_family, "subject": f.subject,
                "artifact": f.artifact, "outcome": f.outcome,
                "evidence_span": f.evidence_span,
            }, f.subject)
        for s in extraction.supersessions:
            _push("supersession", {
                "subject": s.subject,
                "supersedes_statement": s.supersedes_statement,
                "new_statement": s.new_statement,
                "evidence_span": s.evidence_span,
            }, s.subject)

        # Marker row: total-failure cases still get a row so the eval
        # can measure shadow failure rate.
        if not rows and extraction.parse_status != "ok":
            _push("_shadow_marker", {}, "")

        return rows

    def _emit_memory_creation_provenance(
        self,
        *,
        source_item: SourceItem,
        provenance: list[dict[str, Any]],
    ) -> None:
        for entry in provenance:
            self._observability.emit(
                "memory_creation_provenance",
                source_item_id=source_item.id,
                memory_object_id=entry["memory_object_id"],
                memory_kind=entry["memory_kind"],
                source_item_ids=entry["source_item_ids"],
                superseded_memory_ids=entry["superseded_memory_ids"],
            )
