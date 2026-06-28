"""Tests for the resolver's container-scoped similarity branch
(2026-06-28 per-item near-dup fix) and regression guards for the
backfill / eval bucket-key code-review findings (P1, P2).

See:
  - storage/sqlite_queue.py _SIMILARITY_ELIGIBLE_TYPES branch
  - scripts/backfill_thread_near_dups.py _plan bucket key
  - evals/injection_policy_2026_06/near_dup_measure.py simulator/noise
  - docs/specs/2026-06-28-thread-near-dup-supersession.md

The resolver branch catches paraphrases that:
  - the thread writer's same-thread similarity loop missed (per-item),
  - share container_ref with the new record,
  - have canonical_key SequenceMatcher.ratio >= 0.85,
  - pass visibility_matches_exact.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.config import AppConfig
from app.main import create_app
from core.contracts import ProcessResult, SupersessionHint
from core.models import MemoryObject
from semantic.common import normalize_for_index
from storage.sqlite_schema import MemoryObjectRecord
from storage.vector_index import VectorIndexConfig
from tests.config_helpers import DEMO_SEMANTIC_PACKAGES


# ---------------------------------------------------------------------------
# Resolver: container-scoped SequenceMatcher branch
# ---------------------------------------------------------------------------


def _config(db_url: str) -> AppConfig:
    return AppConfig(
        storage_backend="sqlite",
        sqlite_url=db_url,
        default_use_case="demo_agent_memory",
        semantic_packages=DEMO_SEMANTIC_PACKAGES,
        vector_index=VectorIndexConfig(enabled=False),
    )


def _make_memory(
    *,
    memory_type: str,
    canonical_key: str,
    container_ref: str,
    visibility: str = "private",
    source_id: str = "cc-test",
    source_type: str = "claude-code",
    extra_payload: dict | None = None,
) -> MemoryObject:
    payload = {
        "canonical_key": canonical_key,
        "source_type": source_type,
        "source_id": source_id,
    }
    if memory_type == "decision":
        payload["decision"] = canonical_key
    elif memory_type == "investigation_outcome":
        payload["investigation_outcome"] = canonical_key
    if extra_payload:
        payload.update(extra_payload)
    return MemoryObject(
        type=memory_type,
        schema_id=f"test.{memory_type}",
        schema_version="v1",
        payload=payload,
        container_ref=container_ref,
        visibility=visibility,
    )


def _persist(storage, mo: MemoryObject) -> None:
    storage.create_memory_object(mo)


def _lifecycle_of(storage, memory_object_id: str) -> str:
    with storage._session_factory() as session:
        record = session.get(MemoryObjectRecord, memory_object_id)
        return record.lifecycle


class TestResolverSimilarityBranch:
    """The new branch in _resolve_supersession_pairs_in_session triggers
    when a hint has thread_ref=None (container-scoped), memory_type is
    decision or investigation_outcome, and an existing record's
    canonical_key is similar above 0.85.
    """

    def test_paraphrase_supersession_at_container_scope(self, test_db_url: str) -> None:
        """Per-item path: an existing decision is superseded when a new
        decision with similar canonical_key is persisted with a hint."""
        app = create_app(_config(test_db_url))
        service = app.state.pallium_service
        storage = service._storage

        old_key = normalize_for_index(
            "Pallium session is waiting for user approval but the context-graph "
            "session is not in the same blocking state"
        )
        new_key = normalize_for_index(
            "The Pallium session is waiting for approval while the context-graph "
            "session is not in the same blocking state"
        )
        assert old_key != new_key  # genuine paraphrase, not byte-equal

        old = _make_memory(
            memory_type="investigation_outcome",
            canonical_key=old_key,
            container_ref="sim-test:c",
            source_id="cc-old",
        )
        _persist(storage, old)

        new = _make_memory(
            memory_type="investigation_outcome",
            canonical_key=new_key,
            container_ref="sim-test:c",
            source_id="cc-new",
        )
        hint = SupersessionHint(
            replacement_memory_id=new.id,
            memory_type=new.type,
            canonical_key=new_key,
            container_ref="sim-test:c",
            thread_ref=None,
            visibility="private",
        )
        storage.commit_process_result(result=
            ProcessResult(memory_objects=[new], relations=[], index_entries=[], supersession_hints=[hint])
        )

        assert _lifecycle_of(storage, old.id) == "superseded"
        assert _lifecycle_of(storage, new.id) == "active"

    def test_distinct_findings_below_threshold_stay_active(self, test_db_url: str) -> None:
        """Two genuinely distinct decisions stay separate (sim < 0.85)."""
        app = create_app(_config(test_db_url))
        service = app.state.pallium_service
        storage = service._storage

        old_key = normalize_for_index(
            "Switch the order-update channel to gRPC streaming once the latency "
            "regression in HTTP polling exceeds the agreed budget on weekday peaks."
        )
        new_key = normalize_for_index(
            "Adopt Postgres logical replication for the catalog service after "
            "benchmarking against the legacy MySQL deployment over the holiday window."
        )

        old = _make_memory(
            memory_type="decision",
            canonical_key=old_key,
            container_ref="sim-test-distinct:c",
        )
        _persist(storage, old)

        new = _make_memory(
            memory_type="decision",
            canonical_key=new_key,
            container_ref="sim-test-distinct:c",
        )
        hint = SupersessionHint(
            replacement_memory_id=new.id,
            memory_type=new.type,
            canonical_key=new_key,
            container_ref="sim-test-distinct:c",
            thread_ref=None,
            visibility="private",
        )
        storage.commit_process_result(result=
            ProcessResult(memory_objects=[new], relations=[], index_entries=[], supersession_hints=[hint])
        )

        assert _lifecycle_of(storage, old.id) == "active", (
            "distinct decisions must stay separate below the 0.85 threshold"
        )
        assert _lifecycle_of(storage, new.id) == "active"

    def test_cross_container_never_superseded(self, test_db_url: str) -> None:
        """Even with identical canonical_keys, two different containers
        must not collapse — preserves f9af592's intentional cross-
        container left-alone property."""
        app = create_app(_config(test_db_url))
        service = app.state.pallium_service
        storage = service._storage

        shared_key = normalize_for_index(
            "Some specific investigation finding that two unrelated containers might share."
        )
        old = _make_memory(
            memory_type="investigation_outcome",
            canonical_key=shared_key,
            container_ref="container-a",
        )
        _persist(storage, old)

        new = _make_memory(
            memory_type="investigation_outcome",
            canonical_key=shared_key,  # identical
            container_ref="container-b",
        )
        hint = SupersessionHint(
            replacement_memory_id=new.id,
            memory_type=new.type,
            canonical_key=shared_key,
            container_ref="container-b",
            thread_ref=None,
            visibility="private",
        )
        storage.commit_process_result(result=
            ProcessResult(memory_objects=[new], relations=[], index_entries=[], supersession_hints=[hint])
        )

        assert _lifecycle_of(storage, old.id) == "active", (
            "cross-container records must never be superseded"
        )
        assert _lifecycle_of(storage, new.id) == "active"

    def test_visibility_boundary_never_crossed(self, test_db_url: str) -> None:
        """A private record cannot supersede a public one (or vice versa)
        even with high similarity — visibility_matches_exact guards the
        container-scoped branch."""
        app = create_app(_config(test_db_url))
        service = app.state.pallium_service
        storage = service._storage

        old_key = normalize_for_index(
            "Some specific investigation finding A that appears in both visibility buckets."
        )
        new_key = normalize_for_index(
            "Some specific investigation finding B that appears in both visibility buckets."
        )
        # sim > 0.85 between these
        old = _make_memory(
            memory_type="investigation_outcome",
            canonical_key=old_key,
            container_ref="vis-test:c",
            visibility="public",
        )
        _persist(storage, old)

        new = _make_memory(
            memory_type="investigation_outcome",
            canonical_key=new_key,
            container_ref="vis-test:c",
            visibility="private",  # mismatched
        )
        hint = SupersessionHint(
            replacement_memory_id=new.id,
            memory_type=new.type,
            canonical_key=new_key,
            container_ref="vis-test:c",
            thread_ref=None,
            visibility="private",
        )
        storage.commit_process_result(result=
            ProcessResult(memory_objects=[new], relations=[], index_entries=[], supersession_hints=[hint])
        )

        assert _lifecycle_of(storage, old.id) == "active", (
            "visibility boundary must never be crossed"
        )
        assert _lifecycle_of(storage, new.id) == "active"

    def test_constraint_memory_unaffected_by_similarity_branch(
        self, test_db_url: str,
    ) -> None:
        """Constraints have their own Jaccard branch and are NOT in
        _SIMILARITY_ELIGIBLE_TYPES. Two near-paraphrase constraints with
        Jaccard < 0.5 must stay separate (the similarity branch must
        not fire for them)."""
        app = create_app(_config(test_db_url))
        service = app.state.pallium_service
        storage = service._storage

        # Two constraints with high character overlap but mostly-disjoint
        # token sets (Jaccard < 0.5).
        old_key = "do not use eval in code paths handled by middleware"
        new_key = "do not call exec from middleware request paths"
        old = _make_memory(
            memory_type="constraint_memory",
            canonical_key=old_key,
            container_ref="constraint-test:c",
            extra_payload={"constraint_text": old_key},
        )
        _persist(storage, old)

        new = _make_memory(
            memory_type="constraint_memory",
            canonical_key=new_key,
            container_ref="constraint-test:c",
            extra_payload={"constraint_text": new_key},
        )
        hint = SupersessionHint(
            replacement_memory_id=new.id,
            memory_type=new.type,
            canonical_key=new_key,
            container_ref="constraint-test:c",
            thread_ref=None,
            visibility="private",
        )
        storage.commit_process_result(result=
            ProcessResult(memory_objects=[new], relations=[], index_entries=[], supersession_hints=[hint])
        )

        # Constraints not in _SIMILARITY_ELIGIBLE_TYPES, Jaccard not high
        # enough → both stay active.
        assert _lifecycle_of(storage, old.id) == "active"
        assert _lifecycle_of(storage, new.id) == "active"


# ---------------------------------------------------------------------------
# Backfill _plan — P1 regression: container_ref must scope the bucket
# ---------------------------------------------------------------------------


def _candidate(
    *,
    cid: str,
    container_ref: str,
    source_id: str,
    canonical_key: str,
    memory_type: str = "investigation_outcome",
    created_at: datetime,
):
    from scripts.backfill_thread_near_dups import Candidate
    return Candidate(
        id=cid,
        type=memory_type,
        source_id=source_id,
        container_ref=container_ref,
        canonical_key=canonical_key,
        created_at=created_at,
    )


class TestBackfillBucketIncludesContainer:
    """P1 (code review 2026-06-28): two containers sharing the same
    source_id must never plan a cross-container supersession."""

    def test_two_containers_same_source_id_stay_separate(self) -> None:
        from scripts.backfill_thread_near_dups import _plan

        # Same canonical_key (sim = 1.0), same source_id ('shared-tid'),
        # different container_ref. If the bucket key omitted container_ref,
        # the second candidate would be planned to supersede the first.
        t0 = datetime(2026, 6, 28, 12, 0, 0, tzinfo=UTC)
        shared_key = normalize_for_index(
            "A specific finding that both containers happen to share verbatim."
        )
        a = _candidate(
            cid="a",
            container_ref="container-A",
            source_id="shared-tid",
            canonical_key=shared_key,
            created_at=t0,
        )
        b = _candidate(
            cid="b",
            container_ref="container-B",
            source_id="shared-tid",
            canonical_key=shared_key,
            created_at=t0 + timedelta(minutes=1),
        )
        plan = _plan([a, b], threshold=0.85)
        assert plan == [], (
            f"backfill must not plan cross-container supersessions; got {plan!r}"
        )

    def test_same_container_same_source_id_still_collapses(self) -> None:
        """Sanity: same-container same-source paraphrase still plans the
        expected supersession (i.e. the fix didn't accidentally over-
        narrow the bucket)."""
        from scripts.backfill_thread_near_dups import _plan

        t0 = datetime(2026, 6, 28, 12, 0, 0, tzinfo=UTC)
        ck_old = normalize_for_index(
            "Pallium session is waiting for user approval but the other is not."
        )
        ck_new = normalize_for_index(
            "The Pallium session is waiting for approval while the other is not."
        )
        a = _candidate(
            cid="a", container_ref="same-c", source_id="same-tid",
            canonical_key=ck_old, created_at=t0,
        )
        b = _candidate(
            cid="b", container_ref="same-c", source_id="same-tid",
            canonical_key=ck_new, created_at=t0 + timedelta(minutes=1),
        )
        plan = _plan([a, b], threshold=0.85)
        assert len(plan) == 1
        prior, winner, _sim = plan[0]
        assert prior.id == "a" and winner.id == "b"


class TestBackfillPerItemPlanner:
    """``_plan_per_item`` buckets by ``(container_ref, type)`` only —
    per-item rows have a unique source_id per row (each Claude/Codex
    item is its own ``cc-<hash>``), so source-scoped bucketing would
    never find paraphrases.
    """

    def test_per_item_paraphrase_same_container_collapses(self) -> None:
        from scripts.backfill_thread_near_dups import _plan_per_item

        t0 = datetime(2026, 6, 28, 12, 0, 0, tzinfo=UTC)
        ck_old = normalize_for_index(
            "Pallium session is waiting for user approval but the other is not."
        )
        ck_new = normalize_for_index(
            "The Pallium session is waiting for approval while the other is not."
        )
        a = _candidate(
            cid="a", container_ref="cont", source_id="cc-aaa",
            canonical_key=ck_old, created_at=t0,
        )
        b = _candidate(
            cid="b", container_ref="cont", source_id="cc-bbb",
            canonical_key=ck_new, created_at=t0 + timedelta(minutes=1),
        )
        plan = _plan_per_item([a, b], threshold=0.85)
        assert len(plan) == 1
        prior, winner, _sim = plan[0]
        assert prior.id == "a" and winner.id == "b"

    def test_per_item_cross_container_never_collapses(self) -> None:
        from scripts.backfill_thread_near_dups import _plan_per_item

        t0 = datetime(2026, 6, 28, 12, 0, 0, tzinfo=UTC)
        ck = normalize_for_index("Identical finding both containers share.")
        a = _candidate(
            cid="a", container_ref="cont-A", source_id="cc-aaa",
            canonical_key=ck, created_at=t0,
        )
        b = _candidate(
            cid="b", container_ref="cont-B", source_id="cc-bbb",
            canonical_key=ck, created_at=t0 + timedelta(minutes=1),
        )
        plan = _plan_per_item([a, b], threshold=0.85)
        assert plan == []

    def test_per_item_distinct_findings_stay_separate(self) -> None:
        from scripts.backfill_thread_near_dups import _plan_per_item

        t0 = datetime(2026, 6, 28, 12, 0, 0, tzinfo=UTC)
        a = _candidate(
            cid="a", container_ref="cont", source_id="cc-aaa",
            canonical_key=normalize_for_index(
                "Switch the order-update channel to gRPC streaming."
            ),
            created_at=t0,
        )
        b = _candidate(
            cid="b", container_ref="cont", source_id="cc-bbb",
            canonical_key=normalize_for_index(
                "Adopt Postgres logical replication for the catalog service."
            ),
            created_at=t0 + timedelta(minutes=1),
        )
        plan = _plan_per_item([a, b], threshold=0.85)
        assert plan == []


# ---------------------------------------------------------------------------
# Eval simulator/noise — P2 regression: container_ref in bucket key
# ---------------------------------------------------------------------------


def _row(
    *,
    rid: str,
    container_ref: str,
    source_id: str,
    canonical_key: str,
    memory_type: str = "investigation_outcome",
    created_at: str = "2026-06-28 12:00:00",
    lifecycle: str = "active",
):
    from evals.injection_policy_2026_06.near_dup_measure import Row
    return Row(
        id=rid,
        type=memory_type,
        lifecycle=lifecycle,
        container_ref=container_ref,
        source_id=source_id,
        norm_text=canonical_key,
        canonical_key=canonical_key,
        created_at=created_at,
    )


class TestEvalBucketIncludesContainer:
    """P2 (code review 2026-06-28): eval simulator/noise must use the
    same (container_ref, source_id, type) bucket as the backfill."""

    def test_simulator_does_not_demote_cross_container(self) -> None:
        from evals.injection_policy_2026_06.near_dup_measure import _simulate_fix_c

        ck = normalize_for_index("A specific finding both containers happen to share.")
        rows = [
            _row(rid="a", container_ref="cont-A", source_id="shared", canonical_key=ck,
                 created_at="2026-06-28 12:00:00"),
            _row(rid="b", container_ref="cont-B", source_id="shared", canonical_key=ck,
                 created_at="2026-06-28 12:05:00"),
        ]
        sim = _simulate_fix_c(rows, 0.85)
        assert sim["demoted"] == 0, (
            f"simulator must bucket by container_ref; got demoted={sim['demoted']}"
        )
        assert sim["kept"] == 2

    def test_noise_does_not_count_cross_container_pairs(self) -> None:
        from evals.injection_policy_2026_06.near_dup_measure import _per_source_top_noise

        ck = normalize_for_index("A specific finding both containers happen to share.")
        rows = [
            _row(rid="a", container_ref="cont-A", source_id="shared", canonical_key=ck,
                 created_at="2026-06-28 12:00:00"),
            _row(rid="b", container_ref="cont-B", source_id="shared", canonical_key=ck,
                 created_at="2026-06-28 12:05:00"),
        ]
        # With container_ref in the bucket key, neither (cont-A, shared)
        # nor (cont-B, shared) has >= 2 rows, so the noise list is empty.
        noisy = _per_source_top_noise(rows, threshold=0.85, top_n=10)
        assert noisy == [], f"noise must scope by container_ref; got {noisy!r}"

    def test_same_container_same_source_still_surfaces(self) -> None:
        """Sanity: same-container same-source dup IS still surfaced."""
        from evals.injection_policy_2026_06.near_dup_measure import (
            _simulate_fix_c,
            _per_source_top_noise,
        )

        ck = normalize_for_index("A specific same-container finding.")
        rows = [
            _row(rid="a", container_ref="same-c", source_id="same-s", canonical_key=ck,
                 created_at="2026-06-28 12:00:00"),
            _row(rid="b", container_ref="same-c", source_id="same-s", canonical_key=ck,
                 created_at="2026-06-28 12:05:00"),
        ]
        sim = _simulate_fix_c(rows, 0.85)
        assert sim["demoted"] == 1
        noisy = _per_source_top_noise(rows, threshold=0.85, top_n=10)
        assert len(noisy) == 1
        assert noisy[0]["source_id"] == "same-s"
        assert noisy[0]["container_ref"] == "same-c"
