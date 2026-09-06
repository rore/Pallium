"""Release gates for raw Session History/package decoupling.

These are deliberately small public-lifecycle tests.  Gate A proves that
configured provider/model settings do not activate a disabled package; Gate B
proves explicit activation still runs the existing derived lifecycle.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import timedelta
import importlib.util
import json
import sys
from pathlib import Path

import httpx
import pytest
from sqlalchemy import text
from starlette.testclient import TestClient

from app.config import (
    AppConfig, EmbeddingProviderConfig, LLMProviderConfig, RetentionConfig,
    SemanticPackageConfig,
)
from app.main import create_app
from app.mcp.client import PalliumMcpClient
from app.mcp.context import PalliumContext
from app.mcp.server import create_server
from providers.llm.base import LLMJsonResponse
from tests.config_helpers import build_llm_test_config
from tests.test_source_item_embedding import FakeEmbeddingProvider
from tests.tiered_memory_stub_providers import TieredMemorySemanticProvider
from storage.vector_index import VectorIndexConfig


CONTAINER = "git:example.test/release-gate"
THREAD = "session:raw-derived"
VISIBILITY = "private"


def _disabled_config(db_url: str, *, vector_path: Path | None = None) -> AppConfig:
    """Provider/model are configured, but no semantic package is enabled."""
    return AppConfig(
        storage_backend="sqlite",
        sqlite_url=db_url,
        default_use_case="agent_conversation_memory",
        retention=RetentionConfig(enabled=True),
        llm_providers={
            "configured-but-off": LLMProviderConfig(
                name="configured-but-off",
                kind="openai_compatible",
                base_url="http://provider.invalid",
                api_key="not-used",
            ),
        },
        embedding_providers=({
            "test": EmbeddingProviderConfig(name="test", kind="fastembed", model="test-embed")
        } if vector_path is not None else {}),
        vector_index=VectorIndexConfig(
            enabled=vector_path is not None,
            index_path=str(vector_path or "unused"),
            embedding_provider="test" if vector_path is not None else "",
        ),
        semantic_packages={
            "agent_conversation_memory": SemanticPackageConfig(
                name="agent_conversation_memory",
                implementation="agent_conversation_memory",
                enabled=False,
                llm_provider="configured-but-off",
                model="configured-model",
                prompt_variant="configured-prompt",
            ),
            "conversational_knowledge": SemanticPackageConfig(
                name="conversational_knowledge",
                implementation="conversational_knowledge",
                enabled=False,
                llm_provider="configured-but-off",
                model="configured-model",
            ),
        },
    )


class RecordingProvider:
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []
        self._delegate = TieredMemorySemanticProvider()

    def generate_json(
        self, *, system_prompt: str, user_prompt: str, schema_description: str
    ) -> LLMJsonResponse:
        self.calls.append(
            {
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "schema_description": schema_description,
            }
        )
        return self._delegate.generate_json(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            schema_description=schema_description,
        )


def _item(
    source_id: str,
    content: str,
    *,
    thread_ref: str = THREAD,
    visibility: str = VISIBILITY,
    role: str = "user",
    artifact_kind: str = "message",
    work_ref: str = "feature:history-gate",
) -> dict[str, object]:
    return {
        "source_type": "chat",
        "source_id": source_id,
        "content_type": "text/plain",
        "content": content,
        "artifact_kind": artifact_kind,
        "role": role,
        "container_ref": CONTAINER,
        "thread_ref": thread_ref,
        "visibility": visibility,
        "metadata": {"pallium_work_refs": [work_ref]},
    }


def _query_payload(text_value: str, *, source_only: bool = True, work_refs=None) -> dict[str, object]:
    payload: dict[str, object] = {
        "text": text_value,
        "limit": 5,
        "source_only": source_only,
        "trigger_origin": "agent_pull_work" if work_refs else "agent_pull",
        "container_ref": CONTAINER,
        "thread_ref": THREAD,
        "visibility": VISIBILITY,
    }
    if work_refs is not None:
        payload["work_refs"] = work_refs
    return payload


def _load_codex_hook():
    path = Path(__file__).resolve().parents[1] / "integrations/codex/hooks/user_prompt_submit.py"
    spec = importlib.util.spec_from_file_location("decouple_release_gate_codex_hook", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_gate_a_raw_history_has_no_semantic_activation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider_calls: list[object] = []

    def forbidden_provider(*_args, **_kwargs):
        provider_calls.append(True)
        raise AssertionError("disabled package constructed an LLM provider")

    monkeypatch.setattr("app.dependencies.build_llm_provider", forbidden_provider)
    embedding_provider = FakeEmbeddingProvider()
    monkeypatch.setattr(
        "app.dependencies.build_embedding_provider",
        lambda *_args, **_kwargs: embedding_provider,
    )
    app = create_app(
        _disabled_config(
            f"sqlite:///{tmp_path / 'raw.db'}", vector_path=tmp_path / "raw.index"
        )
    )
    client = TestClient(app)
    with client:
        start_events = client.app.state.metrics_store.query(
            category="system", event_type="service_start"
        )
        assert start_events
        assert start_events[0].payload == {"packages_enabled": []}

        first = client.post(
            "/items",
            json=[
                _item(
                    "raw-1",
                    "Unicode anchor: החלטה حفظ history without semantic packages.",
                )
            ],
        )
        assert first.status_code == 200, first.text
        source_id = first.json()[0]["source_item_id"]

        duplicate = client.post(
            "/items",
            json=[_item("raw-1", "Duplicate identity must not create another raw source row.")],
        )
        assert duplicate.status_code == 200, duplicate.text
        assert duplicate.json()[0]["source_item_id"] == source_id
        with client.app.state.pallium_service._storage._engine.connect() as conn:
            assert conn.execute(
                text("SELECT COUNT(*) FROM source_items WHERE source_type = 'chat' AND source_id = 'raw-1'")
            ).scalar_one() == 1

        invalid_payload = _item(
            "invalid-package",
            "An unsupported explicit package must not persist raw history.",
        )
        invalid_payload["use_case"] = "not-configured"
        with pytest.raises(ValueError, match="Unsupported use case"):
            client.post("/items", json=[invalid_payload])
        assert client.app.state.pallium_service._storage.find_source_item(
            source_type="chat", source_id="invalid-package"
        ) is None

        empty = client.post("/query", json=_query_payload(""))
        assert empty.status_code == 422, empty.text
        assert "text must be non-empty" in str(empty.json()["detail"])

        missing_container_payload = _query_payload("Unicode anchor history")
        missing_container_payload.pop("container_ref")
        missing_container = client.post("/query", json=missing_container_payload)
        assert missing_container.status_code == 200, missing_container.text
        assert missing_container.json()["decision_reason"] == "visibility_context_required"
        assert missing_container.json()["results"] == []

        missing_visibility_payload = _query_payload("Unicode anchor history")
        missing_visibility_payload.pop("visibility")
        missing_visibility = client.post("/query", json=missing_visibility_payload)
        assert missing_visibility.status_code == 200, missing_visibility.text
        assert missing_visibility.json()["decision_reason"] == "visibility_context_required"
        assert missing_visibility.json()["results"] == []

        limit_zero = client.post(
            "/query", json={**_query_payload("Unicode anchor history"), "limit": 0}
        )
        assert limit_zero.status_code == 422, limit_zero.text
        limit_max = client.post(
            "/query", json={**_query_payload("Unicode anchor history"), "limit": 50}
        )
        assert limit_max.status_code == 200, limit_max.text
        assert len(limit_max.json()["results"]) <= 50
        limit_over = client.post(
            "/query", json={**_query_payload("Unicode anchor history"), "limit": 51}
        )
        assert limit_over.status_code == 422, limit_over.text

        client.app.state.pallium_service.drain_processing_queue(worker_id="raw-gate")

        broad = client.post("/query", json=_query_payload("Unicode anchor history"))
        assert broad.status_code == 200, broad.text
        broad_body = broad.json()
        assert broad_body["decision_reason"] == "source_only_search"
        hit = next(row for row in broad_body["results"] if row["source_item_id"] == source_id)
        assert hit["work_refs"] == ["feature:history-gate"]
        assert "החלטה" in hit["excerpt"] or "history" in hit["excerpt"]

        vector_only = client.post(
            "/query", json=_query_payload("qzvx-semantic-only-probe")
        )
        assert vector_only.status_code == 200, vector_only.text
        assert source_id in {
            row["source_item_id"] for row in vector_only.json()["results"]
        }

        exact = client.post(
            "/query",
            json=_query_payload("", work_refs=["feature:history-gate"]),
        )
        assert exact.status_code == 200, exact.text
        assert exact.json()["results"][0]["source_item_id"] == source_id
        lookup_id = exact.json()["lookup_event_id"]

        expanded = client.get(
            f"/source/{source_id}/context",
            params={
                "container_ref": CONTAINER,
                "query_visibility": VISIBILITY,
                "active_session_ref": THREAD,
                "parent_lookup_id": lookup_id,
            },
        )
        assert expanded.status_code == 200, expanded.text
        assert expanded.json()["parent_lookup_id"] == lookup_id
        assert expanded.json()["items"][0]["source_item_id"] == source_id

        # Privacy must hold for an active private source before any mutation too.
        active_isolated = client.post(
            "/query",
            json={**_query_payload("Unicode anchor history"), "container_ref": "other-container"},
        )
        assert active_isolated.status_code == 200, active_isolated.text
        assert source_id not in {row["source_item_id"] for row in active_isolated.json()["results"]}

        # The public mutation contract is source forget; retrieval must hide it.
        forgotten = client.post(
            "/source/forget",
            json={"source_item_id": source_id, "reason": "release-gate"},
        )
        assert forgotten.status_code == 200, forgotten.text
        with client.app.state.pallium_service._storage._engine.connect() as conn:
            forgotten_at = conn.execute(
                text("SELECT forgotten_at FROM source_items WHERE id = :source_id"),
                {"source_id": source_id},
            ).scalar_one()
        assert forgotten_at is not None
        hidden = client.post("/query", json=_query_payload("Unicode anchor history"))
        assert hidden.status_code == 200, hidden.text
        assert source_id not in {row["source_item_id"] for row in hidden.json()["results"]}

        # A different container cannot read the forgotten/private source.
        isolated = client.post(
            "/query",
            json={**_query_payload("Unicode anchor history"), "container_ref": "other-container"},
        )
        assert isolated.status_code == 200, isolated.text
        assert isolated.json()["results"] == []

        # Retention hard-deletes expired raw evidence and its indexes without a package.
        stored = client.app.state.pallium_service._storage.get_source_item(source_id)
        retention = client.app.state.pallium_service.run_retention_pass(
            worker_id="raw-retention-gate",
            now=stored.created_at + timedelta(days=31),
        )
        assert retention is not None and retention.deleted_source_items == 1
        with pytest.raises(KeyError):
            client.app.state.pallium_service._storage.get_source_item(source_id)
        assert client.app.state.pallium_service._storage.list_index_entries_for_target(
            "source_item", source_id
        ) == []
        deleted = client.get(
            f"/source/{source_id}/context",
            params={"container_ref": CONTAINER, "query_visibility": VISIBILITY},
        )
        assert deleted.status_code == 404
        # Hook path uses the same public /item-and-query surface.
        hook = _load_codex_hook()
        emitted: list[tuple[str, str]] = []
        hook.read_hook_input = lambda: {
            "cwd": str(tmp_path),
            "session_id": "hook-session",
            "prompt": "Hook Unicode turn: حفظ raw history and keep feature gate evidence.",
        }
        hook.resolve_container_ref = lambda *_args: CONTAINER
        hook.derive_actor_ref = lambda: "hook-actor"
        hook.get_pending_relay_closes = lambda *_args: []
        hook.pin_container = lambda *_args, **_kwargs: None
        hook.discover_work_refs = lambda *_args: hook._common.WorkRefDiscovery(
            ("feature:hook-gate",)
        )
        hook.build_work_refs_metadata = lambda *_args, **_kwargs: {
            "pallium_work_refs": ["feature:hook-gate"]
        }
        hook.relay_request = lambda *_args, **_kwargs: {"deliveries": [], "has_more": False}
        hook.check_dedup = lambda *_args: False
        hook.emit_context = lambda text_value, event: emitted.append((text_value, event))

        def hook_request(method, path, payload, **_kwargs):
            response = client.request(method, path, json=payload)
            assert response.status_code == 200, response.text
            return response.json()

        hook.pallium_request = hook_request
        with pytest.raises(SystemExit) as exited:
            hook.main()
        assert exited.value.code == 0
        assert emitted and emitted[0][1] == "UserPromptSubmit"

        client.app.state.pallium_service.drain_processing_queue(worker_id="raw-gate")
        assert provider_calls == []
        with client.app.state.pallium_service._storage._engine.connect() as conn:
            statuses = conn.execute(
                text("SELECT processing_status FROM source_items WHERE container_ref = :container"),
                {"container": CONTAINER},
            ).scalars().all()
        assert statuses and set(statuses) <= {"completed", "skipped"}
        with client.app.state.pallium_service._storage._engine.connect() as conn:
            rows = conn.execute(
                text("SELECT content, metadata_json FROM source_items WHERE container_ref = :container"),
                {"container": CONTAINER},
            ).mappings().all()
        assert any("Hook Unicode turn" in row["content"] and "feature:hook-gate" in row["metadata_json"] for row in rows)
        assert client.app.state.pallium_service._storage.list_memory_objects() == []
        with client.app.state.pallium_service._storage._engine.connect() as conn:
            assert conn.execute(text("SELECT COUNT(*) FROM package_processing_status")).scalar() == 0

        # MCP client + tool surface are wired to the same ASGI app and retain scope.
        async def exercise_mcp() -> None:
            async def asgi_post(_self, path, payload):
                transport = httpx.ASGITransport(app=app)
                async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http:
                    response = await http.post(path, json=payload)
                    response.raise_for_status()
                    return response.json()

            async def asgi_context(_self, source_item_id, **kwargs):
                params = {"container_ref": CONTAINER, "query_visibility": VISIBILITY}
                if kwargs.get("parent_lookup_id"):
                    params["parent_lookup_id"] = kwargs["parent_lookup_id"]
                transport = httpx.ASGITransport(app=app)
                async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http:
                    response = await http.get(f"/source/{source_item_id}/context", params=params)
                    response.raise_for_status()
                    return response.json()

            monkeypatch.setattr(PalliumMcpClient, "_post", asgi_post)
            monkeypatch.setattr(PalliumMcpClient, "get_source_context", asgi_context)
            ctx = PalliumContext(
                base_url="http://testserver",
                container_ref=CONTAINER,
                thread_ref=THREAD,
                visibility=VISIBILITY,
            )
            mcp = PalliumMcpClient(ctx)
            ingested = await mcp.ingest(
                "MCP raw-only anchor: 保留 history without package derivation.",
                source_id="mcp-raw",
                artifact_kind="message",
                role="user",
            )
            assert ingested["source_item_id"]
            await mcp.search_history("MCP raw-only anchor")
            exact_mcp = await mcp.search_history_by_work_ref("feature:history-gate")
            assert exact_mcp["results"] == []  # MCP item has no work-ref metadata.
            monkeypatch.setenv("PALLIUM_BASE_URL", "http://testserver")
            tool_server = create_server()
            content, _ = await tool_server.call_tool(
                "pallium_search_history",
                {
                    "query": "MCP raw-only anchor",
                    "container_ref": CONTAINER,
                    "thread_ref": THREAD,
                    "visibility": VISIBILITY,
                },
            )
            tool_result = json.loads(content[0].text)
            assert tool_result["results"]
            assert tool_result["results"][0]["source_item_id"] == ingested["source_item_id"]

        asyncio.run(exercise_mcp())
        assert provider_calls == []
        assert client.app.state.pallium_service._storage.list_memory_objects() == []
        with client.app.state.pallium_service._storage._engine.connect() as conn:
            assert conn.execute(text("SELECT COUNT(*) FROM package_processing_status")).scalar() == 0


def test_gate_b_explicit_package_restores_derived_lifecycle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = RecordingProvider()
    monkeypatch.setattr("app.dependencies.build_llm_provider", lambda *_args, **_kwargs: provider)
    config = build_llm_test_config(
        default_use_case="agent_conversation_memory",
        sqlite_url=f"sqlite:///{tmp_path / 'derived.db'}",
    )
    # Exactly one semantic package is enabled; configured providers alone are inert.
    packages = {
        name: replace(package, enabled=(name == "agent_conversation_memory"))
        for name, package in config.semantic_packages.items()
    }
    embedding_provider = FakeEmbeddingProvider()
    monkeypatch.setattr(
        "app.dependencies.build_embedding_provider",
        lambda *_args, **_kwargs: embedding_provider,
    )
    config = replace(
        config,
        semantic_packages=packages,
        embedding_providers={
            "test": EmbeddingProviderConfig(name="test", kind="fastembed", model="test-embed"),
        },
        vector_index=VectorIndexConfig(
            enabled=True,
            index_path=str(tmp_path / "derived.index"),
            embedding_provider="test",
            min_similarity=0.0,
        ),
    )
    assert [name for name, package in config.semantic_packages.items() if package.enabled] == [
        "agent_conversation_memory"
    ]
    app = create_app(config)
    client = TestClient(app)
    with client:
        for thread, source_id, content in (
            (THREAD, "derived-1", "Decision: preserve raw history while enabling deterministic package extraction."),
            (THREAD, "derived-2", "Investigation found that package opt-in creates derived retrieval alongside raw history."),
            ("session:raw-derived-2", "derived-3", "Decision: preserve raw history and verify rebuild across threads."),
        ):
            response = client.post(
                "/items",
                json=[_item(source_id, content, thread_ref=thread, visibility="public")],
            )
            assert response.status_code == 200, response.text
        service = client.app.state.pallium_service
        while service.process_next_source_item(worker_id="derived-gate") is not None:
            pass

        rebuild_runs = 0
        while service.process_next_thread_rebuild(worker_id="derived-gate") is not None:
            rebuild_runs += 1
        assert rebuild_runs >= 1

        assert provider.calls, "explicit enabled=true must invoke the deterministic provider"
        assert any("Thread items:" in call["user_prompt"] for call in provider.calls)
        memories = client.app.state.pallium_service._storage.list_memory_objects(
            container_ref=CONTAINER,
        )
        memory_types = {memory.type for memory in memories}
        assert {"decision", "investigation_outcome"} & memory_types
        assert "thread_summary" in memory_types

        raw = client.post(
            "/query",
            json={
                **_query_payload("preserve raw history", source_only=True),
                "visibility": "public",
            },
        )
        assert raw.status_code == 200, raw.text
        assert any(row["result_kind"] == "source_hit" for row in raw.json()["results"])

        derived = client.post(
            "/query",
            json={
                **_query_payload("qzvx-derived-vector-only", source_only=False),
                "visibility": "public",
            },
        )
        assert derived.status_code == 200, derived.text
        derived_results = derived.json()["results"]
        assert any(row["result_kind"] == "source_hit" for row in derived_results), (
            "raw source history must coexist with derived retrieval"
        )
        memory_hit = next(
            row for row in derived_results if row["result_kind"] == "memory_hit"
        )
        assert memory_hit["retrieval_source"] in {"vector", "both"}
        assert embedding_provider.embed_calls, "Gate B must exercise the deterministic vector provider"
        expanded = client.get(f"/memory/{memory_hit['memory_object_id']}/expand", params={"container_ref": CONTAINER})
        assert expanded.status_code == 200, expanded.text
        assert expanded.json()["items"]
        assert expanded.json()["payload"]

        calls_before_consolidation = len(provider.calls)
        consolidation = client.app.state.pallium_service.run_consolidation_pass(
            use_case="agent_conversation_memory",
            container_ref=CONTAINER,
        )
        assert consolidation is not None or len(provider.calls) > calls_before_consolidation
        final_types = {
            memory.type
            for memory in client.app.state.pallium_service._storage.list_memory_objects(
                container_ref=CONTAINER,
            )
        }
        assert final_types & {"pattern_memory", "continuity_memory"}
        with client.app.state.pallium_service._storage._engine.connect() as conn:
            assert conn.execute(
                text("SELECT COUNT(*) FROM package_processing_status WHERE package_name = 'agent_conversation_memory'")
            ).scalar() >= 3

def test_gate_c_restart_lifecycle_does_not_retroactively_process_disabled_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_url = f"sqlite:///{tmp_path / 'restart.db'}"
    enabled_config = build_llm_test_config(
        default_use_case="agent_conversation_memory", sqlite_url=db_url
    )
    first_provider = RecordingProvider()
    monkeypatch.setattr(
        "app.dependencies.build_llm_provider",
        lambda *_args, **_kwargs: first_provider,
    )

    enabled_app = create_app(enabled_config)
    with TestClient(enabled_app) as client:
        response = client.post(
            "/items",
            json=[
                _item(
                    "restart-enabled",
                    "Decision: retain completed derived history across clean restarts.",
                    visibility="public",
                )
            ],
        )
        assert response.status_code == 200, response.text
        service = client.app.state.pallium_service
        service.drain_processing_queue(worker_id="restart-enabled")
        original_memories = service._storage.list_memory_objects_for_source_item(
            response.json()[0]["source_item_id"]
        )
        assert original_memories
        original_ids = {memory.id for memory in original_memories}

    disabled_provider_calls: list[object] = []

    def forbidden_provider(*_args, **_kwargs):
        disabled_provider_calls.append(True)
        raise AssertionError("disabled restart constructed an LLM provider")

    monkeypatch.setattr("app.dependencies.build_llm_provider", forbidden_provider)
    disabled_app = create_app(_disabled_config(db_url))
    with TestClient(disabled_app) as client:
        response = client.post(
            "/items",
            json=[
                _item(
                    "restart-disabled",
                    "Decision: this middle source must remain raw while packages are disabled.",
                    visibility="public",
                )
            ],
        )
        assert response.status_code == 200, response.text
        middle_id = response.json()[0]["source_item_id"]
        service = client.app.state.pallium_service
        service.drain_processing_queue(worker_id="restart-disabled")

        raw = client.post(
            "/query",
            json={
                **_query_payload("middle source remain raw", source_only=True),
                "visibility": "public",
            },
        )
        assert raw.status_code == 200, raw.text
        assert middle_id in {row["source_item_id"] for row in raw.json()["results"]}

        unavailable = client.post(
            "/query",
            json={
                **_query_payload("middle source remain raw", source_only=False),
                "visibility": "public",
            },
        )
        assert unavailable.status_code == 200, unavailable.text
        unavailable_body = unavailable.json()
        assert unavailable_body["decision_reason"] == "semantic_package_unavailable"
        assert unavailable_body["should_inject"] is False
        assert unavailable_body["injectable_blocks"] == []
        assert disabled_provider_calls == []
        assert original_ids <= {memory.id for memory in service._storage.list_memory_objects()}
        assert service._storage.list_memory_objects_for_source_item(middle_id) == []
        with service._storage._engine.connect() as conn:
            assert conn.execute(
                text(
                    "SELECT COUNT(*) FROM package_processing_status "
                    "WHERE source_item_id = :source_id"
                ),
                {"source_id": middle_id},
            ).scalar() == 0

    final_provider = RecordingProvider()
    monkeypatch.setattr(
        "app.dependencies.build_llm_provider",
        lambda *_args, **_kwargs: final_provider,
    )
    final_app = create_app(enabled_config)
    with TestClient(final_app) as client:
        response = client.post(
            "/items",
            json=[
                _item(
                    "restart-reenabled",
                    "Decision: derive only newly ingested sources after package re-enable.",
                    visibility="public",
                )
            ],
        )
        assert response.status_code == 200, response.text
        new_id = response.json()[0]["source_item_id"]
        service = client.app.state.pallium_service
        service.drain_processing_queue(worker_id="restart-reenabled")

        new_memories = service._storage.list_memory_objects_for_source_item(new_id)
        assert new_memories
        assert service._storage.list_memory_objects_for_source_item(middle_id) == [], (
            "re-enable retroactively derived a memory supported by the disabled middle source"
        )
        assert original_ids <= {memory.id for memory in service._storage.list_memory_objects()}
        assert any(
            "derive only newly ingested sources" in call["user_prompt"]
            for call in final_provider.calls
        )
        assert all(
            "middle source must remain raw" not in call["user_prompt"]
            for call in final_provider.calls
        )
        with service._storage._engine.connect() as conn:
            assert conn.execute(
                text(
                    "SELECT COUNT(*) FROM package_processing_status "
                    "WHERE source_item_id = :source_id"
                ),
                {"source_id": new_id},
            ).scalar() >= 1
            assert conn.execute(
                text(
                    "SELECT COUNT(*) FROM package_processing_status "
                    "WHERE source_item_id = :source_id"
                ),
                {"source_id": middle_id},
            ).scalar() == 0

    second_disabled_provider_calls: list[object] = []

    def forbidden_second_provider(*_args, **_kwargs):
        second_disabled_provider_calls.append(True)
        raise AssertionError("second disabled restart constructed an LLM provider")

    monkeypatch.setattr("app.dependencies.build_llm_provider", forbidden_second_provider)
    second_disabled_app = create_app(_disabled_config(db_url))
    with TestClient(second_disabled_app) as client:
        response = client.post(
            "/items",
            json=[
                _item(
                    "restart-disabled-2",
                    "Decision: the second disabled period remains raw and unprocessed.",
                    visibility="public",
                )
            ],
        )
        assert response.status_code == 200, response.text
        second_disabled_id = response.json()[0]["source_item_id"]
        service = client.app.state.pallium_service
        service.drain_processing_queue(worker_id="restart-disabled-2")
        raw = client.post(
            "/query",
            json={
                **_query_payload("second disabled period remains raw", source_only=True),
                "visibility": "public",
            },
        )
        assert raw.status_code == 200, raw.text
        assert second_disabled_id in {row["source_item_id"] for row in raw.json()["results"]}
        assert service._storage.list_memory_objects_for_source_item(second_disabled_id) == []
        with service._storage._engine.connect() as conn:
            assert conn.execute(
                text(
                    "SELECT COUNT(*) FROM package_processing_status "
                    "WHERE source_item_id = :source_id"
                ),
                {"source_id": second_disabled_id},
            ).scalar() == 0
        assert second_disabled_provider_calls == []

    second_provider = RecordingProvider()
    monkeypatch.setattr(
        "app.dependencies.build_llm_provider",
        lambda *_args, **_kwargs: second_provider,
    )
    second_enabled_app = create_app(enabled_config)
    with TestClient(second_enabled_app) as client:
        response = client.post(
            "/items",
            json=[
                _item(
                    "restart-reenabled-2",
                    "Decision: derive only sources ingested after the second re-enable.",
                    visibility="public",
                )
            ],
        )
        assert response.status_code == 200, response.text
        second_new_id = response.json()[0]["source_item_id"]
        service = client.app.state.pallium_service
        service.drain_processing_queue(worker_id="restart-reenabled-2")
        assert service._storage.list_memory_objects_for_source_item(second_new_id)
        assert service._storage.list_memory_objects_for_source_item(second_disabled_id) == []
        assert original_ids <= {memory.id for memory in service._storage.list_memory_objects()}
        assert any(
            "derive only sources ingested after the second re-enable" in call["user_prompt"]
            for call in second_provider.calls
        )
        assert all(
            "second disabled period remains raw" not in call["user_prompt"]
            for call in second_provider.calls
        )
