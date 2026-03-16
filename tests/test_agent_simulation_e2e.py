from __future__ import annotations

from dataclasses import dataclass

from fastapi.testclient import TestClient

from app.agent_simulation import AgentSimulationApp, TerminalIO
from app.main import create_app
from tests.config_helpers import build_llm_test_config
from tests.stub_providers import TieredMemorySemanticProvider


class FakeIO:
    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.outputs: list[str] = []

    def prompt(self, text: str) -> str:
        self.outputs.append(text)
        if not self._responses:
            raise AssertionError(f"unexpected prompt: {text}")
        return self._responses.pop(0)

    def write(self, text: str) -> None:
        self.outputs.append(text)


class HarnessHttpFromTestClient:
    def __init__(self, client: TestClient) -> None:
        self.base_url = "http://testserver"
        self._client = client

    def create_item(self, payload):
        response = self._client.post("/items", json=payload)
        assert response.status_code == 200
        return response.json()

    def query(self, payload):
        response = self._client.post("/query", json=payload)
        assert response.status_code == 200
        return response.json()

    def query_debug(self, payload):
        response = self._client.post("/query/debug", json=payload)
        assert response.status_code == 200
        return response.json()

    def close(self):
        return None


@dataclass(frozen=True)
class FakeResolution:
    def to_dict(self):
        return {"available": True, "provider_name": "fake", "provider_kind": "openai_compatible", "model": "fake-model", "failure_reason": None}


@dataclass(frozen=True)
class FakeDraft:
    answer: str
    model_request: dict
    model_response: dict
    resolution: FakeResolution


class CapturingModel:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self._resolution = FakeResolution()

    def resolution(self):
        return self._resolution

    def draft_answer(self, *, user_message: str, injectable_blocks: list[dict]):
        self.calls.append({"user_message": user_message, "injectable_blocks": injectable_blocks})
        return FakeDraft(
            answer="Final draft",
            model_request={"injectable_blocks": injectable_blocks},
            model_response={"parsed_json": {"answer": "Final draft"}},
            resolution=self._resolution,
        )


def test_chat_mode_uses_real_items_and_query_debug_contract(monkeypatch, test_db_url: str) -> None:
    monkeypatch.setattr("app.dependencies.build_llm_provider", lambda config, **_: TieredMemorySemanticProvider())
    client = TestClient(create_app(build_llm_test_config(default_use_case="agent_conversation_memory", sqlite_url=test_db_url)))

    for payload in (
        {
            "source_type": "assistant_artifact",
            "source_id": "history-decision-1",
            "content_type": "text/plain",
            "content": "Decision: use item event time for reservation ordering to avoid missed hold updates during sync delays.",
            "artifact_kind": "assistant_output",
            "role": "assistant",
            "container_ref": "chat:ops",
            "thread_ref": "chat:ops:history",
            "session_ref": "session:history",
            "visibility_context": {"kind": "public", "id": None},
        },
        {
            "source_type": "assistant_artifact",
            "source_id": "history-investigation-1",
            "content_type": "text/plain",
            "content": "Investigation found that arrival-time ordering missed hold updates during sync delays.",
            "artifact_kind": "tool_use_summary",
            "role": "assistant",
            "container_ref": "chat:ops",
            "thread_ref": "chat:ops:history",
            "session_ref": "session:history",
            "visibility_context": {"kind": "public", "id": None},
        },
    ):
        assert client.post("/items", json=payload).status_code == 200

    client.app.state.pallium_service.drain_processing_queue(worker_id="agent-simulation-e2e")

    io = FakeIO(["a", "n"])
    model = CapturingModel()
    harness = AgentSimulationApp(
        http_client=HarnessHttpFromTestClient(client),
        io=TerminalIO(input_func=io.prompt, output_func=io.write),
        model=model,
    )
    harness.session.defaults.container_ref = "chat:ops"
    harness.session.defaults.thread_ref = "chat:ops:fresh"
    harness.session.defaults.session_ref = "session:fresh"
    harness.session.defaults.visibility_context = {"kind": "public", "id": None}
    harness.session.defaults.runtime_context["turn_kind"] = "new_thread"
    harness.session.defaults.runtime_context["session_has_sufficient_local_context"] = False

    harness.process_chat_message("Why did we choose item event time for reservation ordering?")

    event = harness.session.events[0]
    query_request = event["query_debug"]["request"]
    query_response = event["query_debug"]["response"]
    user_request = event["user_item"]["request"]
    assistant_request = event["assistant"]["request"]

    assert user_request["artifact_kind"] == "message"
    assert user_request["role"] == "user"
    assert query_request["text"] == "Why did we choose item event time for reservation ordering?"
    assert query_request["container_ref"] == "chat:ops"
    assert query_request["thread_ref"] == "chat:ops:fresh"
    assert query_request["runtime_context"] == {
        "turn_kind": "new_thread",
        "session_has_sufficient_local_context": False,
    }
    assert query_response["should_inject"] is True
    assert query_response["injectable_blocks"]
    assert model.calls[0]["injectable_blocks"] == query_response["injectable_blocks"]
    assert assistant_request["artifact_kind"] == "assistant_output"
    assert assistant_request["role"] == "assistant"
    assert "raw candidate" not in str(event["model"]["request"])
