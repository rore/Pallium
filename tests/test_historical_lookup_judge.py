"""Historical-lookup reuse judge — offline harness tests.

Covers (Verification plan C3):
- rung-1 (incorporation) + rung-2 (influence) labels emitted and PERSISTED to
  the append-only historical_lookup_reuse_label table (per-rater rows).
- user-directed-vs-agent-decided split.
- Cohen's kappa from a double-rated subsample.
- >=3 seeds produce DISTINCT LLM cache keys via the seed folded into the prompt.
- Empty/abandoned-lookup handling is empty-safe.

The judge LLM is a deterministic in-process STUB — no network calls.
"""
from __future__ import annotations

import json
from datetime import datetime

import pytest
from sqlalchemy import text

from evals.historical_lookup_judge import (
    JUDGE_SCHEMA,
    JUDGE_SYSTEM_PROMPT,
    LookupContext,
    _build_user_prompt,
    _load_lookup_contexts,
    cohens_kappa,
    run_judge,
)
from providers.llm.base import LLMJsonResponse
from providers.llm.cached import _cache_key
from storage.sqlite import SQLiteStorageProvider


def test_prompt_requires_one_contiguous_exact_shared_span() -> None:
    assert "one short, contiguous, exact substring" in JUDGE_SYSTEM_PROMPT
    assert "do not paraphrase, combine" in JUDGE_SYSTEM_PROMPT
    assert "there is no suitable exact shared substring" in JUDGE_SYSTEM_PROMPT

# ---------------------------------------------------------------------------
# Deterministic stub judge — verdict keyed on inert content markers
# ---------------------------------------------------------------------------


class _StubJudge:
    """Returns a fixed verdict per lookup, decided STRICTLY by markers in the
    WORK AFTER block (a marker in RETRIEVED HISTORY / CONTEXT BEFORE must NOT
    satisfy the rung — otherwise the before/after split is never exercised).
    Direction is read from CONTEXT BEFORE. Ignores the trailing reviewer-pass
    tag, so both raters agree (kappa is well-defined and, here, 1.0)."""

    def __init__(self) -> None:
        self.calls = 0

    def generate_json(self, *, system_prompt, user_prompt, schema_description) -> LLMJsonResponse:
        self.calls += 1
        # Slice out the blocks so a marker only counts where it actually appears.
        work_after = user_prompt.split("WORK AFTER:", 1)[-1]
        context_before = user_prompt.split("CONTEXT BEFORE:", 1)[-1].split(
            "RETRIEVED HISTORY:", 1
        )[0]
        if "INCORP_MARKER" in work_after:
            rung, genuine = "incorporation", True
        elif "INFLU_MARKER" in work_after:
            rung, genuine = "influence", True
        else:
            rung, genuine = "none", False
        direction = "user_directed" if "please recall" in context_before else "agent_decided"
        payload = {
            "genuine_opportunity": genuine,
            "rung": rung,
            "evidence_span": "INCORP_MARKER" if rung == "incorporation" else "",
            "direction": direction,
        }
        return LLMJsonResponse(raw_text=json.dumps(payload), parsed_json=payload)


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------


def _storage(tmp_path):
    db = tmp_path / "judge.db"
    return SQLiteStorageProvider(f"sqlite:///{db}"), str(db)


def _insert_turn(storage, *, sid, role, artifact_kind, content, thread, created,
                 container="c:1", forgotten=False):
    with storage._engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO source_items (id, source_type, source_id, content_type, "
                "content, role, artifact_kind, container_ref, thread_ref, visibility, "
                "processing_status, processing_attempts, processing_completed_at, "
                "forgotten_at, created_at) VALUES (:id,'chat_message',:sid,'text/plain',"
                ":content,:role,:ak,:c,:t,'private','completed',0,:completed,:forgotten,:created)"
            ),
            {
                "id": sid, "sid": sid, "content": content, "role": role, "ak": artifact_kind,
                "c": container, "t": thread, "completed": created,
                "forgotten": created if forgotten else None, "created": created,
            },
        )


def _write_lookup(storage, *, event_id, thread, exposed_ids, created, container="c:1"):
    storage.write_historical_lookup_event_row({
        "id": event_id,
        # The event's created_at IS the pivot the before/after split turns on.
        # The DateTime column takes a datetime; it serialises to the same
        # "YYYY-MM-DD HH:MM:SS.ffffff" string the source_items turns use, so the
        # lexicographic pivot comparison in the loader stays chronological.
        "created_at": datetime.fromisoformat(created),
        "event_type": "lookup",
        "session_id": thread,
        "container_ref": container,
        "actor_ref": None,
        "trigger_origin": "agent_pull",
        "parent_lookup_id": None,
        "exposed_json": json.dumps(
            [{"source_item_id": s, "raw_rank": i + 1, "score": 0.5} for i, s in enumerate(exposed_ids)]
        ),
        "visibility": "private",
    })
    # The historical row + surrounding turns are inserted by the caller.


def _seed_two_lookups(storage) -> None:
    """Two substantive sessions, one incorporation + user-directed, one
    influence + agent-decided."""
    # Retrieved history rows (past turns the lookups surface).
    _insert_turn(storage, sid="hist-1", role="assistant", artifact_kind="assistant_output",
                 content="Decision: use event time ordering. INCORP_MARKER",
                 thread="t:old", created="2026-07-01 00:00:01.000000")
    _insert_turn(storage, sid="hist-2", role="assistant", artifact_kind="assistant_output",
                 content="Past reservation duplicate-holds discussion. INFLU_MARKER",
                 thread="t:old", created="2026-07-01 00:00:02.000000")

    # Session 1: user-directed, incorporation.
    _insert_turn(storage, sid="s1-u", role="user", artifact_kind="message",
                 content="please recall our earlier decision",
                 thread="t:1", created="2026-08-01 00:00:01.000000")
    _write_lookup(storage, event_id="ev-1", thread="t:1", exposed_ids=["hist-1"],
                  created="2026-08-01 00:00:02.000000")
    _insert_turn(storage, sid="s1-a", role="assistant", artifact_kind="assistant_output",
                 content="Following the earlier decision, I use event time. INCORP_MARKER",
                 thread="t:1", created="2026-08-01 00:00:03.000000")

    # Session 2: agent-decided, influence.
    _insert_turn(storage, sid="s2-u", role="user", artifact_kind="message",
                 content="let's implement the reservation flow",
                 thread="t:2", created="2026-08-02 00:00:01.000000")
    _write_lookup(storage, event_id="ev-2", thread="t:2", exposed_ids=["hist-2"],
                  created="2026-08-02 00:00:02.000000")
    _insert_turn(storage, sid="s2-a", role="assistant", artifact_kind="assistant_output",
                 content="I designed reservations carefully. INFLU_MARKER",
                 thread="t:2", created="2026-08-02 00:00:03.000000")


# ---------------------------------------------------------------------------
# End-to-end offline judge
# ---------------------------------------------------------------------------


class TestJudgeOffline:
    def test_emits_and_persists_rung_labels(self, tmp_path) -> None:
        storage, db = _storage(tmp_path)
        _seed_two_lookups(storage)
        provider = _StubJudge()

        report = run_judge(
            db, provider=provider, storage=storage, container_ref="c:1",
            eligibility_n=0, seeds=[0, 1, 2], sample_size=10,
        )

        # 3 raters x 2 events → 6 persisted per-rater label rows.
        with storage._engine.connect() as conn:
            rows = conn.execute(
                text("SELECT lookup_event_id, rater_seed, rung FROM historical_lookup_reuse_label")
            ).mappings().all()
        assert len(rows) == 6
        rungs = {r["rung"] for r in rows}
        assert "incorporation" in rungs  # rung-1
        assert "influence" in rungs      # rung-2
        # Each event has 3 distinct rater seeds.
        for event_id in ("ev-1", "ev-2"):
            seeds = {r["rater_seed"] for r in rows if r["lookup_event_id"] == event_id}
            assert seeds == {"0", "1", "2"}

    def test_user_directed_vs_agent_split(self, tmp_path) -> None:
        storage, db = _storage(tmp_path)
        _seed_two_lookups(storage)
        report = run_judge(
            db, provider=_StubJudge(), storage=storage, container_ref="c:1",
            eligibility_n=0, seeds=[0, 1, 2],
        )
        assert report.user_directed == 1
        assert report.agent_decided == 1

    def test_kappa_from_double_rated_subsample(self, tmp_path) -> None:
        storage, db = _storage(tmp_path)
        _seed_two_lookups(storage)
        report = run_judge(
            db, provider=_StubJudge(), storage=storage, container_ref="c:1",
            eligibility_n=0, seeds=[0, 1, 2],
        )
        assert report.kappa is not None
        assert report.kappa_n == 2
        assert report.kappa_pair == ("0", "1")
        # Raters agree on every event across two distinct rung categories → kappa 1.0.
        assert report.kappa == pytest.approx(1.0)

    def test_report_rung_rates_and_wilson(self, tmp_path) -> None:
        storage, db = _storage(tmp_path)
        _seed_two_lookups(storage)
        report = run_judge(
            db, provider=_StubJudge(), storage=storage, container_ref="c:1",
            eligibility_n=0, seeds=[0, 1, 2],
        )
        payload = report.to_dict()
        assert payload["rung_rates"]["incorporation"]["numerator"] == 1
        assert payload["rung_rates"]["influence"]["numerator"] == 1
        wi = payload["rung_rates"]["incorporation"]["wilson_95"]
        assert 0.0 <= wi["low"] <= wi["high"] <= 100.0

    def test_reconstruction_splits_before_after(self, tmp_path) -> None:
        """The before/after split is actually exercised: the assistant work turn
        (created AFTER the lookup pivot) lands in after_turns. Guards the bug
        where the event's created_at was stamped at write time, dropping every
        turn into 'before' and leaving after_turns empty."""
        import sqlite3

        storage, db = _storage(tmp_path)
        _seed_two_lookups(storage)
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        try:
            contexts = _load_lookup_contexts(
                conn,
                eligible_set={"t:1", "t:2"},
                container_ref="c:1",
                since=None,
                until=None,
                before_turns=3,
                after_turns=4,
            )
        finally:
            conn.close()

        by_event = {c.lookup_event_id: c for c in contexts}
        ev1 = by_event["ev-1"]
        # Positive assertion: the reconstruction split the turns — the post-pivot
        # assistant work turn is present in after_turns.
        assert ev1.after_turns, "after_turns must be populated (split exercised)"
        assert any("INCORP_MARKER" in content for _role, content in ev1.after_turns)
        # And the pre-pivot user turn is on the before side.
        assert ev1.before_turns
        assert any("please recall" in content for _role, content in ev1.before_turns)


class _PayloadJudge:
    def __init__(self, *, rung, genuine, evidence) -> None:
        self.payload = {
            "genuine_opportunity": genuine,
            "rung": rung,
            "evidence_span": evidence,
            "direction": "agent_decided",
        }

    def generate_json(self, *, system_prompt, user_prompt, schema_description):
        return LLMJsonResponse(
            raw_text=json.dumps(self.payload),
            parsed_json=self.payload,
        )


def _seed_contract_lookup(storage, *, retrieved: str, after: str) -> None:
    _insert_turn(
        storage,
        sid="contract-history",
        role="assistant",
        artifact_kind="assistant_output",
        content=retrieved,
        thread="t:old",
        created="2026-07-01 00:00:01.000000",
    )
    _insert_turn(
        storage,
        sid="contract-user",
        role="user",
        artifact_kind="message",
        content="resume the task",
        thread="t:contract",
        created="2026-08-01 00:00:01.000000",
    )
    _write_lookup(
        storage,
        event_id="contract-event",
        thread="t:contract",
        exposed_ids=["contract-history"],
        created="2026-08-01 00:00:02.000000",
    )
    _insert_turn(
        storage,
        sid="contract-after",
        role="assistant",
        artifact_kind="assistant_output",
        content=after,
        thread="t:contract",
        created="2026-08-01 00:00:03.000000",
    )


class TestEvidenceSpanContract:
    @pytest.mark.parametrize(
        ("evidence", "retrieved", "after"),
        [
            ("shared fact", "SHARED\n fact", "used shared\tFACT"),
            ("x" * 200, "prefix " + "x" * 200, "x" * 200 + " suffix"),
            ("Straße", "Remember STRASSE", "Applied Straße"),
        ],
    )
    def test_valid_incorporation_is_accepted_and_persisted(
        self, tmp_path, evidence, retrieved, after
    ) -> None:
        storage, db = _storage(tmp_path)
        _seed_contract_lookup(storage, retrieved=retrieved, after=after)

        report = run_judge(
            db,
            provider=_PayloadJudge(
                rung="incorporation", genuine=True, evidence=evidence
            ),
            storage=storage,
            container_ref="c:1",
            eligibility_n=0,
            seeds=[0],
        )

        assert report.n_judge_failures == 0
        assert len(report.labels) == 1
        assert report.labels[0].evidence_span == evidence
        with storage._engine.connect() as conn:
            persisted = conn.execute(
                text("SELECT count(*) FROM historical_lookup_reuse_label")
            ).scalar_one()
        assert persisted == 1

    @pytest.mark.parametrize(
        ("rung", "genuine", "evidence", "retrieved", "after"),
        [
            ("incorporation", True, "", "shared fact", "shared fact"),
            ("incorporation", True, None, "shared fact", "shared fact"),
            ("incorporation", True, ["shared fact"], "shared fact", "shared fact"),
            ("incorporation", True, "x" * 201, "x" * 201, "x" * 201),
            ("incorporation", True, "work only", "different", "work only"),
            ("incorporation", True, "history only", "history only", "different"),
            ("influence", True, "shared fact", "shared fact", "shared fact"),
            ("none", False, "shared fact", "shared fact", "shared fact"),
        ],
    )
    def test_invalid_evidence_is_a_failure_and_is_not_persisted(
        self, tmp_path, rung, genuine, evidence, retrieved, after
    ) -> None:
        storage, db = _storage(tmp_path)
        _seed_contract_lookup(storage, retrieved=retrieved, after=after)

        report = run_judge(
            db,
            provider=_PayloadJudge(rung=rung, genuine=genuine, evidence=evidence),
            storage=storage,
            container_ref="c:1",
            eligibility_n=0,
            seeds=[0],
        )

        assert report.n_judge_failures == 1
        assert report.labels == []
        with storage._engine.connect() as conn:
            persisted = conn.execute(
                text("SELECT count(*) FROM historical_lookup_reuse_label")
            ).scalar_one()
        assert persisted == 0

# ---------------------------------------------------------------------------
# Seed folding — >=3 seeds must produce distinct cache keys
# ---------------------------------------------------------------------------


class TestSeedFolding:
    def test_three_seeds_produce_distinct_cache_keys(self) -> None:
        ctx = LookupContext(
            lookup_event_id="ev",
            session_id="t:1",
            container_ref="c:1",
            created_at="2026-08-01 00:00:02.000000",
            exposed=[{"source_item_id": "hist-1"}],
            retrieved_texts=["Decision: use event time ordering."],
            before_turns=[("user", "please recall our earlier decision")],
            after_turns=[("assistant", "Following the earlier decision.")],
        )
        keys = set()
        prompts = set()
        for ordinal in range(3):
            user_prompt = _build_user_prompt(ctx, ordinal)
            prompts.add(user_prompt)
            keys.add(_cache_key(JUDGE_SYSTEM_PROMPT, user_prompt, JUDGE_SCHEMA, "stub-model"))
        # Prompts differ only by the inert trailing tag → 3 distinct cache keys.
        assert len(prompts) == 3
        assert len(keys) == 3


# ---------------------------------------------------------------------------
# Cohen's kappa helper
# ---------------------------------------------------------------------------


class TestCohensKappa:
    def test_perfect_agreement_two_categories(self) -> None:
        assert cohens_kappa(["a", "b"], ["a", "b"]) == pytest.approx(1.0)

    def test_total_disagreement(self) -> None:
        # 2 items, swapped labels → kappa strongly negative.
        assert cohens_kappa(["a", "b"], ["b", "a"]) == pytest.approx(-1.0)

    def test_single_shared_category_is_one(self) -> None:
        assert cohens_kappa(["a", "a"], ["a", "a"]) == 1.0

    def test_empty_or_mismatched_returns_none(self) -> None:
        assert cohens_kappa([], []) is None
        assert cohens_kappa(["a"], ["a", "b"]) is None


# ---------------------------------------------------------------------------
# Empty / abandoned handling
# ---------------------------------------------------------------------------


class TestEmptyAndAbandoned:
    def test_empty_db_is_safe(self, tmp_path) -> None:
        storage, db = _storage(tmp_path)  # fresh schema, no events
        provider = _StubJudge()
        report = run_judge(
            db, provider=provider, storage=storage, container_ref="c:1",
            eligibility_n=0, seeds=[0, 1, 2],
        )
        assert report.n_sampled == 0
        assert report.kappa is None
        assert provider.calls == 0  # no lookups → no LLM calls
        # rung_rates present + empty-safe.
        assert report.rung_rates["incorporation"]["numerator"] == 0

    def test_abandoned_lookup_counted(self, tmp_path) -> None:
        storage, db = _storage(tmp_path)
        # A substantive session with a lookup that exposed NOTHING (abandoned).
        _insert_turn(storage, sid="u", role="user", artifact_kind="message",
                     content="hi", thread="t:1", created="2026-08-01 00:00:01.000000")
        _insert_turn(storage, sid="a", role="assistant", artifact_kind="assistant_output",
                     content="work", thread="t:1", created="2026-08-01 00:00:03.000000")
        _write_lookup(storage, event_id="ev-empty", thread="t:1", exposed_ids=[],
                      created="2026-08-01 00:00:02.000000")
        report = run_judge(
            db, provider=_StubJudge(), storage=storage, container_ref="c:1",
            eligibility_n=0, seeds=[0, 1, 2],
        )
        assert report.n_abandoned == 1
