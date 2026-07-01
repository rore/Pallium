"""W5 PR 3 — shadow-wiring tests for ItemProcessor.

Focuses on the safe-wrapper contract:

- Flag off (provider=None) → no shadow rows, no side effects.
- Flag on + stub provider → shadow rows written to memory_objects_shadow.
- Shadow raises → live path unaffected; WARN logged.
- Shadow returns parse_status='llm_error' → marker row still written.
- Multi-package processing — shadow runs per plugin.
- Isolation — shadow write does not touch memory_objects / relations /
  index_entries beyond what the live path already wrote.

These tests exercise the private `_run_shadow_extraction_safely` +
`_build_shadow_rows` helpers directly; end-to-end coverage
(shadow-enabled full replay against narrow-target scenarios) lands
in W5 PR 4.
"""

from __future__ import annotations

import json
import logging

import pytest
from sqlalchemy import text

from core.models import SourceItem, new_id
from core.processing import ItemProcessor
from providers.llm.base import LLMJsonResponse, LLMProvider, LLMProviderError
from storage.sqlite import SQLiteStorageProvider


class StubProvider(LLMProvider):
    provider_name = "stub"
    provider_kind = "openai_compatible"
    model = "stub-model"

    def __init__(self, response: dict):
        self._response = response

    def generate_json(
        self, *, system_prompt: str, user_prompt: str, schema_description: str
    ) -> LLMJsonResponse:
        return LLMJsonResponse(
            raw_text=json.dumps(self._response),
            parsed_json=self._response,
        )


class ErrorProvider(LLMProvider):
    provider_name = "err-stub"
    provider_kind = "openai_compatible"
    model = "err-model"

    def __init__(self, exc: BaseException):
        self._exc = exc

    def generate_json(
        self, *, system_prompt: str, user_prompt: str, schema_description: str
    ) -> LLMJsonResponse:
        raise self._exc


def _source_item(content: str = "test") -> SourceItem:
    return SourceItem(
        source_type="claude-code",
        source_id=f"cc-{new_id()[:6]}",
        content_type="text/plain",
        content=content,
        container_ref="git:example/repo",
        thread_ref="thread-1",
        visibility="public",
    )


def _build_bare_processor(storage, shadow_llm_provider=None) -> ItemProcessor:
    """Build an ItemProcessor with the minimum stubs the tests need.

    We invoke only _run_shadow_extraction_safely + _build_shadow_rows,
    which don't touch the other constructor deps.
    """
    return ItemProcessor(
        storage=storage,
        semantic_plugins={},
        default_use_case="agent_conversation_memory",
        vector_embedder=None,
        thread_rebuilder=None,
        observability=None,
        persist_fn=lambda _r: None,
        supersede_fn=lambda _a, _b: None,
        get_item_processing_fn=lambda _i: None,
        shadow_llm_provider=shadow_llm_provider,
    )


@pytest.fixture
def storage(tmp_path):
    return SQLiteStorageProvider(
        database_url=f"sqlite:///{tmp_path / 'wiring.db'}"
    )


def _shadow_count(store) -> int:
    with store._engine.connect() as conn:
        return conn.execute(
            text("SELECT COUNT(*) FROM memory_objects_shadow")
        ).scalar() or 0


def _live_count(store, table: str) -> int:
    with store._engine.connect() as conn:
        return conn.execute(
            text(f"SELECT COUNT(*) FROM {table}")
        ).scalar() or 0


class TestFlagOff:
    def test_no_provider_no_shadow_rows(self, storage):
        processor = _build_bare_processor(storage, shadow_llm_provider=None)
        processor._run_shadow_extraction_safely(
            source_item=_source_item(), plugin_name="acm"
        )
        assert _shadow_count(storage) == 0

    def test_no_provider_does_not_touch_live_tables(self, storage):
        processor = _build_bare_processor(storage, shadow_llm_provider=None)
        before = (
            _live_count(storage, "memory_objects"),
            _live_count(storage, "relations"),
            _live_count(storage, "index_entries"),
            _live_count(storage, "source_items"),
        )
        processor._run_shadow_extraction_safely(
            source_item=_source_item(), plugin_name="acm"
        )
        after = (
            _live_count(storage, "memory_objects"),
            _live_count(storage, "relations"),
            _live_count(storage, "index_entries"),
            _live_count(storage, "source_items"),
        )
        assert before == after


class TestFlagOn:
    def test_happy_path_writes_shadow_rows(self, storage):
        provider = StubProvider({
            "decisions": [{
                "subject": "abstention gate",
                "statement": "use per-type thresholds",
                "evidence_span": "user said so",
            }],
            "investigations": [], "constraints": [],
            "operational_facts": [], "supersessions": [],
        })
        processor = _build_bare_processor(storage, shadow_llm_provider=provider)
        processor._run_shadow_extraction_safely(
            source_item=_source_item(), plugin_name="acm"
        )
        assert _shadow_count(storage) == 1

    def test_five_types_produce_five_rows(self, storage):
        provider = StubProvider({
            "decisions": [{"subject": "s", "statement": "st", "evidence_span": "e"}],
            "investigations": [{
                "subject": "s", "hypothesis": "h", "outcome": "confirmed",
                "evidence_span": "e",
            }],
            "constraints": [{
                "subject": "s", "modality": "require", "action": "use_surface",
                "statement": "st", "evidence_span": "e",
            }],
            "operational_facts": [{
                "command_family": "python", "subject": "s", "artifact": "a",
                "evidence_span": "e",
            }],
            "supersessions": [{
                "subject": "s", "supersedes_statement": "old",
                "new_statement": "new", "evidence_span": "e",
            }],
        })
        processor = _build_bare_processor(storage, shadow_llm_provider=provider)
        processor._run_shadow_extraction_safely(
            source_item=_source_item(), plugin_name="acm"
        )
        with storage._engine.connect() as conn:
            types = {
                r[0]
                for r in conn.execute(
                    text("SELECT DISTINCT type FROM memory_objects_shadow")
                ).fetchall()
            }
        assert types == {
            "decision", "investigation_outcome", "constraint_memory",
            "operational_fact", "supersession",
        }

    def test_container_and_visibility_propagate(self, storage):
        provider = StubProvider({
            "decisions": [{"subject": "s", "statement": "st", "evidence_span": "e"}],
            "investigations": [], "constraints": [],
            "operational_facts": [], "supersessions": [],
        })
        processor = _build_bare_processor(storage, shadow_llm_provider=provider)
        item = _source_item()
        processor._run_shadow_extraction_safely(
            source_item=item, plugin_name="acm"
        )
        with storage._engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT container_ref, visibility, package_name "
                    "FROM memory_objects_shadow"
                )
            ).one()
        assert row.container_ref == item.container_ref
        assert row.visibility == item.visibility
        assert row.package_name == "acm"

    def test_provider_metadata_recorded_on_row(self, storage):
        provider = StubProvider({
            "decisions": [{"subject": "s", "statement": "st", "evidence_span": "e"}],
            "investigations": [], "constraints": [],
            "operational_facts": [], "supersessions": [],
        })
        processor = _build_bare_processor(storage, shadow_llm_provider=provider)
        processor._run_shadow_extraction_safely(
            source_item=_source_item(), plugin_name="acm"
        )
        with storage._engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT provider_name, provider_kind, model, prompt_version "
                    "FROM memory_objects_shadow"
                )
            ).one()
        assert row.provider_name == "stub"
        assert row.provider_kind == "openai_compatible"
        assert row.model == "stub-model"
        assert row.prompt_version == "typed_shadow_v1"


class TestShadowRaisesLivePathUnaffected:
    def test_provider_raises_llm_error_writes_marker_row(self, storage, caplog):
        provider = ErrorProvider(LLMProviderError("simulated timeout"))
        processor = _build_bare_processor(storage, shadow_llm_provider=provider)
        # No exception should propagate.
        processor._run_shadow_extraction_safely(
            source_item=_source_item(), plugin_name="acm"
        )
        # Marker row written so the eval can measure failure rate.
        with storage._engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT parse_status, parse_error FROM memory_objects_shadow"
                )
            ).fetchall()
        assert len(rows) == 1
        assert rows[0].parse_status == "llm_error"
        assert "simulated timeout" in (rows[0].parse_error or "")

    def test_unexpected_exception_in_extractor_dropped(self, storage, caplog):
        # Force a code-level failure INSIDE the safe-wrapper by using a
        # provider that raises a non-LLMProviderError. The extractor
        # catches this too (per PR 2 contract), returns parse_status=llm_error.
        provider = ErrorProvider(RuntimeError("something else"))
        processor = _build_bare_processor(storage, shadow_llm_provider=provider)
        processor._run_shadow_extraction_safely(
            source_item=_source_item(), plugin_name="acm"
        )
        with storage._engine.connect() as conn:
            rows = conn.execute(
                text("SELECT parse_status FROM memory_objects_shadow")
            ).fetchall()
        assert len(rows) == 1
        assert rows[0].parse_status == "llm_error"

    def test_storage_write_error_swallowed(self, storage, caplog):
        # Break storage's insert_shadow_extraction: monkey-patch to raise.
        provider = StubProvider({
            "decisions": [{"subject": "s", "statement": "st", "evidence_span": "e"}],
            "investigations": [], "constraints": [],
            "operational_facts": [], "supersessions": [],
        })
        processor = _build_bare_processor(storage, shadow_llm_provider=provider)

        def _boom(**_kw):
            raise RuntimeError("storage down")

        storage.insert_shadow_extraction = _boom
        # Must not raise.
        with caplog.at_level(logging.WARNING):
            processor._run_shadow_extraction_safely(
                source_item=_source_item(), plugin_name="acm"
            )
        assert any("shadow_extraction_dropped" in r.message for r in caplog.records)


class TestIsolation:
    def test_shadow_only_touches_shadow_table(self, storage):
        provider = StubProvider({
            "decisions": [{"subject": "s", "statement": "st", "evidence_span": "e"}],
            "investigations": [], "constraints": [],
            "operational_facts": [], "supersessions": [],
        })
        processor = _build_bare_processor(storage, shadow_llm_provider=provider)
        before = (
            _live_count(storage, "memory_objects"),
            _live_count(storage, "relations"),
            _live_count(storage, "index_entries"),
        )
        processor._run_shadow_extraction_safely(
            source_item=_source_item(), plugin_name="acm"
        )
        after = (
            _live_count(storage, "memory_objects"),
            _live_count(storage, "relations"),
            _live_count(storage, "index_entries"),
        )
        assert before == after
        assert _shadow_count(storage) == 1

    def test_storage_without_insert_shadow_no_op(self, storage, monkeypatch):
        # A storage backend that doesn't expose insert_shadow_extraction
        # (e.g. a hypothetical non-SQLite backend) must not raise.
        provider = StubProvider({
            "decisions": [{"subject": "s", "statement": "st", "evidence_span": "e"}],
            "investigations": [], "constraints": [],
            "operational_facts": [], "supersessions": [],
        })
        processor = _build_bare_processor(storage, shadow_llm_provider=provider)
        # Use monkeypatch (auto-restore) instead of `del` on the class.
        monkeypatch.setattr(
            storage, "insert_shadow_extraction", None, raising=False
        )
        # None triggers the getattr(...) fallback path in the wrapper —
        # method is absent from the instance.
        # But getattr will now return None, not raise AttributeError, so
        # the wrapper's `if insert is None: return` branch handles it.
        processor._run_shadow_extraction_safely(
            source_item=_source_item(), plugin_name="acm"
        )
        # No rows written — the guard returned early.
        assert _shadow_count(storage) == 0


class TestBuildShadowRows:
    def test_empty_extraction_no_rows(self, storage):
        provider = StubProvider({
            "decisions": [], "investigations": [], "constraints": [],
            "operational_facts": [], "supersessions": [],
        })
        processor = _build_bare_processor(storage, shadow_llm_provider=provider)
        processor._run_shadow_extraction_safely(
            source_item=_source_item(), plugin_name="acm"
        )
        assert _shadow_count(storage) == 0

    def test_shadow_run_id_shared_across_rows(self, storage):
        provider = StubProvider({
            "decisions": [
                {"subject": f"s-{i}", "statement": f"st-{i}", "evidence_span": f"e-{i}"}
                for i in range(3)
            ],
            "investigations": [], "constraints": [],
            "operational_facts": [], "supersessions": [],
        })
        processor = _build_bare_processor(storage, shadow_llm_provider=provider)
        processor._run_shadow_extraction_safely(
            source_item=_source_item(), plugin_name="acm"
        )
        with storage._engine.connect() as conn:
            run_ids = {
                r[0]
                for r in conn.execute(
                    text("SELECT shadow_run_id FROM memory_objects_shadow")
                ).fetchall()
            }
        assert len(run_ids) == 1

    def test_two_calls_produce_two_run_ids(self, storage):
        provider = StubProvider({
            "decisions": [{"subject": "s", "statement": "st", "evidence_span": "e"}],
            "investigations": [], "constraints": [],
            "operational_facts": [], "supersessions": [],
        })
        processor = _build_bare_processor(storage, shadow_llm_provider=provider)
        processor._run_shadow_extraction_safely(
            source_item=_source_item(), plugin_name="acm"
        )
        processor._run_shadow_extraction_safely(
            source_item=_source_item(), plugin_name="acm"
        )
        with storage._engine.connect() as conn:
            run_ids = {
                r[0]
                for r in conn.execute(
                    text("SELECT shadow_run_id FROM memory_objects_shadow")
                ).fetchall()
            }
        assert len(run_ids) == 2

    def test_marker_row_written_on_total_failure(self, storage):
        provider = ErrorProvider(LLMProviderError("boom"))
        processor = _build_bare_processor(storage, shadow_llm_provider=provider)
        processor._run_shadow_extraction_safely(
            source_item=_source_item(), plugin_name="acm"
        )
        with storage._engine.connect() as conn:
            types = [
                r[0]
                for r in conn.execute(
                    text("SELECT type FROM memory_objects_shadow")
                ).fetchall()
            ]
        assert types == ["_shadow_marker"]
