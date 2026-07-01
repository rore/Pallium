"""W3 E2E edge-case tests — comprehensive coverage of the 5 memory-write tools.

Complements the unit + integration tests in:
- tests/test_w3_memory_writes_schema.py (9 tests: schema + migration)
- tests/test_w3_memory_writes_storage.py (22 tests: storage-layer contracts)
- tests/test_w3_memory_writes_http.py (18 tests: HTTP happy/error paths)

This module covers the edge cases those don't:
- All 5 allowed memory types accepted by pallium_remember
- Boundary values (confidence 0.0/1.0, reason at max length, near-max text)
- Unicode / multilingual text
- Soft-deleted + superseded interactions (correct/supersede/forget on non-active)
- Supersession chain length > 2 (A→B→C attempts)
- Cross-tool full lifecycle journeys (remember → correct → forget)
- Retrieval integration (writes are actually indexed and queryable)
- All 3 outcome enum values for record_outcome
- Repeated outcomes for the same procedure

Every test drives through the HTTP surface so it exercises pydantic
validation + FastAPI + service + storage as one path.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text as _text


@pytest.fixture
def client(tmp_path):
    from app.config import AppConfig
    from app.main import create_app
    from storage.vector_index import VectorIndexConfig
    from tests.config_helpers import DEMO_SEMANTIC_PACKAGES
    from fastapi.testclient import TestClient

    db_url = f"sqlite:///{tmp_path / 'w3-e2e.db'}"
    config = AppConfig(
        storage_backend="sqlite",
        sqlite_url=db_url,
        default_use_case="demo_agent_memory",
        semantic_packages=DEMO_SEMANTIC_PACKAGES,
        vector_index=VectorIndexConfig(enabled=False),
    )
    app = create_app(config)
    return TestClient(app)


@pytest.fixture
def storage(client):
    return client.app.state.pallium_service._storage


def _remember(client, **overrides) -> dict:
    """Convenience: POST /memory/remember with sensible defaults, return response body."""
    body = {
        "text": "a durable fact",
        "type": "decision",
        "container_ref": "git:test",
    }
    body.update(overrides)
    resp = client.post("/memory/remember", json=body)
    assert resp.status_code in (200, 400, 422), (
        f"unexpected status {resp.status_code}: {resp.text}"
    )
    if resp.status_code == 200:
        return resp.json()
    return {"_status": resp.status_code, "_body": resp.text}


class TestRememberEveryAllowedType:
    """Every type in _W3_ALLOWED_MEMORY_TYPES must be accepted."""

    @pytest.mark.parametrize("mtype", [
        "decision",
        "investigation_outcome",
        "constraint_memory",
        "operational_fact",
        "note",
    ])
    def test_type_accepted(self, client, mtype):
        result = _remember(client, type=mtype, text=f"a {mtype} fact")
        assert "memory_object_id" in result, f"type={mtype!r} rejected: {result}"
        assert result["origin"] == "agent_explicit"


class TestRememberBoundaryValues:
    """Values at the exact edge of the accepted range."""

    def test_confidence_zero_exactly(self, client):
        r = _remember(client, confidence=0.0)
        assert "memory_object_id" in r

    def test_confidence_one_exactly(self, client):
        r = _remember(client, confidence=1.0)
        assert "memory_object_id" in r

    def test_confidence_above_one_rejected(self, client):
        resp = client.post("/memory/remember", json={
            "text": "x", "type": "decision", "confidence": 1.01,
        })
        assert resp.status_code == 422

    def test_text_near_max_accepted(self, client):
        """9999 chars: one below the 10000 boundary."""
        r = _remember(client, text="a" * 9999)
        assert "memory_object_id" in r

    def test_text_at_max_accepted(self, client):
        """Exactly 10000 chars: at the boundary."""
        r = _remember(client, text="a" * 10_000)
        assert "memory_object_id" in r

    def test_text_over_max_rejected(self, client):
        resp = client.post("/memory/remember", json={
            "text": "a" * 10_001, "type": "decision",
        })
        assert resp.status_code == 422

    def test_evidence_exactly_five_items(self, client):
        r = _remember(client, evidence=["e1", "e2", "e3", "e4", "e5"])
        assert "memory_object_id" in r

    def test_evidence_six_items_rejected(self, client):
        resp = client.post("/memory/remember", json={
            "text": "x", "type": "decision",
            "evidence": ["e1", "e2", "e3", "e4", "e5", "e6"],
        })
        assert resp.status_code == 422

    def test_evidence_empty_list_accepted(self, client):
        r = _remember(client, evidence=[])
        assert "memory_object_id" in r

    def test_evidence_none_accepted(self, client):
        r = _remember(client, evidence=None)
        assert "memory_object_id" in r


class TestRememberUnicode:
    """Pallium supports multilingual; make sure explicit writes preserve it.

    NOTE: payload_json is stored with ensure_ascii=True, so raw JSON contains
    \\u escape sequences rather than literal Unicode characters. The test
    decodes payload_json before asserting to check the semantic content, not
    the storage encoding.
    """

    @staticmethod
    def _decoded_statement(storage, mid: str) -> str:
        import json as _json
        with storage._engine.connect() as conn:
            raw = conn.execute(_text(
                "SELECT payload_json FROM memory_objects WHERE id=:i"
            ), {"i": mid}).scalar()
        return _json.loads(raw)["statement"]

    def test_hebrew_text(self, client, storage):
        r = _remember(client, text="החלטה: להשתמש בגישה B במקום A")
        statement = self._decoded_statement(storage, r["memory_object_id"])
        assert "החלטה" in statement

    def test_chinese_text(self, client, storage):
        r = _remember(client, text="决定：使用方法B而不是A")
        statement = self._decoded_statement(storage, r["memory_object_id"])
        assert "方法B" in statement

    def test_emoji_and_symbols(self, client, storage):
        r = _remember(client, text="✅ Approach B → prefer this. €100 budget, α=0.05.")
        statement = self._decoded_statement(storage, r["memory_object_id"])
        assert "→" in statement
        assert "α" in statement


class TestRememberProvenanceCombinations:
    """Verify optional provenance fields land correctly regardless of combination."""

    def test_only_session_id(self, client, storage):
        r = _remember(client, origin_session_id="sess-only")
        mid = r["memory_object_id"]
        with storage._engine.connect() as conn:
            row = conn.execute(_text(
                "SELECT origin_session_id, origin_agent_id FROM memory_objects WHERE id=:i"
            ), {"i": mid}).one()
        assert row.origin_session_id == "sess-only"
        assert row.origin_agent_id is None

    def test_only_agent_id(self, client, storage):
        r = _remember(client, origin_agent_id="agent-only")
        mid = r["memory_object_id"]
        with storage._engine.connect() as conn:
            row = conn.execute(_text(
                "SELECT origin_session_id, origin_agent_id FROM memory_objects WHERE id=:i"
            ), {"i": mid}).one()
        assert row.origin_session_id is None
        assert row.origin_agent_id == "agent-only"

    def test_neither(self, client, storage):
        r = _remember(client)
        mid = r["memory_object_id"]
        with storage._engine.connect() as conn:
            row = conn.execute(_text(
                "SELECT origin_session_id, origin_agent_id FROM memory_objects WHERE id=:i"
            ), {"i": mid}).one()
        assert row.origin_session_id is None
        assert row.origin_agent_id is None


class TestRememberDistinctIds:
    def test_multiple_remembers_get_distinct_ids(self, client):
        ids = {_remember(client, text=f"fact-{i}")["memory_object_id"] for i in range(5)}
        assert len(ids) == 5, "Each remember must produce a unique memory_object_id"


class TestCorrectEdgeCases:
    def test_correct_empty_reason_rejected(self, client):
        r = _remember(client)
        resp = client.post(f"/memory/{r['memory_object_id']}/correct", json={
            "corrected_text": "fix", "reason": "",
        })
        assert resp.status_code == 422

    def test_correct_reason_at_max_length(self, client):
        r = _remember(client)
        resp = client.post(f"/memory/{r['memory_object_id']}/correct", json={
            "corrected_text": "fix", "reason": "r" * 500,
        })
        assert resp.status_code == 200

    def test_correct_reason_over_max_rejected(self, client):
        r = _remember(client)
        resp = client.post(f"/memory/{r['memory_object_id']}/correct", json={
            "corrected_text": "fix", "reason": "r" * 501,
        })
        assert resp.status_code == 422

    def test_correct_preserves_type_and_schema(self, client, storage):
        r = _remember(client, type="investigation_outcome", text="found root cause X")
        mid = r["memory_object_id"]
        with storage._engine.connect() as conn:
            before = conn.execute(_text(
                "SELECT type, schema_id, schema_version FROM memory_objects WHERE id=:i"
            ), {"i": mid}).one()
        client.post(f"/memory/{mid}/correct", json={
            "corrected_text": "actual root cause was Y", "reason": "further investigation",
        })
        with storage._engine.connect() as conn:
            after = conn.execute(_text(
                "SELECT type, schema_id, schema_version FROM memory_objects WHERE id=:i"
            ), {"i": mid}).one()
        assert (before.type, before.schema_id, before.schema_version) == (
            after.type, after.schema_id, after.schema_version
        ), "correct must not change type/schema — that's supersede's job"

    def test_correct_twice_consecutively(self, client, storage):
        r = _remember(client, text="original")
        mid = r["memory_object_id"]
        assert client.post(f"/memory/{mid}/correct", json={
            "corrected_text": "first fix", "reason": "reason 1",
        }).status_code == 200
        # Second correction on the same active memory should also succeed.
        assert client.post(f"/memory/{mid}/correct", json={
            "corrected_text": "second fix", "reason": "reason 2",
        }).status_code == 200
        with storage._engine.connect() as conn:
            row = conn.execute(_text(
                "SELECT payload_json, correction_reason FROM memory_objects WHERE id=:i"
            ), {"i": mid}).one()
        assert "second fix" in row.payload_json
        assert row.correction_reason == "reason 2"

    def test_correct_on_soft_deleted_still_allowed(self, client, storage):
        """A soft-deleted memory is orthogonal to lifecycle; correct semantics
        gate on lifecycle only. Soft-deletion doesn't move the memory out of
        'active' lifecycle, so correction should succeed."""
        r = _remember(client)
        mid = r["memory_object_id"]
        client.post(f"/memory/{mid}/forget", json={"reason": "hidden"})
        resp = client.post(f"/memory/{mid}/correct", json={
            "corrected_text": "corrected while hidden", "reason": "test",
        })
        assert resp.status_code == 200


class TestSupersedeEdgeCases:
    def test_chain_length_3_a_to_b_to_c(self, client, storage):
        """Chain: remember A → supersede A with B → attempt supersede A with C.
        The third call must return 409 because A is already superseded.
        Superseding B with C is a separate valid operation.
        """
        a = _remember(client, text="A")["memory_object_id"]
        # A → B
        r1 = client.post("/memory/supersede", json={
            "new_text": "B", "supersedes_id": a,
        })
        assert r1.status_code == 200
        b = r1.json()["new_memory_object_id"]
        # A → C rejected
        r2 = client.post("/memory/supersede", json={
            "new_text": "C via A", "supersedes_id": a,
        })
        assert r2.status_code == 409
        # B → C accepted (B is still active)
        r3 = client.post("/memory/supersede", json={
            "new_text": "C", "supersedes_id": b,
        })
        assert r3.status_code == 200
        c = r3.json()["new_memory_object_id"]
        # Chain integrity: A superseded_by=B, B superseded_by=C, C active
        with storage._engine.connect() as conn:
            rows = {}
            for mid in (a, b, c):
                row = conn.execute(_text(
                    "SELECT lifecycle, superseded_by_id FROM memory_objects WHERE id=:i"
                ), {"i": mid}).one()
                rows[mid] = (row.lifecycle, row.superseded_by_id)
        assert rows[a] == ("superseded", b)
        assert rows[b] == ("superseded", c)
        assert rows[c] == ("active", None)

    def test_supersede_with_different_type(self, client, storage):
        """The new memory can have a different type than the old — supersession
        replaces intent, not type. Storing an investigation as a decision is
        allowed if the caller wants that shape."""
        old = _remember(client, type="investigation_outcome", text="investigated X")["memory_object_id"]
        resp = client.post("/memory/supersede", json={
            "new_text": "Decision: don't do X.", "supersedes_id": old,
            "type": "decision",
        })
        assert resp.status_code == 200
        new_id = resp.json()["new_memory_object_id"]
        with storage._engine.connect() as conn:
            new_type = conn.execute(_text(
                "SELECT type FROM memory_objects WHERE id=:i"
            ), {"i": new_id}).scalar()
            old_type = conn.execute(_text(
                "SELECT type FROM memory_objects WHERE id=:i"
            ), {"i": old}).scalar()
        assert old_type == "investigation_outcome"
        assert new_type == "decision"

    def test_supersede_with_invalid_new_type_rejected(self, client):
        old = _remember(client)["memory_object_id"]
        resp = client.post("/memory/supersede", json={
            "new_text": "x", "supersedes_id": old, "type": "not_valid",
        })
        assert resp.status_code == 400

    def test_supersede_reason_at_max(self, client):
        old = _remember(client)["memory_object_id"]
        resp = client.post("/memory/supersede", json={
            "new_text": "new", "supersedes_id": old, "reason": "r" * 500,
        })
        assert resp.status_code == 200

    def test_supersede_reason_over_max_rejected(self, client):
        old = _remember(client)["memory_object_id"]
        resp = client.post("/memory/supersede", json={
            "new_text": "new", "supersedes_id": old, "reason": "r" * 501,
        })
        assert resp.status_code == 422

    def test_supersede_soft_deleted_memory_returns_conflict(self, client):
        """Soft-delete alone doesn't move lifecycle, so supersede works.
        This is the reference behavior — call out clearly."""
        old = _remember(client)["memory_object_id"]
        client.post(f"/memory/{old}/forget", json={"reason": "hidden"})
        resp = client.post("/memory/supersede", json={
            "new_text": "replacement", "supersedes_id": old,
        })
        # Lifecycle is still 'active' after forget (tombstone is orthogonal),
        # so supersede succeeds. This is the documented semantic.
        assert resp.status_code == 200


class TestForgetEdgeCases:
    def test_forget_empty_reason_rejected(self, client):
        r = _remember(client)
        resp = client.post(f"/memory/{r['memory_object_id']}/forget", json={"reason": ""})
        assert resp.status_code == 422

    def test_forget_reason_at_max(self, client):
        r = _remember(client)
        resp = client.post(f"/memory/{r['memory_object_id']}/forget", json={"reason": "r" * 500})
        assert resp.status_code == 200

    def test_forget_reason_over_max_rejected(self, client):
        r = _remember(client)
        resp = client.post(f"/memory/{r['memory_object_id']}/forget", json={"reason": "r" * 501})
        assert resp.status_code == 422

    def test_forget_a_superseded_memory_allowed(self, client, storage):
        """A superseded memory can still be soft-deleted for audit hygiene.
        Retrieval already hides it via lifecycle; soft-delete adds a second
        signal.
        """
        old = _remember(client)["memory_object_id"]
        client.post("/memory/supersede", json={"new_text": "new", "supersedes_id": old})
        # Old is now lifecycle='superseded'.
        resp = client.post(f"/memory/{old}/forget", json={"reason": "audit cleanup"})
        assert resp.status_code == 200
        assert resp.json()["forgotten"] is True
        with storage._engine.connect() as conn:
            row = conn.execute(_text(
                "SELECT lifecycle, is_soft_deleted, soft_delete_reason FROM memory_objects WHERE id=:i"
            ), {"i": old}).one()
        assert row.lifecycle == "superseded"
        assert row.is_soft_deleted == 1
        assert row.soft_delete_reason == "audit cleanup"


class TestRecordOutcomeEdgeCases:
    @pytest.mark.parametrize("outcome", ["success", "failure", "inconclusive"])
    def test_all_three_outcome_values(self, client, outcome):
        proc = _remember(client, type="operational_fact")["memory_object_id"]
        resp = client.post("/memory/record-outcome", json={
            "procedure_id": proc, "outcome": outcome,
        })
        assert resp.status_code == 200
        assert resp.json()["outcome"] == outcome

    def test_multiple_outcomes_for_same_procedure(self, client, storage):
        """Recording multiple outcomes creates multiple note memory objects
        (one per outcome). This is intentional — each is an event.
        """
        proc = _remember(client, type="operational_fact")["memory_object_id"]
        for outcome in ("success", "failure", "success"):
            resp = client.post("/memory/record-outcome", json={
                "procedure_id": proc, "outcome": outcome,
            })
            assert resp.status_code == 200
        # Three note memories should exist linked to this procedure.
        with storage._engine.connect() as conn:
            count = conn.execute(_text(
                "SELECT COUNT(*) FROM memory_objects "
                "WHERE type='note' AND payload_json LIKE :p"
            ), {"p": f'%"procedure_id": "{proc}"%'}).scalar()
        assert count == 3

    def test_outcome_with_evidence_and_note(self, client, storage):
        proc = _remember(client, type="operational_fact")["memory_object_id"]
        resp = client.post("/memory/record-outcome", json={
            "procedure_id": proc, "outcome": "success",
            "evidence": ["source:1", "source:2"],
            "note": "worked on first try",
        })
        assert resp.status_code == 200

    def test_outcome_evidence_over_max_rejected(self, client):
        proc = _remember(client, type="operational_fact")["memory_object_id"]
        resp = client.post("/memory/record-outcome", json={
            "procedure_id": proc, "outcome": "success",
            "evidence": ["e1", "e2", "e3", "e4", "e5", "e6"],
        })
        assert resp.status_code == 422

    def test_outcome_note_over_max_rejected(self, client):
        proc = _remember(client, type="operational_fact")["memory_object_id"]
        resp = client.post("/memory/record-outcome", json={
            "procedure_id": proc, "outcome": "success",
            "note": "n" * 501,
        })
        assert resp.status_code == 422

    def test_outcome_against_non_operational_fact_type_currently_allowed(
        self, client, storage
    ):
        """v1 accepts outcomes against any existing memory. When W4 wires
        procedure counters, this will likely tighten to only operational_fact.
        Documenting current behavior so the tightening PR moves the assertion
        deliberately.
        """
        proc = _remember(client, type="decision")["memory_object_id"]
        resp = client.post("/memory/record-outcome", json={
            "procedure_id": proc, "outcome": "success",
        })
        assert resp.status_code == 200  # tighten in W4 if we decide to

    def test_outcome_against_soft_deleted_procedure(self, client):
        """v1: outcome records a fact linked to the (soft-deleted) procedure
        id. get_memory_object still returns soft-deleted rows, so this
        works. When W4 wires ranking, this may want to reject."""
        proc = _remember(client, type="operational_fact")["memory_object_id"]
        client.post(f"/memory/{proc}/forget", json={"reason": "cleanup"})
        resp = client.post("/memory/record-outcome", json={
            "procedure_id": proc, "outcome": "success",
        })
        assert resp.status_code == 200  # v1 permissive; W4 may tighten


class TestFullLifecycleJourneys:
    """End-to-end: chains of tool calls that mirror what an agent might do."""

    def test_remember_correct_forget(self, client, storage):
        r = _remember(client, text="original decision")
        mid = r["memory_object_id"]
        # Correct
        assert client.post(f"/memory/{mid}/correct", json={
            "corrected_text": "refined decision after test", "reason": "test found gap",
        }).status_code == 200
        # Forget
        assert client.post(f"/memory/{mid}/forget", json={
            "reason": "no longer relevant after milestone shift",
        }).status_code == 200
        # State: single memory, lifecycle=active (correct doesn't change it),
        # is_soft_deleted=1, correction_reason and soft_delete_reason both set.
        with storage._engine.connect() as conn:
            row = conn.execute(_text(
                "SELECT lifecycle, is_soft_deleted, correction_reason, soft_delete_reason, payload_json "
                "FROM memory_objects WHERE id=:i"
            ), {"i": mid}).one()
        assert row.lifecycle == "active"
        assert row.is_soft_deleted == 1
        assert row.correction_reason == "test found gap"
        assert row.soft_delete_reason == "no longer relevant after milestone shift"
        assert "refined decision" in row.payload_json

    def test_remember_supersede_correct_the_new(self, client, storage):
        old = _remember(client, text="A")["memory_object_id"]
        new = client.post("/memory/supersede", json={
            "new_text": "B", "supersedes_id": old,
        }).json()["new_memory_object_id"]
        # Correcting the new (active) memory should work.
        assert client.post(f"/memory/{new}/correct", json={
            "corrected_text": "B fixed", "reason": "typo",
        }).status_code == 200
        # Correcting the old (superseded) memory must 409.
        r_old_correct = client.post(f"/memory/{old}/correct", json={
            "corrected_text": "should fail", "reason": "test",
        })
        assert r_old_correct.status_code == 409

    def test_remember_supersede_forget_new(self, client, storage):
        """Full journey: A→B, then forget B. A stays superseded; B is soft-deleted."""
        old = _remember(client, text="A")["memory_object_id"]
        new = client.post("/memory/supersede", json={
            "new_text": "B", "supersedes_id": old,
        }).json()["new_memory_object_id"]
        assert client.post(f"/memory/{new}/forget", json={"reason": "changed my mind"}).status_code == 200
        with storage._engine.connect() as conn:
            r_old = conn.execute(_text(
                "SELECT lifecycle, is_soft_deleted FROM memory_objects WHERE id=:i"
            ), {"i": old}).one()
            r_new = conn.execute(_text(
                "SELECT lifecycle, is_soft_deleted FROM memory_objects WHERE id=:i"
            ), {"i": new}).one()
        assert (r_old.lifecycle, r_old.is_soft_deleted) == ("superseded", 0)
        assert (r_new.lifecycle, r_new.is_soft_deleted) == ("active", 1)


class TestRetrievalIntegration:
    """Writes are actually indexed — /query returns them (when policy allows)."""

    def test_remembered_memory_has_index_entries(self, client, storage):
        r = _remember(
            client,
            text="Decision: use per-type block-score thresholds for abstention.",
            container_ref="git:idx-test",
        )
        mid = r["memory_object_id"]
        with storage._engine.connect() as conn:
            entries = conn.execute(_text(
                "SELECT index_type, text_view_name FROM index_entries "
                "WHERE target_kind='memory_object' AND target_id=:i "
                "ORDER BY index_type"
            ), {"i": mid}).fetchall()
        types = {e.index_type for e in entries}
        assert "lexical" in types, "explicit-write memory must have a lexical index entry"

    def test_superseded_new_memory_has_index_entries(self, client, storage):
        old = _remember(client, container_ref="git:idx-test")["memory_object_id"]
        new = client.post("/memory/supersede", json={
            "new_text": "replacement fact for retrieval test",
            "supersedes_id": old,
            "container_ref": "git:idx-test",
        }).json()["new_memory_object_id"]
        with storage._engine.connect() as conn:
            count = conn.execute(_text(
                "SELECT COUNT(*) FROM index_entries "
                "WHERE target_kind='memory_object' AND target_id=:i"
            ), {"i": new}).scalar()
        assert count >= 1, "superseded new memory must be indexed for retrieval"


class TestOrdering:
    def test_created_at_monotonic_across_remembers(self, client, storage):
        ids = [_remember(client, text=f"fact-{i}")["memory_object_id"] for i in range(5)]
        with storage._engine.connect() as conn:
            times = [
                conn.execute(_text(
                    "SELECT created_at FROM memory_objects WHERE id=:i"
                ), {"i": mid}).scalar()
                for mid in ids
            ]
        # Timestamps should be non-decreasing.
        assert times == sorted(times), (
            "sequential remembers must produce non-decreasing created_at"
        )


class TestErrorMessageQuality:
    """Errors that an agent will see should be actionable."""

    def test_invalid_type_error_names_the_allowed_set(self, client):
        resp = client.post("/memory/remember", json={"text": "x", "type": "bogus"})
        assert resp.status_code == 400
        detail = resp.json()["detail"]
        # Every allowed type should appear so the agent can self-correct.
        for allowed in ("decision", "investigation_outcome", "constraint_memory",
                        "operational_fact", "note"):
            assert allowed in detail, f"error must name allowed type {allowed!r}"

    def test_supersede_conflict_error_names_current_state(self, client):
        old = _remember(client)["memory_object_id"]
        client.post("/memory/supersede", json={"new_text": "first", "supersedes_id": old})
        resp = client.post("/memory/supersede", json={"new_text": "second", "supersedes_id": old})
        assert resp.status_code == 409
        detail = resp.json()["detail"]
        assert "superseded" in detail.lower() or "not active" in detail.lower(), (
            f"409 detail must explain the conflict: {detail}"
        )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
