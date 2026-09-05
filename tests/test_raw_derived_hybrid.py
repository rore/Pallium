"""RAW / DERIVED / HYBRID retrieval + representation eval (Pallium vNext).

Pure-function units (arm purity / RAW-source-only; evidence-link candidate-recovery
RAW-only/DERIVED-only/both/neither; equal-token-budget item-boundary truncation incl.
the RAW-many-small vs DERIVED-few-dense asymmetry; empty safety; representation
aggregation incl. an N-independent-draw-under-real-CachedLLMProvider check; provenance)
plus a runner test against a synthetic DB with a counting stub judge. All fixtures are
domain-neutral. No production code is exercised beyond the read-only storage +
lexical-retrieval methods the eval reuses.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from core.models import (
    IndexEntry,
    MemoryEnvelope,
    MemoryEnvelopeDerivation,
    MemoryEnvelopeScope,
    MemoryObject,
    Relation,
    SourceItem,
    utc_now,
)
from evals.raw_derived_hybrid import arms
from evals.raw_derived_hybrid import represent as rep
from evals.raw_derived_hybrid.arms import (
    DERIVED,
    HYBRID,
    KIND_MEMORY,
    KIND_SOURCE,
    RAW,
    Candidate,
    DerivedObjectEvidence,
    equal_token_budget,
    evidence_link_recovery,
    partition_candidates,
)
from evals.raw_derived_hybrid.runner import (
    QueryRow,
    count_lookup_population,
    load_query_rows,
    run_eval,
)


# ---------------------------------------------------------------------------
# A. Arm assembly + RAW purity
# ---------------------------------------------------------------------------

def _src(cid, rank=1, score=1.0):
    return Candidate(kind=KIND_SOURCE, id=cid, rank=rank, score=score)


def _mem(cid, rank=1, score=1.0):
    return Candidate(kind=KIND_MEMORY, id=cid, rank=rank, score=score)


def test_raw_arm_must_be_source_only() -> None:
    ok = partition_candidates(RAW, [_src("s1", 1), _src("s2", 2)])
    assert ok.target_kind == "source_item"
    assert ok.ids_of_kind(KIND_MEMORY) == set()
    assert ok.ids_of_kind(KIND_SOURCE) == {"s1", "s2"}
    # A memory object leaking into RAW is a hard error, not a silent confound.
    with pytest.raises(ValueError, match="purity"):
        partition_candidates(RAW, [_src("s1", 1), _mem("m1", 2)])


def test_derived_and_hybrid_target_kinds() -> None:
    d = partition_candidates(DERIVED, [_mem("m1", 1)])
    h = partition_candidates(HYBRID, [_src("s1", 1), _mem("m1", 2)])
    assert d.target_kind == "memory_object"
    assert h.target_kind is None  # mixed
    assert h.ids_of_kind(KIND_SOURCE) == {"s1"}
    assert h.ids_of_kind(KIND_MEMORY) == {"m1"}


def test_unknown_arm_name_rejected() -> None:
    with pytest.raises(ValueError, match="unknown arm"):
        partition_candidates("NOPE", [])


# ---------------------------------------------------------------------------
# B. Evidence-link candidate-recovery (objective, symmetric)
# ---------------------------------------------------------------------------

def test_recovery_both_raw_only_derived_only_neither() -> None:
    raw_source_ids = {"s1", "s2"}
    objs = [
        # linked source s1 in RAW, object in DERIVED -> both
        DerivedObjectEvidence("m_both", ("s1",), entered_derived_arm=True),
        # linked source s2 in RAW, object NOT in DERIVED -> raw_only
        DerivedObjectEvidence("m_raw", ("s2",), entered_derived_arm=False),
        # linked source s9 NOT in RAW, object in DERIVED -> derived_only
        DerivedObjectEvidence("m_der", ("s9",), entered_derived_arm=True),
        # linked source s8 NOT in RAW, object NOT in DERIVED -> neither
        DerivedObjectEvidence("m_none", ("s8",), entered_derived_arm=False),
    ]
    out = evidence_link_recovery(raw_source_ids, objs)
    assert out["seam"] == "candidate_recovery"
    assert out["counts"] == {"both": 1, "raw_only": 1, "derived_only": 1, "neither": 1}
    assert out["n_objects"] == 4
    assert out["n_with_evidence"] == 4
    by_id = {o["memory_object_id"]: o["label"] for o in out["objects"]}
    assert by_id == {
        "m_both": "both", "m_raw": "raw_only",
        "m_der": "derived_only", "m_none": "neither",
    }


def test_recovery_object_with_no_evidence_and_empty_safe() -> None:
    # An object with no linked source turns is segregated (RAW recovery undefined),
    # NOT counted toward the four RAW-vs-DERIVED labels.
    out = evidence_link_recovery({"s1"}, [DerivedObjectEvidence("m0", (), entered_derived_arm=True)])
    assert out["no_evidence"] == 1
    assert out["counts"]["derived_only"] == 0
    assert out["counts"] == {"both": 0, "raw_only": 0, "derived_only": 0, "neither": 0}
    assert out["n_with_evidence"] == 0
    empty = evidence_link_recovery(set(), [])
    assert empty["n_objects"] == 0
    assert empty["counts"] == {"both": 0, "raw_only": 0, "derived_only": 0, "neither": 0}


# ---------------------------------------------------------------------------
# C. Equal-token-budget truncation (item boundaries, asymmetry, empty)
# ---------------------------------------------------------------------------

def test_estimate_tokens_ceil_len_over_4() -> None:
    assert arms.estimate_tokens("") == 0
    assert arms.estimate_tokens("a") == 1     # ceil(1/4)
    assert arms.estimate_tokens("abcd") == 1  # ceil(4/4)
    assert arms.estimate_tokens("abcde") == 2  # ceil(5/4)


def test_equal_token_budget_drops_whole_items_never_splits() -> None:
    # Each item is 8 chars -> 2 tokens. Budget 5 fits 2 items (4 tokens), not a 3rd
    # (would be 6 > 5); the 3rd is dropped WHOLE, never truncated to fill the gap.
    items = ["abcdefgh", "abcdefgh", "abcdefgh"]
    out = equal_token_budget(items, budget=5)
    assert out["retained_items"] == 2
    assert out["total_tokens"] == 4
    assert out["dropped_items"] == 1
    assert out["total_tokens"] <= 5


def test_equal_token_budget_raw_many_small_vs_derived_few_dense_asymmetry() -> None:
    # Same budget: RAW arm = many small turns; DERIVED arm = few dense blobs.
    budget = 10
    raw_many_small = ["abcd"] * 8          # each 1 token -> 8 fit
    derived_few_dense = ["x" * 40, "y" * 40]  # each 10 tokens -> only 1 fits
    raw = equal_token_budget(raw_many_small, budget)
    derived = equal_token_budget(derived_few_dense, budget)
    assert raw["retained_items"] == 8
    assert derived["retained_items"] == 1
    # Both respect the identical budget — HYBRID/DERIVED can't win by more context.
    assert raw["total_tokens"] <= budget
    assert derived["total_tokens"] <= budget


def test_equal_token_budget_empty_safe() -> None:
    out = equal_token_budget([], budget=100)
    assert out == {
        "budget": 100, "considered_items": 0, "retained_items": 0,
        "dropped_items": 0, "total_tokens": 0, "per_item": [],
    }


# ---------------------------------------------------------------------------
# D. Representation aggregation + prompt provenance
# ---------------------------------------------------------------------------

def test_aggregate_representation_majority_median_empty_safe() -> None:
    samples = [
        rep.RepresentationSample(misleading=True, unsupported=True, usability_score=0.8),
        rep.RepresentationSample(misleading=True, unsupported=False, usability_score=0.6),
        rep.RepresentationSample(misleading=False, unsupported=False, usability_score=0.4),
    ]
    agg = rep.aggregate_representation(samples)
    assert agg["seam"] == "representation_quality"
    assert agg["n_samples"] == 3
    assert agg["misleading"] is True     # 2/3 majority
    assert agg["unsupported"] is False   # 1/3, no majority
    assert abs(agg["usability_median"] - 0.6) < 1e-9
    assert abs(agg["usability_mean"] - 0.6) < 1e-9
    empty = rep.aggregate_representation([])
    assert empty["n_samples"] == 0
    assert empty["usability_mean"] is None
    assert empty["misleading"] is None


def test_parse_representation_tolerates_junk_and_clamps() -> None:
    assert rep.parse_representation_response(None).parse_ok is False
    s = rep.parse_representation_response(
        {"misleading": "yes", "unsupported": "no", "usability_score": "1.9"}
    )
    assert s.misleading is True
    assert s.unsupported is False
    assert s.usability_score == 1.0  # clamped


def test_build_prompt_distinct_per_sample_ordinal() -> None:
    p0 = rep.build_representation_prompt("q", ["raw turn"], "derived", sample_ordinal=0)
    p1 = rep.build_representation_prompt("q", ["raw turn"], "derived", sample_ordinal=1)
    assert p0 != p1  # distinct -> distinct CachedLLMProvider cache key


def test_extract_derivation_version_reexported() -> None:
    env = MemoryEnvelope(
        schema_id="core.memory_envelope", schema_version="v1", kind="finding",
        scope=MemoryEnvelopeScope(),
        derivation=MemoryEnvelopeDerivation(
            producer_kind="item_extraction", producer_schema_id="ps",
            producer_schema_version="pv", prompt_variant="strict_v1", model_role="write_extraction",
        ),
    )
    mem = MemoryObject(type="decision", schema_id="core.memory_envelope", schema_version="v1", payload={}, envelope=env)
    v = rep.extract_derivation_version(mem)
    assert v["producer_kind"] == "item_extraction"
    assert v["prompt_variant"] == "strict_v1"
    assert v["memory_type"] == "decision"


# ---------------------------------------------------------------------------
# Counting stub judge
# ---------------------------------------------------------------------------

class _CountingJudge:
    """Deterministic stub judge; records call count and echoes prompts so we can
    prove N independent draws (not one cached repeat)."""

    def __init__(self) -> None:
        self.calls = 0
        self.prompts: list[str] = []

    def generate_json(self, *, system_prompt, user_prompt, schema_description):
        from providers.llm.base import LLMJsonResponse
        self.calls += 1
        self.prompts.append(user_prompt)
        return LLMJsonResponse(
            raw_text="{}",
            parsed_json={"misleading": False, "unsupported": False, "usability_score": 0.7},
            metadata=None,
        )


def test_n_independent_draws_under_real_cached_provider(tmp_path: Path) -> None:
    # Criterion 4, literal: N samples under a real CachedLLMProvider must be N cache
    # MISSES (independent draws), because each sample's prompt embeds a distinct ordinal.
    from providers.llm.cached import CachedLLMProvider
    judge = _CountingJudge()
    cached = CachedLLMProvider(judge, tmp_path / "jcache", model_tag="test")
    n = 4
    for ordinal in range(n):
        prompt = rep.build_representation_prompt("q", ["raw"], "derived", sample_ordinal=ordinal)
        cached.generate_json(system_prompt=rep.REPRESENTATION_SYSTEM_PROMPT, user_prompt=prompt, schema_description=rep.REPRESENTATION_SCHEMA)
    assert judge.calls == n
    assert cached.stats == {"hits": 0, "misses": n}  # N independent draws
    # Re-issuing the SAME ordinals hits the cache (proves independence came from ordinal).
    for ordinal in range(n):
        prompt = rep.build_representation_prompt("q", ["raw"], "derived", sample_ordinal=ordinal)
        cached.generate_json(system_prompt=rep.REPRESENTATION_SYSTEM_PROMPT, user_prompt=prompt, schema_description=rep.REPRESENTATION_SCHEMA)
    assert judge.calls == n  # no new upstream calls
    assert cached.stats == {"hits": n, "misses": n}


# ---------------------------------------------------------------------------
# E. Runner: synthetic DB (real storage + lexical-only retrieval, vector disabled)
# ---------------------------------------------------------------------------

def _env(producer_kind: str) -> MemoryEnvelope:
    # Envelope schema_id/version MUST be the canonical constants or the storage codec
    # drops the envelope on read.
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
    db = tmp_path / "rdh.db"
    storage = SQLiteStorageProvider(database_url=f"sqlite:///{db}")

    def add_item(sid, content):
        item = SourceItem(
            source_type="chat_message", source_id=sid, content_type="text/plain",
            content=content, container_ref=None, thread_ref="t1", visibility="public",
            processing_status="completed", processing_completed_at=utc_now(),
        )
        storage.create_source_item(item)
        # Lexical index entry so the turn is retrievable.
        storage.create_index_entry(IndexEntry(
            target_kind="source_item", target_id=item.id, index_type="lexical", text_view=content,
        ))
        return item.id

    def add_mem(mtype, payload):
        mem = MemoryObject(
            type=mtype, schema_id="core.memory_envelope", schema_version="v1", payload=payload,
            container_ref=None, visibility="public", envelope=_env("item_extraction"),
        )
        storage.create_memory_object(mem)
        text_view = " ".join(str(v) for v in payload.values())
        storage.create_index_entry(IndexEntry(
            target_kind="memory_object", target_id=mem.id, index_type="lexical", text_view=text_view,
        ))
        return mem.id

    def link(mem_id, source_item_id):
        storage.create_relation(Relation(
            from_kind="memory_object", from_id=mem_id, relation_type="supported_by",
            to_kind="source_item", to_id=source_item_id,
        ))

    # Domain-neutral corpus: a "reservation ledger" episode.
    s0 = add_item("t1-0", "the reservation ledger holds must be idempotent")
    s1 = add_item("t1-1", "we discussed the reservation ledger design")
    dec = add_mem("decision", {"decision": "holds must be idempotent in the reservation ledger"})
    link(dec, s0)

    # Seed one historical agent-pull lookup on the always-on funnel event (the
    # loader's authoritative population — NOT query_audit_log, which is off by
    # default). query_text is the redacted search phrase.
    storage.write_historical_lookup_event_row({
        "id": "lk1",
        "created_at": utc_now(),
        "event_type": "lookup",
        "session_id": None,
        "container_ref": None,
        "actor_ref": None,
        "trigger_origin": "agent_pull",
        "parent_lookup_id": None,
        "exposed_json": "[]",
        "visibility": None,
        "source_session_ref": None,
        "query_text": "reservation ledger idempotent holds",
    })

    return {"storage": storage, "db": str(db), "s0": s0, "s1": s1, "dec": dec}


def _build_lexical_retrieval(storage):
    from retrieval.lexical import LexicalRetrievalProvider
    return LexicalRetrievalProvider(storage)


def test_population_counts_lookups_only_and_reports_exclusions(synthetic_db) -> None:
    """count_lookup_population counts funnel 'lookup' events under the loader's
    filters, splits with/without query_text, and never counts expansions."""
    storage = synthetic_db["storage"]
    # A second lookup with NO query_text (legacy / pre-column) — excluded from the
    # eval population but reported.
    storage.write_historical_lookup_event_row({
        "id": "lk2", "created_at": utc_now(), "event_type": "lookup",
        "session_id": None, "container_ref": None, "actor_ref": None,
        "trigger_origin": "agent_pull", "parent_lookup_id": None,
        "exposed_json": "[]", "visibility": None, "source_session_ref": None,
        "query_text": None,
    })
    # An expansion event must NOT inflate the lookup population.
    storage.write_historical_lookup_event_row({
        "id": "ex1", "created_at": utc_now(), "event_type": "expansion",
        "session_id": None, "container_ref": None, "actor_ref": None,
        "trigger_origin": None, "parent_lookup_id": "lk1",
        "exposed_json": "[]", "visibility": None, "source_session_ref": "t1",
        "query_text": None,
    })

    origins = ("agent_pull", "mcp_pull")
    pop = count_lookup_population(
        synthetic_db["db"], container_ref=None, thread_ref=None, actor_ref=None,
        trigger_origins=origins,
    )
    assert pop["total"] == 2  # two lookups (lk1, lk2); expansion excluded
    assert pop["with_query_text"] == 1  # only lk1
    assert pop["without_query_text"] == 1  # lk2, reported not silently dropped

    rows = load_query_rows(
        synthetic_db["db"], container_ref=None, thread_ref=None, actor_ref=None,
        trigger_origins=origins,
    )
    assert [r.query_text for r in rows] == ["reservation ledger idempotent holds"]


def test_run_eval_report_includes_population(synthetic_db) -> None:
    """The eval report carries a population block (default install won't emit a
    silent zero — it states how many lookups were found and excluded)."""
    judge = _CountingJudge()
    retrieval = _build_lexical_retrieval(synthetic_db["storage"])
    report = run_eval(
        db_path=synthetic_db["db"], storage=synthetic_db["storage"], retrieval=retrieval,
        judge_provider=judge, report_time_model="test-model",
        limit=0, seed=1, container_ref=None, thread_ref=None, actor_ref=None,
        trigger_origins=("agent_pull", "mcp_pull"),
        retrieval_limit=10, judge_samples=1, represent_limit=0, token_budgets=[64],
    )
    assert report["population"]["total"] == 1
    assert report["population"]["with_query_text"] == 1
    assert report["population"]["without_query_text"] == 0


def test_runner_three_arms_purity_recovery_and_seam_labels(synthetic_db) -> None:
    judge = _CountingJudge()
    retrieval = _build_lexical_retrieval(synthetic_db["storage"])
    report = run_eval(
        db_path=synthetic_db["db"], storage=synthetic_db["storage"], retrieval=retrieval,
        judge_provider=judge, report_time_model="test-model",
        limit=0, seed=17, container_ref=None, thread_ref=None, actor_ref=None,
        trigger_origins=("agent_pull", "mcp_pull"),
        retrieval_limit=10, judge_samples=3, represent_limit=0, token_budgets=[64, 256],
    )
    assert report["eval"] == "raw_derived_hybrid.v1"
    assert report["query_count"] == 1
    pq = report["queries"][0]

    # Three arms produced.
    assert set(pq["arms"]) == {RAW, DERIVED, HYBRID}
    # RAW arm has NO memory objects.
    raw_kinds = {c["kind"] for c in pq["arms"][RAW]["candidates"]}
    assert KIND_MEMORY not in raw_kinds
    assert pq["arms"][RAW]["target_kind"] == "source_item"
    assert raw_kinds == {KIND_SOURCE}
    # DERIVED arm retrieved the decision object.
    derived_ids = {c["id"] for c in pq["arms"][DERIVED]["candidates"]}
    assert synthetic_db["dec"] in derived_ids

    # Evidence-link recovery present; the decision's source s0 is in RAW and the
    # object is in DERIVED -> a "both" episode.
    recovery = pq["candidate_recovery"]
    assert recovery["seam"] == "candidate_recovery"
    assert recovery["counts"]["both"] >= 1
    labels = {o["memory_object_id"]: o["label"] for o in recovery["objects"]}
    assert labels[synthetic_db["dec"]] == "both"

    # Representation quality: version-stamped, seam-labelled.
    rq = pq["representation_quality"]
    assert rq["seam"] == "representation_quality"
    assert rq["judged_object_count"] >= 1
    judged = next(o for o in rq["objects"] if o["memory_object_id"] == synthetic_db["dec"])
    assert judged["version"]["producer_kind"] == "item_extraction"
    assert judged["representation"]["n_samples"] == 3

    # Context cost is a SEPARATE equal-token-budget axis (not blended, not judged).
    cc = pq["context_cost_equal_token_budget"]
    assert cc["seam"] == "context_cost"
    assert set(cc["by_budget"]) == {"64", "256"}
    for budget_str, per_arm in cc["by_budget"].items():
        for _arm_name, res in per_arm.items():
            assert res["total_tokens"] <= int(budget_str)

    # Seam labels + version stamp + current-index caveat; NO blended/downstream number.
    assert "current_index_replay" in report["caveats"]
    assert report["report_time_model"] == "test-model"
    blob = str(report)
    assert "derived_is_better" not in blob
    # aggregate is the two distinct seams + context cost — no blended scalar metric.
    assert "downstream" not in report["candidate_recovery_aggregate"]
    # The two seams stay distinct keys; no single "derived quality" scalar.
    assert "candidate_recovery" in pq and "representation_quality" in pq
    assert report["candidate_recovery_aggregate"]["counts"]["both"] >= 1


def test_runner_degrades_to_no_judge(synthetic_db) -> None:
    retrieval = _build_lexical_retrieval(synthetic_db["storage"])
    report = run_eval(
        db_path=synthetic_db["db"], storage=synthetic_db["storage"], retrieval=retrieval,
        judge_provider=None, report_time_model=None,
        limit=0, seed=17, container_ref=None, thread_ref=None, actor_ref=None,
        trigger_origins=("agent_pull", "mcp_pull"),
        retrieval_limit=10, judge_samples=3, represent_limit=0, token_budgets=[256],
    )
    pq = report["queries"][0]
    # Objective recovery still computed; representation judge skipped.
    assert pq["candidate_recovery"]["counts"]["both"] >= 1
    for o in pq["representation_quality"]["objects"]:
        assert o["representation"] is None
        assert o["version"]["producer_kind"] == "item_extraction"


def test_runner_cached_provider_independent_draws(synthetic_db, tmp_path) -> None:
    from providers.llm.cached import CachedLLMProvider
    judge = _CountingJudge()
    cached = CachedLLMProvider(judge, tmp_path / "runcache", model_tag="test")
    retrieval = _build_lexical_retrieval(synthetic_db["storage"])
    run_eval(
        db_path=synthetic_db["db"], storage=synthetic_db["storage"], retrieval=retrieval,
        judge_provider=cached, report_time_model="m",
        limit=0, seed=17, container_ref=None, thread_ref=None, actor_ref=None,
        trigger_origins=("agent_pull", "mcp_pull"),
        retrieval_limit=10, judge_samples=3, represent_limit=0, token_budgets=[256],
    )
    # 1 DERIVED object x 3 samples = 3 distinct prompts -> 3 misses, 0 hits.
    assert judge.calls == 3
    assert cached.stats == {"hits": 0, "misses": 3}


def test_runner_explicit_queries_bypass_load(synthetic_db) -> None:
    # run_eval accepts explicit QueryRows (no query_audit_log dependency).
    retrieval = _build_lexical_retrieval(synthetic_db["storage"])
    q = QueryRow(
        query_text="reservation ledger idempotent holds",
        container_ref=None, thread_ref=None, actor_ref=None,
        visibility=None, trigger_origin="agent_pull",
    )
    report = run_eval(
        db_path=None, storage=synthetic_db["storage"], retrieval=retrieval,
        judge_provider=None, report_time_model=None,
        limit=0, seed=1, container_ref=None, thread_ref=None, actor_ref=None,
        trigger_origins=None, retrieval_limit=10, judge_samples=1,
        represent_limit=0, token_budgets=[256], queries=[q],
    )
    assert report["query_count"] == 1


def test_recovery_universe_excludes_tombstoned_objects(synthetic_db) -> None:
    # A tombstoned object linked to a RAW source can never enter the DERIVED arm, so it
    # must NOT appear in the recovery universe (else it falsely inflates raw_only).
    from evals.raw_derived_hybrid.runner import build_recovery_universe
    storage = synthetic_db["storage"]
    dead = MemoryObject(
        type="decision", schema_id="core.memory_envelope", schema_version="v1",
        payload={"decision": "obsolete"}, container_ref=None, visibility="public",
        envelope=_env("item_extraction"),
    )
    storage.create_memory_object(dead)
    storage.create_relation(Relation(
        from_kind="memory_object", from_id=dead.id, relation_type="supported_by",
        to_kind="source_item", to_id=synthetic_db["s1"],
    ))
    storage.soft_delete_memory(dead.id, reason="test tombstone")

    universe = build_recovery_universe(
        storage, {synthetic_db["s0"], synthetic_db["s1"]}, {synthetic_db["dec"]}
    )
    ids = {o.memory_object_id for o in universe}
    assert dead.id not in ids            # tombstoned excluded (can't be a DERIVED miss)
    assert synthetic_db["dec"] in ids    # active derived object still present

def test_exact_work_origin_is_excluded_from_unscoped_replay_even_for_all(
    synthetic_db,
) -> None:
    storage = synthetic_db["storage"]
    storage.write_historical_lookup_event_row({
        "id": "work-lk",
        "created_at": utc_now(),
        "event_type": "lookup",
        "session_id": None,
        "container_ref": None,
        "actor_ref": None,
        "trigger_origin": "agent_pull_work",
        "parent_lookup_id": None,
        "exposed_json": "[]",
        "visibility": None,
        "source_session_ref": None,
        "query_text": "scoped query must not replay broadly",
    })

    population = count_lookup_population(
        synthetic_db["db"],
        container_ref=None,
        thread_ref=None,
        actor_ref=None,
        trigger_origins=None,
    )
    rows = load_query_rows(
        synthetic_db["db"],
        container_ref=None,
        thread_ref=None,
        actor_ref=None,
        trigger_origins=None,
    )

    assert population["total"] == 1
    assert [row.trigger_origin for row in rows] == ["agent_pull"]
