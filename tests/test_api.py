from __future__ import annotations

from fastapi.testclient import TestClient
import pytest

from app.config import AppConfig
from app.main import create_app
from providers.llm.base import LLMJsonResponse, LLMProviderError


class StubLLMProvider:
    def __init__(self, parsed_json: dict[str, object] | None = None, error: Exception | None = None) -> None:
        self._parsed_json = parsed_json
        self._error = error

    def generate_json(self, *, system_prompt: str, user_prompt: str, schema_description: str) -> LLMJsonResponse:
        if self._error is not None:
            raise self._error
        assert self._parsed_json is not None
        return LLMJsonResponse(
            raw_text=str(self._parsed_json),
            parsed_json=self._parsed_json,
        )


def test_post_items_creates_fallback_summary_artifacts(client) -> None:
    response = client.post(
        "/items",
        json={
            "source_type": "chat_thread",
            "source_id": "thread-123",
            "content_type": "text/plain",
            "content": "We should use event time for watermarking. It avoids skipped records.",
            "metadata": {"topic": "exports"},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["source_item_id"]
    assert len(payload["annotation_ids"]) == 1
    assert len(payload["memory_object_ids"]) == 1
    assert len(payload["relation_ids"]) == 1
    assert len(payload["index_entry_ids"]) == 2

    query_response = client.post(
        "/query",
        json={"text": "event time watermarking", "limit": 5},
    )
    assert query_response.status_code == 200
    memory_hits = [
        item for item in query_response.json()["results"] if item["result_kind"] == "memory_hit"
    ]
    assert any(item["type"] == "discussion_summary" for item in memory_hits)


def test_post_items_is_idempotent_on_source_reference(client) -> None:
    request = {
        "source_type": "decision_note",
        "source_id": "decision-1",
        "content_type": "text/plain",
        "content": "Decision: use event timestamp watermarking for exports to avoid skipped records.",
    }

    first_response = client.post("/items", json=request)
    second_response = client.post("/items", json=request)

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert len(first_response.json()["annotation_ids"]) == 2
    assert len(first_response.json()["memory_object_ids"]) == 1
    assert second_response.json() == first_response.json()


def test_post_query_returns_decision_memory_and_source_hits(client) -> None:
    client.post(
        "/items",
        json={
            "source_type": "decision_note",
            "source_id": "decision-1",
            "content_type": "text/plain",
            "content": "Decision: use event timestamp watermarking for exports to avoid skipped records during lag.",
        },
    )

    response = client.post(
        "/query",
        json={"text": "what did we decide about watermarking?", "limit": 5},
    )

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["results"]) >= 2
    result_kinds = {result["result_kind"] for result in payload["results"]}
    assert "memory_hit" in result_kinds
    assert "source_hit" in result_kinds

    memory_hit = next(result for result in payload["results"] if result["result_kind"] == "memory_hit")
    assert memory_hit["type"] == "decision"
    assert memory_hit["payload"]["decision"] == "use event timestamp watermarking for exports"
    assert memory_hit["payload"]["decision_evidence_text"] == "Decision: use event timestamp watermarking for exports to avoid skipped records during lag"
    assert memory_hit["payload"]["rationale"] == "to avoid skipped records during lag"
    assert len(memory_hit["evidence"]) == 1

    source_hit = next(result for result in payload["results"] if result["result_kind"] == "source_hit")
    assert source_hit["source_item_id"]
    assert source_hit["source_type"] == "decision_note"
    assert source_hit["source_id"] == "decision-1"
    assert source_hit["content"]


def test_llm_plugin_path_preserves_public_api_shape(monkeypatch, test_db_url: str) -> None:
    monkeypatch.setattr(
        "app.dependencies.build_llm_provider",
        lambda config: StubLLMProvider(
            {
                "summary": "Decision discussion about watermarking.",
                "candidate_type": "decision",
                "decision_text": "use event timestamp watermarking",
                "decision_evidence_text": "We decided to use event timestamp watermarking.",
                "rationale_text": "to avoid skipped records during lag",
            }
        ),
    )
    llm_client = TestClient(
        create_app(
            AppConfig(
                storage_backend="sqlite",
                sqlite_url=test_db_url,
                default_use_case="llm_agent_memory",
                llm_provider="openai_compatible",
                llm_model="fake-model",
                llm_base_url="http://fake-provider.local",
            )
        )
    )

    create_response = llm_client.post(
        "/items",
        json={
            "source_type": "decision_note",
            "source_id": "decision-llm-1",
            "content_type": "text/plain",
            "content": "An LLM should identify this as a decision about watermarking.",
        },
    )
    assert create_response.status_code == 200
    assert len(create_response.json()["annotation_ids"]) == 2

    query_response = llm_client.post(
        "/query",
        json={"text": "what did we decide about watermarking?", "limit": 5},
    )
    assert query_response.status_code == 200
    payload = query_response.json()
    memory_hit = next(result for result in payload["results"] if result["result_kind"] == "memory_hit")
    assert memory_hit["type"] == "decision"
    assert memory_hit["payload"]["decision"] == "use event timestamp watermarking"
    assert memory_hit["payload"]["decision_evidence_text"] == "We decided to use event timestamp watermarking."
    assert any(result["result_kind"] == "source_hit" for result in payload["results"])


def test_llm_plugin_path_returns_server_error_when_provider_fails(monkeypatch, test_db_url: str) -> None:
    monkeypatch.setattr(
        "app.dependencies.build_llm_provider",
        lambda config: StubLLMProvider(error=LLMProviderError("provider failed")),
    )
    llm_client = TestClient(
        create_app(
            AppConfig(
                storage_backend="sqlite",
                sqlite_url=test_db_url,
                default_use_case="llm_agent_memory",
                llm_provider="openai_compatible",
                llm_model="fake-model",
                llm_base_url="http://fake-provider.local",
            )
        ),
        raise_server_exceptions=False,
    )

    create_response = llm_client.post(
        "/items",
        json={
            "source_type": "decision_note",
            "source_id": "decision-llm-error-1",
            "content_type": "text/plain",
            "content": "Decision: use event timestamp watermarking for exports to avoid skipped records.",
        },
    )

    assert create_response.status_code == 500
