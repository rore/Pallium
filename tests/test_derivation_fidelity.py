"""Source-episode derivation coverage + fidelity eval (Pallium vNext).

Pure-function units (coverage classification/aggregation, fidelity compression +
N-sample aggregation + provenance) plus a runner test against a synthetic DB with a
stub judge. All fixtures are domain-neutral. No production code is exercised beyond
the read-only storage methods the eval reuses.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from core.models import (
    MemoryEnvelope,
    MemoryEnvelopeDerivation,
    MemoryEnvelopeScope,
    MemoryObject,
    Relation,
    SourceItem,
    utc_now,
)
from evals.derivation_fidelity import coverage as cov
from evals.derivation_fidelity import fidelity as fid
from evals.derivation_fidelity.coverage import ItemRecord, LinkedObject, aggregate_coverage
from evals.derivation_fidelity.runner import run_eval


# ---------------------------------------------------------------------------
# A. Coverage: pure classification + segmented aggregation
# ---------------------------------------------------------------------------

def _lo(mid, mtype, producer_kind, demoted=False):
    return LinkedObject(memory_object_id=mid, memory_type=mtype, producer_kind=producer_kind, demoted=demoted)


def test_classify_four_states_item_lens() -> None:
    # not processed
    r0 = ItemRecord("s0", "c", "t", processed=False)
    # processed, nothing linked
    r1 = ItemRecord("s1", "c", "t", processed=True, linked=())
    # processed, active item_extraction object
    r2 = ItemRecord("s2", "c", "t", processed=True, linked=(_lo("m2", "decision", "item_extraction"),))
    # processed, only-demoted item_extraction object
    r3 = ItemRecord("s3", "c", "t", processed=True, linked=(_lo("m3", "decision", "item_extraction", demoted=True),))
    out = aggregate_coverage([r0, r1, r2, r3])
    ie = out["item_extraction"]
    assert ie["counts"] == {
        cov.NOT_PROCESSED: 1, cov.PROCESSED_NOTHING: 1,
        cov.EXTRACTED: 1, cov.EXTRACTED_THEN_DEMOTED: 1,
    }
    # coverage rate = extracted / processed = 1/3
    assert ie["processed_denominator"] == 3
    assert abs(ie["coverage_rate"] - (1 / 3)) < 1e-9
    assert out["pending_items"] == 1


def test_mixed_active_and_demoted_is_extracted() -> None:
    rec = ItemRecord("s", "c", "t", processed=True, linked=(
        _lo("a", "decision", "item_extraction", demoted=True),
        _lo("b", "decision", "item_extraction", demoted=False),
    ))
    out = aggregate_coverage([rec])
    assert out["item_extraction"]["counts"][cov.EXTRACTED] == 1


def test_thread_producers_measured_at_thread_granularity_not_inflating_item_lens() -> None:
    # One thread, 3 processed items; a single thread_summary linked to ALL of them.
    summary = _lo("sum", "thread_summary", "thread_aggregation")
    recs = [ItemRecord(f"s{i}", "c", "t1", processed=True, linked=(summary,)) for i in range(3)]
    out = aggregate_coverage(recs)
    # Item-extraction lens sees NO item_extraction objects → all processed_nothing
    # (the thread_summary must not count as per-item coverage).
    assert out["item_extraction"]["counts"][cov.PROCESSED_NOTHING] == 3
    assert out["item_extraction"]["counts"][cov.EXTRACTED] == 0
    # Thread lens: exactly one thread, extracted, deduped to one object.
    ta = out["thread_aggregation"]
    assert ta["processed_denominator"] == 1
    assert ta["counts"][cov.EXTRACTED] == 1
    assert ta["coverage_rate"] == 1.0


def test_thread_with_no_processed_item_excluded_from_thread_denominator() -> None:
    recs = [ItemRecord("s0", "c", "t1", processed=False, linked=())]
    out = aggregate_coverage(recs)
    assert out["thread_aggregation"]["processed_denominator"] == 0
    assert out["thread_aggregation"]["coverage_rate"] is None


def test_coverage_empty_data_safe() -> None:
    out = aggregate_coverage([])
    assert out["sampled_items"] == 0
    assert out["item_extraction"]["coverage_rate"] is None
    assert out["thread_aggregation"]["coverage_rate"] is None


def test_no_blended_overall_rate_key() -> None:
    out = aggregate_coverage([ItemRecord("s", "c", "t", processed=True, linked=())])
    # Guard: the report must NOT expose a single blended derivation coverage number.
    assert "coverage_rate" not in out
    assert "overall" not in out


# ---------------------------------------------------------------------------
# B. Fidelity: compression, aggregation, parsing, prompt, provenance
# ---------------------------------------------------------------------------

def test_compression_ratio_deterministic_and_zero_safe() -> None:
    assert fid.compression_ratio(1000, 250) == 4.0
    assert fid.compression_ratio(100, 0) is None


def test_aggregate_fidelity_majority_and_median() -> None:
    samples = [
        fid.FidelitySample(completeness_score=0.8, unsupported_by_context=True, drift=False),
        fid.FidelitySample(completeness_score=0.6, unsupported_by_context=True, drift=False),
        fid.FidelitySample(completeness_score=0.4, unsupported_by_context=False, drift=True),
    ]
    agg = fid.aggregate_fidelity(samples)
    assert agg["n_samples"] == 3
    assert agg["unsupported_by_context"] is True  # 2/3 majority
    assert agg["drift"] is False  # 1/3, no majority
    assert abs(agg["completeness_median"] - 0.6) < 1e-9
    assert abs(agg["completeness_mean"] - 0.6) < 1e-9


def test_aggregate_fidelity_tie_is_false_and_empty_safe() -> None:
    tie = [
        fid.FidelitySample(None, True, None),
        fid.FidelitySample(None, False, None),
    ]
    assert fid.aggregate_fidelity(tie)["unsupported_by_context"] is False
    empty = fid.aggregate_fidelity([])
    assert empty["n_samples"] == 0
    assert empty["completeness_mean"] is None
    assert empty["unsupported_by_context"] is None


def test_parse_fidelity_tolerates_junk_and_clamps() -> None:
    assert fid.parse_fidelity_response(None).parse_ok is False
    s = fid.parse_fidelity_response({"completeness_score": "1.7", "unsupported_by_context": "yes", "drift": "no"})
    assert s.completeness_score == 1.0  # clamped
    assert s.unsupported_by_context is True
    assert s.drift is False


def test_build_prompt_distinct_per_sample_ordinal() -> None:
    p0 = fid.build_fidelity_prompt(linked_turns=["a"], context_turns=[], derived_text="d", sample_ordinal=0)
    p1 = fid.build_fidelity_prompt(linked_turns=["a"], context_turns=[], derived_text="d", sample_ordinal=1)
    assert p0 != p1  # distinct → distinct CachedLLMProvider cache key


def test_extract_derivation_version() -> None:
    env = MemoryEnvelope(
        schema_id="s", schema_version="v1", kind="finding",
        scope=MemoryEnvelopeScope(),
        derivation=MemoryEnvelopeDerivation(
            producer_kind="item_extraction", producer_schema_id="ps",
            producer_schema_version="pv", prompt_variant="strict_v1", model_role="write_extraction",
        ),
    )
    mem = MemoryObject(type="decision", schema_id="s", schema_version="v1", payload={}, envelope=env)
    v = fid.extract_derivation_version(mem)
    assert v["producer_kind"] == "item_extraction"
    assert v["prompt_variant"] == "strict_v1"
    assert v["model_role"] == "write_extraction"
    assert v["memory_type"] == "decision"


# ---------------------------------------------------------------------------
# C. Runner: synthetic DB + stub judge (independent-draw + seam separation)
# ---------------------------------------------------------------------------

class _CountingJudge:
    """Deterministic stub judge; records how many times it was called and echoes
    the sample ordinal so we can prove N independent draws (not one cached repeat)."""

    def __init__(self) -> None:
        self.calls = 0
        self.prompts: list[str] = []

    def generate_json(self, *, system_prompt, user_prompt, schema_description):
        from providers.llm.base import LLMJsonResponse
        self.calls += 1
        self.prompts.append(user_prompt)
        return LLMJsonResponse(
            raw_text="{}",
            parsed_json={"completeness_score": 0.7, "unsupported_by_context": False, "drift": False},
            metadata=None,
        )


def _env(producer_kind: str) -> MemoryEnvelope:
    # The envelope's own schema_id/version MUST be the canonical constants or the
    # storage codec drops the envelope on read (real objects use these).
    return MemoryEnvelope(
        schema_id="core.memory_envelope", schema_version="v1", kind="finding",
        scope=MemoryEnvelopeScope(),
        derivation=MemoryEnvelopeDerivation(
            producer_kind=producer_kind, producer_schema_id="ps", producer_schema_version="pv",
        ),
    )


@pytest.fixture()
def synthetic_db(tmp_path: Path):
    from storage.sqlite import SQLiteStorageProvider
    db = tmp_path / "deriv.db"
    storage = SQLiteStorageProvider(database_url=f"sqlite:///{db}")

    def add_item(sid, thread, *, processed, content):
        item = SourceItem(
            source_type="chat_message", source_id=sid, content_type="text/plain",
            content=content, container_ref="c", thread_ref=thread, visibility="public",
            processing_status=("completed" if processed else "pending"),
            processing_completed_at=(utc_now() if processed else None),
        )
        storage.create_source_item(item)
        return item.id

    def add_mem(mtype, producer_kind, payload, *, soft_deleted=False, lifecycle="active"):
        mem = MemoryObject(
            type=mtype, schema_id="sch", schema_version="v1", payload=payload,
            container_ref="c", visibility="public", envelope=_env(producer_kind),
            is_soft_deleted=soft_deleted, lifecycle=lifecycle,
        )
        storage.create_memory_object(mem)
        return mem.id

    def link(mem_id, source_item_id):
        storage.create_relation(Relation(
            from_kind="memory_object", from_id=mem_id, relation_type="supported_by",
            to_kind="source_item", to_id=source_item_id,
        ))

    # Thread t1: three processed turns; a thread_summary linked to ALL; one turn
    # also has an item_extraction decision; one processed turn produces nothing.
    t1 = [add_item(f"t1-{i}", "t1", processed=True, content=f"turn {i} about the reservation ledger") for i in range(3)]
    summary = add_mem("thread_summary", "thread_aggregation", {"summary": "ledger work summary"})
    for sid in t1:
        link(summary, sid)
    dec = add_mem("decision", "item_extraction", {"decision": "holds must be idempotent"})
    link(dec, t1[0])

    # Thread t2: one processed turn whose only extraction was soft-deleted (demoted),
    # and one pending turn.
    t2a = add_item("t2-a", "t2", processed=True, content="we chose a unique index")
    add_item("t2-b", "t2", processed=False, content="pending unprocessed turn")
    dead = add_mem("decision", "item_extraction", {"decision": "old approach"})
    link(dead, t2a)
    storage.soft_delete_memory(dead, reason="test tombstone")

    return {"storage": storage, "db": str(db), "t1": t1, "t2a": t2a}


def test_runner_segments_seams_and_makes_independent_draws(synthetic_db) -> None:
    judge = _CountingJudge()
    report = run_eval(
        db_path=synthetic_db["db"], storage=synthetic_db["storage"], judge_provider=judge,
        report_time_model="test-model", limit=0, seed=17, container_ref=None, thread_ref=None,
        judge_samples=3, fidelity_limit=0, max_context=8,
    )
    coverage = report["coverage"]
    # Seam separation: two lenses, no blended number.
    assert set(coverage) >= {"item_extraction", "thread_aggregation", "pending_items", "sampled_items"}
    assert "coverage_rate" not in coverage

    ie = coverage["item_extraction"]
    # 4 processed items (3 in t1 + t2a) + 1 pending. Item-extraction:
    #   t1[0] extracted (decision), t1[1]/t1[2] processed_nothing, t2a extracted_then_demoted.
    assert coverage["pending_items"] == 1
    assert ie["counts"][cov.EXTRACTED] == 1
    assert ie["counts"][cov.EXTRACTED_THEN_DEMOTED] == 1
    assert ie["counts"][cov.PROCESSED_NOTHING] == 2

    ta = coverage["thread_aggregation"]
    # Two threads have >=1 processed item; only t1 has a thread_summary.
    assert ta["processed_denominator"] == 2
    assert ta["counts"][cov.EXTRACTED] == 1
    assert ta["counts"][cov.PROCESSED_NOTHING] == 1

    # Fidelity: active objects only (summary + t1 decision; the soft-deleted one excluded).
    fobjs = report["fidelity"]["objects"]
    judged_ids = {o["memory_object_id"] for o in fobjs}
    assert len(judged_ids) == 2  # deduped; soft-deleted excluded
    # Independent draws: 2 objects x 3 samples = 6 judge calls (NOT 2 cached repeats).
    assert judge.calls == 6
    for o in fobjs:
        assert o["fidelity"]["n_samples"] == 3
        assert o["version"]["producer_kind"] in {"item_extraction", "thread_aggregation"}
        assert o["compression_ratio"] is not None


def test_runner_coverage_only_when_no_judge(synthetic_db) -> None:
    report = run_eval(
        db_path=synthetic_db["db"], storage=synthetic_db["storage"], judge_provider=None,
        report_time_model=None, limit=0, seed=17, container_ref=None, thread_ref=None,
        judge_samples=3, fidelity_limit=0, max_context=8,
    )
    assert report["coverage"]["sampled_items"] == 5
    for o in report["fidelity"]["objects"]:
        assert o["fidelity"] is None  # judge skipped, coverage still computed


def test_is_processed_counts_terminal_outcomes() -> None:
    from evals.derivation_fidelity.runner import is_processed
    # Terminal outcomes are "processed" — a FAILED item that produced nothing must
    # stay in the coverage denominator (not be dropped as pending → inflating rate).
    assert is_processed("completed", None) is True
    assert is_processed("failed", None) is True
    assert is_processed("skipped", None) is True
    # completed-timestamp set even with a non-terminal status label → processed.
    assert is_processed("processing", utc_now()) is True
    # genuinely in-flight → not processed (excluded from denominator, counted pending).
    assert is_processed("pending", None) is False
    assert is_processed(None, None) is False


def test_terminally_failed_item_is_processed_nothing_not_pending(tmp_path) -> None:
    from storage.sqlite import SQLiteStorageProvider
    db = tmp_path / "failed.db"
    storage = SQLiteStorageProvider(database_url=f"sqlite:///{db}")
    # One terminally-FAILED item that produced no derived object.
    storage.create_source_item(SourceItem(
        source_type="chat_message", source_id="f1", content_type="text/plain",
        content="extraction crashed here", container_ref="c", thread_ref="tf",
        visibility="public", processing_status="failed", processing_completed_at=utc_now(),
    ))
    report = run_eval(
        db_path=str(db), storage=storage, judge_provider=None, report_time_model=None,
        limit=0, seed=1, container_ref=None, thread_ref=None,
        judge_samples=1, fidelity_limit=0, max_context=4,
    )
    ie = report["coverage"]["item_extraction"]
    assert report["coverage"]["pending_items"] == 0  # NOT dropped as pending
    assert ie["counts"][cov.PROCESSED_NOTHING] == 1  # in the denominator
    assert ie["processed_denominator"] == 1
    assert ie["coverage_rate"] == 0.0  # honest: attempted, produced nothing


def test_cached_provider_gets_n_independent_misses(synthetic_db, tmp_path) -> None:
    # Criterion 3, literal: N samples under a real CachedLLMProvider must be N cache
    # MISSES (independent draws), not one miss + repeats.
    from providers.llm.cached import CachedLLMProvider
    judge = _CountingJudge()
    cached = CachedLLMProvider(judge, tmp_path / "jcache", model_tag="test")
    run_eval(
        db_path=synthetic_db["db"], storage=synthetic_db["storage"], judge_provider=cached,
        report_time_model="m", limit=0, seed=17, container_ref=None, thread_ref=None,
        judge_samples=3, fidelity_limit=0, max_context=8,
    )
    # 2 active objects x 3 samples = 6 distinct prompts -> 6 misses, 0 hits.
    assert judge.calls == 6
    assert cached.stats == {"hits": 0, "misses": 6}
