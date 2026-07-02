"""PR D — cross-run dedup for operational_fact via reconcile_process_result.

Live data motivated by 48 remaining rows post-PR-C: same interpreter
stored 4×, same script path 3×, same URL 2× across query strings.
Each rebuild re-derived the same candidates and wrote fresh rows
because the class-level ``non_superseding_types`` exempts
``operational_fact`` from the blanket sweep and the storage-pass
supersession the class docstring promises was never implemented.

This test locks the reconcile hook's contract:

- Second-rebuild candidates matching an existing (family, role,
  scope_kind, scope_ref, artifact_normalized) slot are DROPPED from
  the ProcessResult before it reaches persistence.
- Intra-batch duplicates against a freshly-added slot are also
  dropped (so the same result can't inflate its own count).
- Corresponding IndexEntry rows for dropped memories are stripped.
- Task_trace rows (the other type produced by this plugin) are
  never touched.
- A storage handle without ``list_memory_objects`` (e.g. a scenario
  harness mock) degrades to no-op instead of raising.
"""

from __future__ import annotations

import types
from typing import Any

from core.contracts import ProcessResult
from core.models import IndexEntry, MemoryObject
from semantic.agent_work_trace import AgentWorkTracePlugin
from semantic.operational_fact import OPERATIONAL_FACT_TYPE


CONTAINER = "git:example/repo"


def _op_fact_memory(
    *,
    family: str,
    role: str,
    scope_kind: str,
    scope_ref: str,
    artifact_normalized: str,
    id_suffix: str = "",
) -> MemoryObject:
    return MemoryObject(
        id=f"op-{family}-{role}-{artifact_normalized}-{id_suffix}",
        type=OPERATIONAL_FACT_TYPE,
        schema_id="operational_fact",
        schema_version="1",
        payload={
            "command_family": family,
            "artifact_role": role,
            "scope_kind": scope_kind,
            "scope_ref": scope_ref,
            "artifact_normalized": artifact_normalized,
        },
        container_ref=CONTAINER,
    )


def _task_trace_memory(id_suffix: str = "t") -> MemoryObject:
    return MemoryObject(
        id=f"tt-{id_suffix}",
        type="task_trace",
        schema_id="task_trace",
        schema_version="1",
        payload={"subject": "unrelated"},
        container_ref=CONTAINER,
    )


def _index_entry(target_id: str) -> IndexEntry:
    return IndexEntry(
        id=f"idx-{target_id}",
        target_kind="memory_object",
        target_id=target_id,
        index_type="lexical",
        text_view="text",
        text_view_name="default",
        provider_name="test",
        provider_version="1",
    )


class _FakeStorage:
    def __init__(self, existing: list[MemoryObject]):
        self._existing = existing
        self.calls: list[dict[str, Any]] = []

    def list_memory_objects(
        self,
        memory_types: list[str] | None = None,
        lifecycle: str | None = None,
        container_ref: str | None = None,
        subject_in: list[str] | None = None,
    ) -> list[MemoryObject]:
        self.calls.append({
            "memory_types": memory_types,
            "lifecycle": lifecycle,
            "container_ref": container_ref,
        })
        out = self._existing
        if memory_types is not None:
            out = [m for m in out if m.type in memory_types]
        if container_ref is not None:
            out = [m for m in out if m.container_ref == container_ref]
        return out


def _make_plugin() -> AgentWorkTracePlugin:
    # No LLM provider needed — reconcile_process_result never calls it.
    return AgentWorkTracePlugin(provider=None)  # type: ignore[arg-type]


class TestReconcileDropsExistingSlots:
    def test_existing_slot_dropped(self):
        existing = [
            _op_fact_memory(
                family="python", role="interpreter",
                scope_kind="machine_repo", scope_ref="repo@machine:h",
                artifact_normalized="C:/x/python.exe",
                id_suffix="prior",
            ),
        ]
        candidate = _op_fact_memory(
            family="python", role="interpreter",
            scope_kind="machine_repo", scope_ref="repo@machine:h",
            artifact_normalized="C:/x/python.exe",
            id_suffix="new",
        )
        result = ProcessResult(
            memory_objects=[candidate],
            relations=[],
            index_entries=[_index_entry(candidate.id)],
        )
        plugin = _make_plugin()
        out = plugin.reconcile_process_result(
            result,
            storage=_FakeStorage(existing),
            container_ref=CONTAINER,
            visibility="private",
        )
        assert out.memory_objects == []
        assert out.index_entries == []

    def test_fresh_slot_kept(self):
        existing = [
            _op_fact_memory(
                family="python", role="interpreter",
                scope_kind="machine_repo", scope_ref="repo@machine:h",
                artifact_normalized="C:/x/python.exe",
            ),
        ]
        candidate = _op_fact_memory(
            family="python", role="runner",  # different slot
            scope_kind="machine_repo", scope_ref="repo@machine:h",
            artifact_normalized="scripts/build.py",
            id_suffix="new",
        )
        result = ProcessResult(
            memory_objects=[candidate],
            relations=[],
            index_entries=[_index_entry(candidate.id)],
        )
        plugin = _make_plugin()
        out = plugin.reconcile_process_result(
            result,
            storage=_FakeStorage(existing),
            container_ref=CONTAINER,
            visibility="private",
        )
        assert [m.id for m in out.memory_objects] == [candidate.id]
        assert [idx.target_id for idx in out.index_entries] == [candidate.id]

    def test_intra_batch_duplicates_collapse(self):
        # Two candidates in the SAME ProcessResult with identical
        # slots: only the first survives.
        c1 = _op_fact_memory(
            family="python", role="interpreter",
            scope_kind="machine_repo", scope_ref="repo@machine:h",
            artifact_normalized="C:/x/python.exe",
            id_suffix="a",
        )
        c2 = _op_fact_memory(
            family="python", role="interpreter",
            scope_kind="machine_repo", scope_ref="repo@machine:h",
            artifact_normalized="C:/x/python.exe",
            id_suffix="b",
        )
        result = ProcessResult(
            memory_objects=[c1, c2],
            relations=[],
            index_entries=[_index_entry(c1.id), _index_entry(c2.id)],
        )
        plugin = _make_plugin()
        out = plugin.reconcile_process_result(
            result,
            storage=_FakeStorage([]),
            container_ref=CONTAINER,
            visibility="private",
        )
        assert [m.id for m in out.memory_objects] == [c1.id]
        assert [idx.target_id for idx in out.index_entries] == [c1.id]

    def test_task_trace_untouched(self):
        """The reconcile hook must only filter operational_fact.
        Task_trace rows and their indexes pass through unchanged.
        """
        existing = [
            _op_fact_memory(
                family="python", role="interpreter",
                scope_kind="machine_repo", scope_ref="repo@machine:h",
                artifact_normalized="C:/x/python.exe",
            ),
        ]
        tt = _task_trace_memory()
        of = _op_fact_memory(
            family="python", role="interpreter",
            scope_kind="machine_repo", scope_ref="repo@machine:h",
            artifact_normalized="C:/x/python.exe",
            id_suffix="new",
        )
        result = ProcessResult(
            memory_objects=[tt, of],
            relations=[],
            index_entries=[_index_entry(tt.id), _index_entry(of.id)],
        )
        plugin = _make_plugin()
        out = plugin.reconcile_process_result(
            result,
            storage=_FakeStorage(existing),
            container_ref=CONTAINER,
            visibility="private",
        )
        # Task_trace preserved; op_fact dropped
        assert [m.id for m in out.memory_objects] == [tt.id]
        assert set(idx.target_id for idx in out.index_entries) == {tt.id}

    def test_empty_op_fact_list_shortcircuits(self):
        # Fast path: if the batch has no op_fact rows, we don't call
        # storage at all.
        tt = _task_trace_memory()
        result = ProcessResult(
            memory_objects=[tt],
            relations=[],
            index_entries=[_index_entry(tt.id)],
        )
        fake = _FakeStorage([])
        plugin = _make_plugin()
        out = plugin.reconcile_process_result(
            result,
            storage=fake,
            container_ref=CONTAINER,
            visibility="private",
        )
        assert out is result  # unchanged
        assert fake.calls == []

    def test_storage_failure_falls_back_to_no_op(self):
        # If the storage handle doesn't support the query (harness mock,
        # future refactor), the hook logs and returns the unfiltered
        # result rather than blocking persistence.
        of = _op_fact_memory(
            family="python", role="interpreter",
            scope_kind="machine_repo", scope_ref="repo@machine:h",
            artifact_normalized="C:/x/python.exe",
        )
        result = ProcessResult(
            memory_objects=[of],
            relations=[],
            index_entries=[_index_entry(of.id)],
        )

        class _BadStorage:
            def list_memory_objects(self, *a, **kw):
                raise RuntimeError("not implemented in this harness")

        plugin = _make_plugin()
        out = plugin.reconcile_process_result(
            result,
            storage=_BadStorage(),
            container_ref=CONTAINER,
            visibility="private",
        )
        assert out is result

    def test_scope_kind_differs_no_dedup(self):
        # Same family/role/artifact but different scope_kind → distinct
        # slots. Regression pin so we don't over-dedup across scopes.
        existing = [
            _op_fact_memory(
                family="python", role="interpreter",
                scope_kind="machine_repo", scope_ref="repo@machine:h",
                artifact_normalized="C:/x/python.exe",
            ),
        ]
        candidate = _op_fact_memory(
            family="python", role="interpreter",
            scope_kind="machine",  # scope_kind differs
            scope_ref="machine:h",
            artifact_normalized="C:/x/python.exe",
            id_suffix="new",
        )
        result = ProcessResult(
            memory_objects=[candidate],
            relations=[],
            index_entries=[_index_entry(candidate.id)],
        )
        plugin = _make_plugin()
        out = plugin.reconcile_process_result(
            result,
            storage=_FakeStorage(existing),
            container_ref=CONTAINER,
            visibility="private",
        )
        assert [m.id for m in out.memory_objects] == [candidate.id]
