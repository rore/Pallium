from __future__ import annotations

from dataclasses import dataclass

from fastapi.testclient import TestClient

from app.agent_simulation import AgentSimulationApp, TerminalIO
from app.main import create_app
from tests.config_helpers import build_llm_test_config
from tests.public_corpus_stub_providers import PublicCorpusSemanticProvider
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
        return {
            "available": True,
            "provider_name": "fake",
            "provider_kind": "openai_compatible",
            "model": "fake-model",
            "failure_reason": None,
        }


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


_PUBLIC = {"kind": "public", "id": None}


def _seed_history(client: TestClient, payloads: list[dict[str, object]]) -> None:
    for payload in payloads:
        assert client.post("/items", json=payload).status_code == 200
    client.app.state.pallium_service.drain_processing_queue(worker_id="agent-simulation-e2e")


def _build_harness(
    client: TestClient,
    *,
    container_ref: str,
    thread_ref: str,
    session_ref: str,
    turn_kind: str = "new_thread",
    session_has_sufficient_local_context: bool = False,
) -> tuple[AgentSimulationApp, CapturingModel]:
    io = FakeIO(["a", "n"])
    model = CapturingModel()
    harness = AgentSimulationApp(
        http_client=HarnessHttpFromTestClient(client),
        io=TerminalIO(input_func=io.prompt, output_func=io.write),
        model=model,
    )
    harness.session.defaults.container_ref = container_ref
    harness.session.defaults.thread_ref = thread_ref
    harness.session.defaults.session_ref = session_ref
    harness.session.defaults.visibility_context = dict(_PUBLIC)
    harness.session.defaults.runtime_context["turn_kind"] = turn_kind
    harness.session.defaults.runtime_context["session_has_sufficient_local_context"] = session_has_sufficient_local_context
    return harness, model


def test_chat_mode_uses_real_items_and_query_debug_contract(monkeypatch, test_db_url: str) -> None:
    monkeypatch.setattr("app.dependencies.build_llm_provider", lambda config, **_: TieredMemorySemanticProvider())
    client = TestClient(create_app(build_llm_test_config(default_use_case="agent_conversation_memory", sqlite_url=test_db_url)))

    _seed_history(
        client,
        [
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
                "visibility_context": dict(_PUBLIC),
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
                "visibility_context": dict(_PUBLIC),
            },
        ],
    )

    harness, model = _build_harness(
        client,
        container_ref="chat:ops",
        thread_ref="chat:ops:fresh",
        session_ref="session:fresh",
    )

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


def test_chat_mode_does_not_inject_the_current_user_turn_when_no_prior_memory_exists(monkeypatch, test_db_url: str) -> None:
    monkeypatch.setattr("app.dependencies.build_llm_provider", lambda config, **_: TieredMemorySemanticProvider())
    client = TestClient(create_app(build_llm_test_config(default_use_case="agent_conversation_memory", sqlite_url=test_db_url)))

    harness, model = _build_harness(
        client,
        container_ref="chat:empty",
        thread_ref="chat:empty:thread",
        session_ref="session:empty",
    )

    harness.process_chat_message("Anything important I should carry forward from earlier?")

    event = harness.session.events[0]
    query_response = event["query_debug"]["response"]

    assert query_response["should_inject"] is False
    assert query_response["decision_reason"] == "no_relevant_memory"
    assert query_response["injectable_blocks"] == []
    assert query_response["results"] == []
    assert model.calls[0]["injectable_blocks"] == []


def test_chat_mode_prefers_prior_decision_for_indirect_resource_recall(monkeypatch, test_db_url: str) -> None:
    monkeypatch.setattr("app.dependencies.build_llm_provider", lambda config, **_: PublicCorpusSemanticProvider())
    client = TestClient(create_app(build_llm_test_config(default_use_case="agent_conversation_memory", sqlite_url=test_db_url)))

    _seed_history(
        client,
        [
            {
                "source_type": "assistant_artifact",
                "source_id": "export-investigation-1",
                "content_type": "text/plain",
                "content": "Investigation found that the export worker hit the 512Mi memory limit during the packaging step.",
                "artifact_kind": "tool_use_summary",
                "role": "assistant",
                "container_ref": "chat:capacity",
                "thread_ref": "chat:capacity:history",
                "session_ref": "session:capacity:history",
                "visibility_context": dict(_PUBLIC),
            },
            {
                "source_type": "assistant_artifact",
                "source_id": "export-decision-1",
                "content_type": "text/plain",
                "content": "Decision: raise the worker memory limit to 1Gi while keeping the request at 512Mi.",
                "artifact_kind": "assistant_output",
                "role": "assistant",
                "container_ref": "chat:capacity",
                "thread_ref": "chat:capacity:history",
                "session_ref": "session:capacity:history",
                "visibility_context": dict(_PUBLIC),
            },
        ],
    )

    harness, model = _build_harness(
        client,
        container_ref="chat:capacity",
        thread_ref="chat:capacity:fresh",
        session_ref="session:capacity:fresh",
    )

    harness.process_chat_message("Which cap were we bumping for that export worker, and what stayed the same?")

    query_response = harness.session.events[0]["query_debug"]["response"]
    routing = query_response["trace"]["routing"]
    rendered_blocks = " ".join(block["text"].lower() for block in query_response["injectable_blocks"])

    assert query_response["should_inject"] is True
    assert query_response["decision_reason"] == "carry_forward_available"
    assert routing["query_intent"] == "precise_fact"
    assert routing["selected_layer"] == "decision"
    assert query_response["results"][0]["result_kind"] == "memory_hit"
    assert query_response["results"][0]["type"] == "decision"
    assert any(block["memory_type"] == "decision" for block in query_response["injectable_blocks"])
    assert all(block["block_type"] == "memory" for block in query_response["injectable_blocks"])
    assert "1gi" in rendered_blocks
    assert "512mi" in rendered_blocks
    assert model.calls[0]["injectable_blocks"] == query_response["injectable_blocks"]


def test_chat_mode_keeps_task_checkpoint_for_messy_resumed_work_prompt(monkeypatch, test_db_url: str) -> None:
    monkeypatch.setattr("app.dependencies.build_llm_provider", lambda config, **_: PublicCorpusSemanticProvider())
    client = TestClient(create_app(build_llm_test_config(default_use_case="agent_conversation_memory", sqlite_url=test_db_url)))

    _seed_history(
        client,
        [
            {
                "source_type": "assistant_artifact",
                "source_id": "sync-history-1",
                "content_type": "text/plain",
                "content": "The service token expired during the earlier sync retry, so we had to refresh auth before continuing.",
                "artifact_kind": "tool_use_summary",
                "role": "assistant",
                "container_ref": "chat:sync",
                "thread_ref": "chat:sync:history",
                "session_ref": "session:sync:history",
                "visibility_context": dict(_PUBLIC),
            },
            {
                "source_type": "assistant_artifact",
                "source_id": "sync-history-2",
                "content_type": "text/plain",
                "content": "The token refresh worked, the retry resumed through batch 417, and then the retry window was exhausted. Next step: wait 15 minutes and resume from batch 418.",
                "artifact_kind": "assistant_output",
                "role": "assistant",
                "container_ref": "chat:sync",
                "thread_ref": "chat:sync:history",
                "session_ref": "session:sync:history",
                "visibility_context": dict(_PUBLIC),
            },
        ],
    )

    harness, model = _build_harness(
        client,
        container_ref="chat:sync",
        thread_ref="chat:sync:fresh",
        session_ref="session:sync:fresh",
    )

    harness.process_chat_message("What's still blocking the sync, and where do I resume from now?")

    query_response = harness.session.events[0]["query_debug"]["response"]
    routing = query_response["trace"]["routing"]
    rendered_blocks = " ".join(block["text"].lower() for block in query_response["injectable_blocks"])

    assert query_response["should_inject"] is True
    assert query_response["decision_reason"] == "carry_forward_available"
    assert routing["query_intent"] == "work_resumption"
    assert routing["selected_layer"] == "task_checkpoint"
    assert any(block["memory_type"] == "task_checkpoint" for block in query_response["injectable_blocks"])
    assert all(block["block_type"] == "memory" for block in query_response["injectable_blocks"])
    assert "retry window" in rendered_blocks
    assert "batch 418" in rendered_blocks
    assert "expired token" not in rendered_blocks
    assert model.calls[0]["injectable_blocks"] == query_response["injectable_blocks"]

def test_chat_mode_uses_task_checkpoint_for_natural_language_resumed_work_history(monkeypatch, test_db_url: str) -> None:
    monkeypatch.setattr("app.dependencies.build_llm_provider", lambda config, **_: PublicCorpusSemanticProvider())
    client = TestClient(create_app(build_llm_test_config(default_use_case="agent_conversation_memory", sqlite_url=test_db_url)))

    _seed_history(
        client,
        [
            {
                "source_type": "assistant_artifact",
                "source_id": "sync-natural-history-1",
                "content_type": "text/plain",
                "content": "The token refresh worked and the sync got through batch 417, but the retry window is exhausted now. Wait 15 minutes and resume from batch 418.",
                "artifact_kind": "assistant_output",
                "role": "assistant",
                "container_ref": "chat:sync-natural",
                "thread_ref": "chat:sync-natural:history",
                "session_ref": "session:sync-natural:history",
                "visibility_context": dict(_PUBLIC),
            },
        ],
    )

    harness, model = _build_harness(
        client,
        container_ref="chat:sync-natural",
        thread_ref="chat:sync-natural:fresh",
        session_ref="session:sync-natural:fresh",
    )

    harness.process_chat_message("I'm back on the sync. What's the current blocker and where do I pick it up?")

    query_response = harness.session.events[0]["query_debug"]["response"]
    routing = query_response["trace"]["routing"]
    rendered_blocks = " ".join(block["text"].lower() for block in query_response["injectable_blocks"])

    assert query_response["should_inject"] is True
    assert query_response["decision_reason"] == "carry_forward_available"
    assert routing["query_intent"] == "work_resumption"
    assert routing["selected_layer"] == "task_checkpoint"
    assert any(block["memory_type"] == "task_checkpoint" for block in query_response["injectable_blocks"])
    assert "retry window" in rendered_blocks
    assert "batch 418" in rendered_blocks
    assert model.calls[0]["injectable_blocks"] == query_response["injectable_blocks"]
