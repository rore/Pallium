"""W4 PR 3 — derivation wiring tests for AgentWorkTracePlugin.

Verifies that when the [features] operational_fact_derivation flag is on,
build_thread_summary produces operational_fact MemoryObjects + IndexEntries
alongside the existing task_trace, without disturbing task_trace behavior.

Uses synthetic ThreadAggregate fixtures — no live DB, no service, no LLM.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from capabilities.thread_aggregation import build_thread_aggregate
from core.contracts import ProcessResult
from core.models import SourceItem, MemoryObject, new_id
from providers.llm.base import LLMJsonResponse, LLMProvider
from semantic.agent_work_trace import (
    AgentWorkTracePlugin,
    OPERATIONAL_FACT_LEXICAL_TEXT_VIEW,
    OPERATIONAL_FACT_SCHEMA_ID,
    TASK_TRACE_TYPE,
    _build_turn_stream_from_aggregate,
    _candidate_to_index_entry,
    _candidate_to_memory_object,
)
from semantic.operational_fact import (
    OPERATIONAL_FACT_TYPE,
    OperationalFactCandidate,
    DiscoveryEvent,
    UseEvent,
)


class StubOutcomeProvider(LLMProvider):
    def generate_json(self, *, system_prompt, user_prompt, schema_description):
        return LLMJsonResponse(raw_text='{"outcome": null}', parsed_json={"outcome": None})


def _make_source_item(
    *,
    content: str = "turn response",
    thread_ref: str = "session-1",
    container_ref: str = "git:example.com/repo",
    metadata: dict | None = None,
    occurred_at: datetime | None = None,
) -> SourceItem:
    return SourceItem(
        source_type="claude-code",
        source_id=f"cc-{new_id()[:12]}",
        content_type="text/plain",
        content=content,
        thread_ref=thread_ref,
        container_ref=container_ref,
        visibility="private",
        metadata=metadata,
        occurred_at=occurred_at,
    )


def _seed_discovery_use_turns() -> list[SourceItem]:
    """Two-turn stream: discovery of `where python` → use with same argv."""
    base = datetime(2026, 7, 1, 12, 0, 0, tzinfo=timezone.utc)
    items = []
    for i, turn in enumerate([
        {
            "commands": [
                {"cmd": "where python C:/Users/x/.venv/Scripts/python.exe",
                 "exit_code": 0, "output_tail": ""},
            ],
            "files_read": [],
            "files_modified": [],
            "grep_patterns": [],
            "has_productive_action": False,
        },
        {
            "commands": [
                {"cmd": "C:/Users/x/.venv/Scripts/python.exe --version",
                 "exit_code": 0, "output_tail": ""},
            ],
            "files_read": [],
            "files_modified": [],
            "grep_patterns": [],
            "has_productive_action": False,
        },
    ]):
        items.append(_make_source_item(
            metadata={"agent_work_trace_turn": turn, "cwd": "/home/x/project"},
            occurred_at=base + timedelta(minutes=i),
        ))
    return items


def _build_plugin(*, enabled: bool) -> AgentWorkTracePlugin:
    return AgentWorkTracePlugin(
        provider=StubOutcomeProvider(),
        operational_fact_derivation_enabled=enabled,
    )


class TestFeatureFlagOff:
    def test_flag_off_writes_task_trace_only(self):
        items = _seed_discovery_use_turns()
        aggregate = build_thread_aggregate(items)
        plugin = _build_plugin(enabled=False)
        result = plugin.build_thread_summary(aggregate, conclusions=[])
        types = [m.type for m in result.memory_objects]
        assert types.count(TASK_TRACE_TYPE) == 1
        assert types.count(OPERATIONAL_FACT_TYPE) == 0

    def test_flag_off_index_entries_only_for_task_trace(self):
        items = _seed_discovery_use_turns()
        aggregate = build_thread_aggregate(items)
        plugin = _build_plugin(enabled=False)
        result = plugin.build_thread_summary(aggregate, conclusions=[])
        # Exactly one index entry (task_trace only)
        assert len(result.index_entries) == 1
        assert result.index_entries[0].text_view_name != OPERATIONAL_FACT_LEXICAL_TEXT_VIEW


class TestFeatureFlagOn:
    def test_flag_on_derivation_writes_operational_fact(self):
        items = _seed_discovery_use_turns()
        aggregate = build_thread_aggregate(items)
        plugin = _build_plugin(enabled=True)
        result = plugin.build_thread_summary(aggregate, conclusions=[])
        types = [m.type for m in result.memory_objects]
        assert types.count(TASK_TRACE_TYPE) == 1
        assert types.count(OPERATIONAL_FACT_TYPE) >= 1

    def test_flag_on_operational_fact_container_ref_preserved(self):
        items = _seed_discovery_use_turns()
        aggregate = build_thread_aggregate(items)
        plugin = _build_plugin(enabled=True)
        result = plugin.build_thread_summary(aggregate, conclusions=[])
        op_facts = [m for m in result.memory_objects if m.type == OPERATIONAL_FACT_TYPE]
        for f in op_facts:
            assert f.container_ref == aggregate.container_ref

    def test_flag_on_operational_fact_schema_and_lifecycle(self):
        items = _seed_discovery_use_turns()
        aggregate = build_thread_aggregate(items)
        plugin = _build_plugin(enabled=True)
        result = plugin.build_thread_summary(aggregate, conclusions=[])
        op_facts = [m for m in result.memory_objects if m.type == OPERATIONAL_FACT_TYPE]
        for f in op_facts:
            assert f.schema_id == OPERATIONAL_FACT_SCHEMA_ID
            # PR 3 (recon-verb model): derived candidates ship as
            # lifecycle="candidate"; promotion to "active" is the wiring
            # layer's job at the next milestone.
            assert f.lifecycle == "candidate"

    def test_flag_on_visibility_matches_aggregate(self):
        items = _seed_discovery_use_turns()
        aggregate = build_thread_aggregate(items)
        plugin = _build_plugin(enabled=True)
        result = plugin.build_thread_summary(aggregate, conclusions=[])
        for f in result.memory_objects:
            if f.type == OPERATIONAL_FACT_TYPE:
                assert f.visibility == aggregate.visibility

    def test_flag_on_index_entry_for_each_operational_fact(self):
        items = _seed_discovery_use_turns()
        aggregate = build_thread_aggregate(items)
        plugin = _build_plugin(enabled=True)
        result = plugin.build_thread_summary(aggregate, conclusions=[])
        op_facts = [m for m in result.memory_objects if m.type == OPERATIONAL_FACT_TYPE]
        op_index_entries = [
            ix for ix in result.index_entries
            if ix.text_view_name == OPERATIONAL_FACT_LEXICAL_TEXT_VIEW
        ]
        assert len(op_index_entries) == len(op_facts)
        # target_id matches
        fact_ids = {f.id for f in op_facts}
        for ix in op_index_entries:
            assert ix.target_id in fact_ids
            assert ix.target_kind == "memory_object"


class TestUseCountersNesting:
    """Invariant 1 structural guard: use_counters is nested."""

    def test_use_counters_nested_not_top_level(self):
        items = _seed_discovery_use_turns()
        aggregate = build_thread_aggregate(items)
        plugin = _build_plugin(enabled=True)
        result = plugin.build_thread_summary(aggregate, conclusions=[])
        op_facts = [m for m in result.memory_objects if m.type == OPERATIONAL_FACT_TYPE]
        assert op_facts
        for f in op_facts:
            payload = f.payload
            # Top-level counters must NOT exist.
            assert "success_count" not in payload
            assert "reuse_count" not in payload
            assert "last_used_at" not in payload
            assert "failure_count" not in payload
            assert "last_confirmed_at" not in payload
            # Nested sub-blob must exist with all five keys.
            assert "use_counters" in payload
            uc = payload["use_counters"]
            assert set(uc.keys()) == {
                "reuse_count", "success_count", "failure_count",
                "last_used_at", "last_confirmed_at",
            }
            assert uc["reuse_count"] == 1
            assert uc["success_count"] == 0
            assert uc["failure_count"] == 0
            assert uc["last_used_at"] is not None
            assert uc["last_confirmed_at"] is None


class TestPayloadShape:
    def test_payload_has_expected_top_level_keys(self):
        items = _seed_discovery_use_turns()
        aggregate = build_thread_aggregate(items)
        plugin = _build_plugin(enabled=True)
        result = plugin.build_thread_summary(aggregate, conclusions=[])
        op_facts = [m for m in result.memory_objects if m.type == OPERATIONAL_FACT_TYPE]
        assert op_facts
        expected = {
            "command_family", "artifact_role", "scope_kind", "scope_ref",
            "subject", "artifact", "artifact_normalized", "evidence",
            "origin", "use_counters",
        }
        for f in op_facts:
            assert set(f.payload.keys()) == expected

    def test_payload_origin_is_agent_inferred(self):
        # Regression: derivation MUST tag every derived fact with
        # origin='agent_inferred' so the cross-origin rule can operate.
        items = _seed_discovery_use_turns()
        aggregate = build_thread_aggregate(items)
        plugin = _build_plugin(enabled=True)
        result = plugin.build_thread_summary(aggregate, conclusions=[])
        op_facts = [m for m in result.memory_objects if m.type == OPERATIONAL_FACT_TYPE]
        assert op_facts
        for f in op_facts:
            assert f.payload["origin"] == "agent_inferred"

    def test_evidence_has_exactly_one_entry(self):
        # PR 3 (recon-verb model): each candidate is derived from a single
        # reconnaissance event, so payload["evidence"] is length 1 and
        # contains only a "discovery" kind entry.
        items = _seed_discovery_use_turns()
        aggregate = build_thread_aggregate(items)
        plugin = _build_plugin(enabled=True)
        result = plugin.build_thread_summary(aggregate, conclusions=[])
        op_facts = [m for m in result.memory_objects if m.type == OPERATIONAL_FACT_TYPE]
        assert op_facts
        for f in op_facts:
            ev = f.payload["evidence"]
            assert len(ev) == 1
            kinds = {e["kind"] for e in ev}
            assert kinds == {"discovery"}

    def test_evidence_source_item_ids_link_back(self):
        items = _seed_discovery_use_turns()
        aggregate = build_thread_aggregate(items)
        plugin = _build_plugin(enabled=True)
        result = plugin.build_thread_summary(aggregate, conclusions=[])
        op_facts = [m for m in result.memory_objects if m.type == OPERATIONAL_FACT_TYPE]
        source_ids = {it.id for it in items}
        for f in op_facts:
            for e in f.payload["evidence"]:
                assert e["source_item_id"] in source_ids


class TestTurnStreamBuilder:
    def test_paired_invariant_enforced(self):
        """_build_turn_stream_from_aggregate must fail loud if the two
        lists desync — this is the correctness bedrock of the wiring."""
        items = _seed_discovery_use_turns()
        turns = [items[0].metadata["agent_work_trace_turn"]]  # length 1
        with pytest.raises(AssertionError):
            _build_turn_stream_from_aggregate(items, turns)  # length 2 vs 1

    def test_turn_index_is_thread_order(self):
        items = _seed_discovery_use_turns()
        turns = [it.metadata["agent_work_trace_turn"] for it in items]
        records = _build_turn_stream_from_aggregate(items, turns)
        assert [r.turn_index for r in records] == [0, 1]

    def test_commands_extracted_with_exit_code(self):
        items = _seed_discovery_use_turns()
        turns = [it.metadata["agent_work_trace_turn"] for it in items]
        records = _build_turn_stream_from_aggregate(items, turns)
        for rec in records:
            for cmd in rec.commands:
                assert cmd.exit_code == 0


class TestNoTraceItemsFallback:
    def test_zero_trace_items_returns_empty_processresult(self):
        # A thread aggregate with items that lack agent_work_trace_turn
        # metadata → build_thread_summary returns empty ProcessResult
        # regardless of the derivation flag.
        item = _make_source_item(metadata={"unrelated": True})
        aggregate = build_thread_aggregate([item])
        plugin = _build_plugin(enabled=True)
        result = plugin.build_thread_summary(aggregate, conclusions=[])
        assert result.memory_objects == []
        assert result.index_entries == []


class TestDerivationIdempotency:
    def test_two_rebuilds_produce_same_candidate_count(self):
        items = _seed_discovery_use_turns()
        aggregate = build_thread_aggregate(items)
        plugin = _build_plugin(enabled=True)
        r1 = plugin.build_thread_summary(aggregate, conclusions=[])
        r2 = plugin.build_thread_summary(aggregate, conclusions=[])
        count1 = sum(1 for m in r1.memory_objects if m.type == OPERATIONAL_FACT_TYPE)
        count2 = sum(1 for m in r2.memory_objects if m.type == OPERATIONAL_FACT_TYPE)
        assert count1 == count2

    def test_two_rebuilds_produce_same_candidate_identity(self):
        # Strengthened: compare the conflict-slot + artifact identity,
        # not just count. Two rebuilds must produce derived facts with
        # identical (family, role, scope_kind, scope_ref, artifact_normalized)
        # keys — else the derivation is non-deterministic and downstream
        # supersession will churn.
        items = _seed_discovery_use_turns()
        aggregate = build_thread_aggregate(items)
        plugin = _build_plugin(enabled=True)
        r1 = plugin.build_thread_summary(aggregate, conclusions=[])
        r2 = plugin.build_thread_summary(aggregate, conclusions=[])

        def _identity(mo):
            p = mo.payload
            return (
                p["command_family"],
                p["artifact_role"],
                p["scope_kind"],
                p["scope_ref"],
                p["artifact_normalized"],
            )

        ids1 = sorted(_identity(m) for m in r1.memory_objects if m.type == OPERATIONAL_FACT_TYPE)
        ids2 = sorted(_identity(m) for m in r2.memory_objects if m.type == OPERATIONAL_FACT_TYPE)
        assert ids1 == ids2


class TestRoutingTypeRegistration:
    def test_plugin_registers_operational_fact_type(self):
        from core.type_registry import TypeRegistry

        registry = TypeRegistry()
        plugin = _build_plugin(enabled=True)
        plugin.register_routing_types(registry)
        reg = registry.get(OPERATIONAL_FACT_TYPE)
        assert reg is not None
        assert reg.type_name == OPERATIONAL_FACT_TYPE
        assert reg.layer_name == OPERATIONAL_FACT_TYPE
        assert reg.block_text_field == "subject"
        assert reg.high_value is True

    def test_plugin_does_not_register_task_trace(self):
        # task_trace is retrieved via internal paths, not the standard
        # routing gate. Registering it would double-count in ranking.
        from core.type_registry import TypeRegistry

        registry = TypeRegistry()
        plugin = _build_plugin(enabled=True)
        plugin.register_routing_types(registry)
        assert registry.get(TASK_TRACE_TYPE) is None


class TestRetentionPolicy:
    def test_operational_fact_is_durable(self):
        plugin = _build_plugin(enabled=True)
        policy = plugin.memory_retention_policy
        assert OPERATIONAL_FACT_TYPE in policy.durable_types

    def test_task_trace_is_still_working(self):
        plugin = _build_plugin(enabled=True)
        policy = plugin.memory_retention_policy
        assert TASK_TRACE_TYPE in policy.working_types


class TestNonSupersedingTypes:
    """R2 regression pin: operational_fact must be excluded from the
    blanket rebuild-supersedes-prior sweep. Slot-scoped supersession is
    handled at the storage layer via the conflict-slot key, not the
    (type, schema_id) key the rebuild sweep uses.

    Without this exclusion, every thread rebuild would mark every prior
    active operational_fact in the rebuild window as `superseded`,
    regardless of whether it collides with a newly-derived candidate.
    """

    def test_operational_fact_excluded_from_rebuild_supersedes_prior(self):
        plugin = _build_plugin(enabled=True)
        assert plugin.rebuild_supersedes_prior is True
        assert OPERATIONAL_FACT_TYPE in plugin.non_superseding_types

    def test_task_trace_still_subject_to_rebuild_supersedes(self):
        plugin = _build_plugin(enabled=True)
        # task_trace intentionally NOT in non_superseding_types — its
        # thread-scoped summary is meant to be swept and rebuilt.
        assert TASK_TRACE_TYPE not in plugin.non_superseding_types


class TestConversionHelpers:
    def test_candidate_to_memory_object_populates_all_fields(self):
        cand = OperationalFactCandidate(
            command_family="python",
            artifact_role="interpreter",
            scope_kind="repo",
            scope_ref="git:example/repo",
            subject="python: .venv/bin/python",
            artifact=".venv/bin/python",
            artifact_normalized=".venv/bin/python",
            evidence=(
                DiscoveryEvent(
                    source_item_id="src-1", tool="Bash", turn_index=0,
                    timestamp="2026-07-01T12:00:00+00:00",
                    fragment="where python", artifact_raw=".venv/bin/python",
                    artifact_normalized=".venv/bin/python",
                ),
                UseEvent(
                    source_item_id="src-2", tool="Bash", turn_index=1,
                    timestamp="2026-07-01T12:01:00+00:00",
                    fragment=".venv/bin/python --version",
                ),
            ),
        )
        items = _seed_discovery_use_turns()
        aggregate = build_thread_aggregate(items)
        mem = _candidate_to_memory_object(cand, aggregate)
        assert mem.type == OPERATIONAL_FACT_TYPE
        assert mem.container_ref == aggregate.container_ref
        assert mem.payload["command_family"] == "python"
        assert mem.payload["artifact_role"] == "interpreter"
        assert "use_counters" in mem.payload

    def test_candidate_to_index_entry_text_view_contains_subject_and_artifact(self):
        cand = OperationalFactCandidate(
            command_family="uv",
            artifact_role="runner",
            scope_kind="repo",
            scope_ref="git:example/repo",
            subject="uv: pyproject.toml",
            artifact="pyproject.toml",
            artifact_normalized="pyproject.toml",
            evidence=(),
        )
        items = _seed_discovery_use_turns()
        aggregate = build_thread_aggregate(items)
        mem = _candidate_to_memory_object(cand, aggregate)
        ix = _candidate_to_index_entry(cand, mem)
        assert "uv: pyproject.toml" in ix.text_view
        assert "pyproject.toml" in ix.text_view
        assert "uv" in ix.text_view
        assert ix.text_view_name == OPERATIONAL_FACT_LEXICAL_TEXT_VIEW
        assert ix.target_id == mem.id


class TestFeatureFlagEnvOverride:
    """N8 non-blocking coverage: PALLIUM_FEATURES_OPERATIONAL_FACT_DERIVATION
    environment variable must take precedence over the TOML value.
    """

    def test_env_var_true_overrides_missing_toml(self, monkeypatch):
        from app.config import FeaturesConfig, _build_features_config

        monkeypatch.setenv(
            "PALLIUM_FEATURES_OPERATIONAL_FACT_DERIVATION", "true"
        )
        cfg = _build_features_config({}, {"PALLIUM_FEATURES_OPERATIONAL_FACT_DERIVATION": "true"})
        assert cfg.operational_fact_derivation is True

    def test_env_var_false_overrides_toml_true(self, monkeypatch):
        from app.config import _build_features_config

        cfg = _build_features_config(
            {"features": {"operational_fact_derivation": True}},
            {"PALLIUM_FEATURES_OPERATIONAL_FACT_DERIVATION": "false"},
        )
        assert cfg.operational_fact_derivation is False

    def test_default_is_false_when_neither_set(self):
        from app.config import _build_features_config

        cfg = _build_features_config({}, {})
        assert cfg.operational_fact_derivation is False

    def test_toml_true_no_env_yields_true(self):
        from app.config import _build_features_config

        cfg = _build_features_config(
            {"features": {"operational_fact_derivation": True}}, {}
        )
        assert cfg.operational_fact_derivation is True
