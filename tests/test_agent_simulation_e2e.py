from __future__ import annotations

import pytest
from dataclasses import dataclass

from fastapi.testclient import TestClient

from app.agent_simulation import AgentSimulationApp, TerminalIO
from app.main import create_app
from tests.config_helpers import build_llm_test_config
from tests.public_corpus_stub_providers import PublicCorpusSemanticProvider
from tests.stub_providers import TieredMemorySemanticProvider

pytestmark = pytest.mark.slow


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
        response = self._client.post("/items", json=[payload])
        assert response.status_code == 200
        return response.json()[0]

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

    def draft_answer(self, *, user_message: str, injectable_blocks: list[dict], local_thread_context: list[dict]):
        self.calls.append({"user_message": user_message, "injectable_blocks": injectable_blocks, "local_thread_context": local_thread_context})
        return FakeDraft(
            answer="Final draft",
            model_request={"injectable_blocks": injectable_blocks},
            model_response={"parsed_json": {"answer": "Final draft"}},
            resolution=self._resolution,
        )


_PUBLIC = "public"


def _seed_history(client: TestClient, payloads: list[dict[str, object]]) -> None:
    for payload in payloads:
        assert client.post("/items", json=[payload]).status_code == 200
    client.app.state.pallium_service.drain_processing_queue(worker_id="agent-simulation-e2e")


def _build_harness(
    client: TestClient,
    *,
    container_ref: str,
    thread_ref: str,
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
    harness.session.defaults.visibility = "public"
    harness.session.defaults.set_runtime_context("turn_kind", turn_kind, manual=True)
    harness.session.defaults.set_runtime_context("session_has_sufficient_local_context", session_has_sufficient_local_context, manual=True)
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
                "visibility": "public",
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
                "visibility": "public",
            },
        ],
    )

    harness, model = _build_harness(
        client,
        container_ref="chat:ops",
        thread_ref="chat:ops:fresh",
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
                "visibility": "public",
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
                "visibility": "public",
            },
        ],
    )

    harness, model = _build_harness(
        client,
        container_ref="chat:capacity",
        thread_ref="chat:capacity:fresh",
    )

    harness.process_chat_message("Which cap were we bumping for that export worker, and what stayed the same?")

    query_response = harness.session.events[0]["query_debug"]["response"]
    routing = query_response["trace"]["routing"]
    rendered_blocks = " ".join(block["text"].lower() for block in query_response["injectable_blocks"])

    assert query_response["should_inject"] is True
    assert query_response["decision_reason"] == "carry_forward_available"
    assert routing["query_intent"] in {"structured_recall", "recall"}  # envelope-first
    assert routing["selected_layer"] in {"decision", "pattern_memory", "thread_summary", "lower_level_memory"}  # envelope-first
    assert query_response["results"][0]["result_kind"] == "memory_hit"
    assert query_response["results"][0]["type"] in {"decision", "investigation_outcome"}  # envelope-first
    assert any(block["memory_type"] in {"decision", "investigation_outcome"} for block in query_response["injectable_blocks"])
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
                "visibility": "public",
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
                "visibility": "public",
            },
        ],
    )

    harness, model = _build_harness(
        client,
        container_ref="chat:sync",
        thread_ref="chat:sync:fresh",
    )

    harness.process_chat_message("What's still blocking the sync, and where do I resume from now?")

    query_response = harness.session.events[0]["query_debug"]["response"]
    routing = query_response["trace"]["routing"]
    rendered_blocks = " ".join(block["text"].lower() for block in query_response["injectable_blocks"])

    assert query_response["should_inject"] is True
    assert query_response["decision_reason"] == "carry_forward_available"
    # Without legacy English cues, work_resumption intent requires resumed_session
    # context. Without it, the query routes as broad_recall. The task checkpoint
    # may still appear in results but is not guaranteed to be the injected block.
    assert routing["query_intent"] in ("work_resumption", "recall")
    assert query_response["injectable_blocks"]
    assert all(block["block_type"] == "memory" for block in query_response["injectable_blocks"])
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
                "visibility": "public",
            },
        ],
    )

    harness, model = _build_harness(
        client,
        container_ref="chat:sync-natural",
        thread_ref="chat:sync-natural:fresh",
    )

    harness.process_chat_message("I'm back on the sync. What's the current blocker and where do I pick it up?")

    query_response = harness.session.events[0]["query_debug"]["response"]
    routing = query_response["trace"]["routing"]
    rendered_blocks = " ".join(block["text"].lower() for block in query_response["injectable_blocks"])

    assert query_response["should_inject"] is True
    assert query_response["decision_reason"] == "carry_forward_available"
    # Without legacy English cues, work_resumption intent requires resumed_session
    # context. Without it, the query routes as broad_recall. The task checkpoint
    # may still appear in results but is not guaranteed to be the injected block.
    assert routing["query_intent"] in ("work_resumption", "recall")
    assert query_response["injectable_blocks"]
    assert model.calls[0]["injectable_blocks"] == query_response["injectable_blocks"]

def test_chat_mode_uses_pattern_memory_after_consolidation_for_broad_recall(monkeypatch, test_db_url: str) -> None:
    monkeypatch.setattr("app.dependencies.build_llm_provider", lambda config, **_: PublicCorpusSemanticProvider())
    client = TestClient(create_app(build_llm_test_config(default_use_case="agent_conversation_memory", sqlite_url=test_db_url)))

    _seed_history(
        client,
        [
            {
                "source_type": "chat_message",
                "source_id": "grocery-history-u1",
                "content_type": "text/plain",
                "content": "We keep wasting time in the store. What is the real lesson?",
                "artifact_kind": "message",
                "role": "user",
                "container_ref": "chat:grocery-pattern",
                "thread_ref": "chat:grocery-pattern:one",
                "visibility": "public",
            },
            {
                "source_type": "assistant_artifact",
                "source_id": "grocery-history-a1",
                "content_type": "text/plain",
                "content": "You keep zig-zagging. Investigation found that aisle-by-aisle shopping leads to repeated backtracking when the list is unordered.",
                "artifact_kind": "assistant_output",
                "role": "assistant",
                "container_ref": "chat:grocery-pattern",
                "thread_ref": "chat:grocery-pattern:one",
                "visibility": "public",
            },
            {
                "source_type": "assistant_artifact",
                "source_id": "grocery-history-a2",
                "content_type": "text/plain",
                "content": "Decision: sort the list by store section before leaving home.",
                "artifact_kind": "assistant_output",
                "role": "assistant",
                "container_ref": "chat:grocery-pattern",
                "thread_ref": "chat:grocery-pattern:one",
                "visibility": "public",
            },
            {
                "source_type": "chat_message",
                "source_id": "grocery-history-u2",
                "content_type": "text/plain",
                "content": "This happened again with a different list.",
                "artifact_kind": "message",
                "role": "user",
                "container_ref": "chat:grocery-pattern",
                "thread_ref": "chat:grocery-pattern:two",
                "visibility": "public",
            },
            {
                "source_type": "assistant_artifact",
                "source_id": "grocery-history-a3",
                "content_type": "text/plain",
                "content": "Different surface, same problem. Investigation found that recipe-order shopping created the same backtracking problem in the store.",
                "artifact_kind": "assistant_output",
                "role": "assistant",
                "container_ref": "chat:grocery-pattern",
                "thread_ref": "chat:grocery-pattern:two",
                "visibility": "public",
            },
            {
                "source_type": "assistant_artifact",
                "source_id": "grocery-history-a4",
                "content_type": "text/plain",
                "content": "Decision: group the shopping list by produce, dairy, pantry, and freezer before you shop.",
                "artifact_kind": "assistant_output",
                "role": "assistant",
                "container_ref": "chat:grocery-pattern",
                "thread_ref": "chat:grocery-pattern:two",
                "visibility": "public",
            },
        ],
    )
    client.app.state.pallium_service.run_consolidation_pass(
        use_case="agent_conversation_memory",
        strategy_name="container_topic_window",
    )

    harness, model = _build_harness(
        client,
        container_ref="chat:grocery-pattern",
        thread_ref="chat:grocery-pattern:fresh",
    )

    harness.process_chat_message("Give me the big picture across those conversations, not one specific tactic.")

    query_response = harness.session.events[0]["query_debug"]["response"]
    routing = query_response["trace"]["routing"]
    rendered_blocks = " ".join(block["text"].lower() for block in query_response["injectable_blocks"])

    assert query_response["should_inject"] is True
    assert routing["selected_layer"] == "pattern_memory"
    assert any(block["memory_type"] == "pattern_memory" for block in query_response["injectable_blocks"])
    assert "backtracking" in rendered_blocks
    assert "store section" in rendered_blocks
    assert model.calls[0]["injectable_blocks"] == query_response["injectable_blocks"]


def test_greeting_exchange_does_not_inject_source_evidence(monkeypatch, test_db_url: str) -> None:
    """Greetings and low-value pleasantry exchanges must not be injected as source_evidence
    for unrelated follow-up queries in a new thread."""
    monkeypatch.setattr("app.dependencies.build_llm_provider", lambda config, **_: PublicCorpusSemanticProvider())
    client = TestClient(create_app(build_llm_test_config(default_use_case="agent_conversation_memory", sqlite_url=test_db_url)))

    _seed_history(
        client,
        [
            {
                "source_type": "chat_message",
                "source_id": "greeting-user-1",
                "content_type": "text/plain",
                "content": "hello again",
                "artifact_kind": "message",
                "role": "user",
                "container_ref": "chat:greeting",
                "thread_ref": "chat:greeting:thread1",
                "visibility": "public",
            },
            {
                "source_type": "assistant_artifact",
                "source_id": "greeting-assistant-1",
                "content_type": "text/plain",
                "content": "Hello! Good to see you again.",
                "artifact_kind": "assistant_output",
                "role": "assistant",
                "container_ref": "chat:greeting",
                "thread_ref": "chat:greeting:thread1",
                "visibility": "public",
            },
        ],
    )

    harness, model = _build_harness(
        client,
        container_ref="chat:greeting",
        thread_ref="chat:greeting:thread2",
        turn_kind="new_thread",
        session_has_sufficient_local_context=False,
    )

    harness.process_chat_message("do you know what day it is?")

    query_response = harness.session.events[0]["query_debug"]["response"]
    injectable_blocks = query_response["injectable_blocks"]

    # No greeting/pleasantry source hit must be injected.
    source_blocks = [b for b in injectable_blocks if b.get("block_type") == "source"]
    assert not source_blocks, (
        f"Expected no source_evidence blocks from greeting exchange, got: {source_blocks}"
    )
    # If injection happens at all, the block must not contain the greeting text.
    for block in injectable_blocks:
        block_text = block.get("text", "").lower()
        assert "hello again" not in block_text, (
            f"Greeting text leaked into injection block: {block}"
        )
        assert "hello! good to see" not in block_text, (
            f"Greeting text leaked into injection block: {block}"
        )


def test_offtopic_weather_query_does_not_carry_forward_library_memories(monkeypatch, test_db_url: str) -> None:
    monkeypatch.setattr("app.dependencies.build_llm_provider", lambda config, **_: PublicCorpusSemanticProvider())
    client = TestClient(create_app(build_llm_test_config(default_use_case="agent_conversation_memory", sqlite_url=test_db_url)))

    _seed_history(
        client,
        [
            {
                "source_type": "chat_message",
                "source_id": "weather-offtopic-user-1",
                "content_type": "text/plain",
                "content": "We need to sort out reservation ordering before the next catalog sync.",
                "artifact_kind": "message",
                "role": "user",
                "container_ref": "chat:library-help",
                "thread_ref": "chat:library-help:history-weather-offtopic",
                "visibility": "public",
            },
            {
                "source_type": "assistant_artifact",
                "source_id": "weather-offtopic-assistant-1",
                "content_type": "text/plain",
                "content": "Investigation found that catalog sync delays let arrival-time ordering create duplicate reservation holds.",
                "artifact_kind": "tool_use_summary",
                "role": "assistant",
                "container_ref": "chat:library-help",
                "thread_ref": "chat:library-help:history-weather-offtopic",
                "visibility": "public",
            },
            {
                "source_type": "assistant_artifact",
                "source_id": "weather-offtopic-assistant-2",
                "content_type": "text/plain",
                "content": "Decision: use item event time for reservation ordering instead of arrival time during catalog sync retries.",
                "artifact_kind": "assistant_output",
                "role": "assistant",
                "container_ref": "chat:library-help",
                "thread_ref": "chat:library-help:history-weather-offtopic",
                "visibility": "public",
            },
        ],
    )

    harness, model = _build_harness(
        client,
        container_ref="chat:library-help",
        thread_ref="chat:library-help:fresh-weather-offtopic",
        turn_kind="new_thread",
        session_has_sufficient_local_context=False,
    )

    harness.process_chat_message("how is the weather today?")

    query_response = harness.session.events[0]["query_debug"]["response"]
    injectable_blocks = query_response["injectable_blocks"]

    assert query_response["should_inject"] is False, (
        f"Expected no off-topic injection, got decision_reason={query_response.get('decision_reason')!r}, "
        f"blocks={injectable_blocks}"
    )
    assert injectable_blocks == []
    assert model.calls[0]["injectable_blocks"] == []


def test_same_thread_confirmation_does_not_inject_source_evidence(monkeypatch, test_db_url: str) -> None:
    """A same-thread lightweight confirmation query ('we're talking about export, right?')
    must not receive multiple raw source_evidence injection blocks.
    With session_has_sufficient_local_context=True, same-thread suppression should fire."""
    monkeypatch.setattr("app.dependencies.build_llm_provider", lambda config, **_: PublicCorpusSemanticProvider())
    client = TestClient(create_app(build_llm_test_config(default_use_case="agent_conversation_memory", sqlite_url=test_db_url)))

    _seed_history(
        client,
        [
            {
                "source_type": "assistant_artifact",
                "source_id": "export-ctx-1",
                "content_type": "text/plain",
                "content": "Decision: raise the worker memory limit to 1Gi while keeping the request at 512Mi.",
                "artifact_kind": "assistant_output",
                "role": "assistant",
                "container_ref": "chat:export-confirm",
                "thread_ref": "chat:export-confirm:thread1",
                "visibility": "public",
            },
        ],
    )

    harness, model = _build_harness(
        client,
        container_ref="chat:export-confirm",
        thread_ref="chat:export-confirm:thread1",
        turn_kind="same_thread",
        session_has_sufficient_local_context=True,
    )

    harness.process_chat_message("we're talking about export, right?")

    query_response = harness.session.events[0]["query_debug"]["response"]

    # Same-thread context is sufficient — no injection should happen for a lightweight confirmation.
    assert query_response["should_inject"] is False, (
        f"Expected no injection for same-thread confirmation, got decision_reason={query_response.get('decision_reason')!r}, "
        f"blocks={query_response['injectable_blocks']}"
    )
    # No raw source blocks should leak through.
    source_blocks = [b for b in query_response["injectable_blocks"] if b.get("block_type") == "source"]
    assert not source_blocks, (
        f"Expected no raw source_evidence blocks for same-thread confirmation, got: {source_blocks}"
    )


@pytest.mark.xfail(
    reason=(
        "Formation gap: natural-language export statements without 'Decision:' prefix "
        "produce candidate_type=None from LLM extraction, so no decision object is formed. "
        "Stub confirms this: only source_hit is indexed, no structured memory. "
        "Requires stub/LLM extraction to recognize natural operational-fact sentences. "
        "Routing fix (Fix 4, precise_fact fresh-thread preference) is separately covered by "
        "test_fresh_thread_recalls_export_cap_fact_prefixed_control."
    ),
    strict=False,  # envelope-first routing may resolve this via broad_recall weights
)
def test_fresh_thread_recalls_export_cap_fact_natural_language(monkeypatch, test_db_url: str) -> None:
    """A natural-language export cap statement (no 'Decision:' prefix) followed by a fresh-thread
    recall query must surface the cap figures.

    This test uses the verbatim harness repro sentence. With the stub provider returning
    candidate_type=None for natural sentences, this test is expected to reveal whether the
    failure is in memory formation (stub returns no structured type → only source_hit available)
    or in routing (structured memory retrieved but not ranked/injected).

    If this test fails with should_inject=False or no 1Gi/512Mi in rendered_blocks,
    the gap is at the formation layer — the natural sentence did not produce a decision object.
    Run test_fresh_thread_recalls_export_cap_fact_prefixed_control to confirm routing works
    once formation is correct.
    """
    monkeypatch.setattr("app.dependencies.build_llm_provider", lambda config, **_: PublicCorpusSemanticProvider())
    client = TestClient(create_app(build_llm_test_config(default_use_case="agent_conversation_memory", sqlite_url=test_db_url)))

    _seed_history(
        client,
        [
            {
                "source_type": "chat_message",
                "source_id": "export-natural-user-1",
                "content_type": "text/plain",
                "content": "We said the export worker should go to 1Gi memory limit while keeping the request at 512Mi.",
                "artifact_kind": "message",
                "role": "user",
                "container_ref": "chat:export-natural",
                "thread_ref": "chat:export-natural:thread1",
                "visibility": "public",
            },
        ],
    )

    harness, model = _build_harness(
        client,
        container_ref="chat:export-natural",
        thread_ref="chat:export-natural:thread2",
        turn_kind="new_thread",
        session_has_sufficient_local_context=False,
    )

    harness.process_chat_message("Which cap were we bumping and what stayed the same?")

    query_response = harness.session.events[0]["query_debug"]["response"]
    rendered_blocks = " ".join(block["text"].lower() for block in query_response["injectable_blocks"])

    assert query_response["should_inject"] is True, (
        f"Expected injection for fresh-thread export recall, got decision_reason={query_response.get('decision_reason')!r}. "
        f"If candidate_type=None from stub, this confirms the formation gap (no decision object formed for natural sentence)."
    )
    assert "1gi" in rendered_blocks, f"Expected '1gi' in injected blocks, got: {rendered_blocks!r}"
    assert "512mi" in rendered_blocks, f"Expected '512mi' in injected blocks, got: {rendered_blocks!r}"


def test_fresh_thread_recalls_export_cap_fact_prefixed_control(monkeypatch, test_db_url: str) -> None:
    """Control test: a 'Decision:'-prefixed export cap statement must be recalled correctly
    from a fresh thread using a 'which cap' query.

    This covers the routing layer — the stub produces a decision object, and the routing
    must prefer it over raw source_hits in fresh-thread precise_fact mode.
    This test was already effectively covered by test_chat_mode_prefers_prior_decision_for_indirect_resource_recall
    but that test uses a slightly different query. This variant uses the verbatim harness repro query.
    """
    monkeypatch.setattr("app.dependencies.build_llm_provider", lambda config, **_: PublicCorpusSemanticProvider())
    client = TestClient(create_app(build_llm_test_config(default_use_case="agent_conversation_memory", sqlite_url=test_db_url)))

    _seed_history(
        client,
        [
            {
                "source_type": "assistant_artifact",
                "source_id": "export-prefixed-1",
                "content_type": "text/plain",
                "content": "Decision: raise the worker memory limit to 1Gi while keeping the request at 512Mi.",
                "artifact_kind": "assistant_output",
                "role": "assistant",
                "container_ref": "chat:export-prefixed",
                "thread_ref": "chat:export-prefixed:thread1",
                "visibility": "public",
            },
        ],
    )

    harness, model = _build_harness(
        client,
        container_ref="chat:export-prefixed",
        thread_ref="chat:export-prefixed:thread2",
        turn_kind="new_thread",
        session_has_sufficient_local_context=False,
    )

    harness.process_chat_message("Which cap were we bumping and what stayed the same?")

    query_response = harness.session.events[0]["query_debug"]["response"]
    routing = query_response["trace"]["routing"]
    rendered_blocks = " ".join(block["text"].lower() for block in query_response["injectable_blocks"])

    assert query_response["should_inject"] is True, (
        f"Expected injection, got decision_reason={query_response.get('decision_reason')!r}"
    )
    assert routing["query_intent"] in {"structured_recall", "recall"}  # envelope-first: recall mode from candidate evidence
    assert routing["selected_layer"] in {"decision", "pattern_memory", "lower_level_memory"}, (
        f"Expected recall layer, got {routing['selected_layer']!r}"
    )
    assert "1gi" in rendered_blocks
    assert "512mi" in rendered_blocks


def test_chat_mode_local_thread_context_does_not_leak_across_new_conversation(monkeypatch, test_db_url: str) -> None:
    monkeypatch.setattr("app.dependencies.build_llm_provider", lambda config, **_: TieredMemorySemanticProvider())
    client = TestClient(create_app(build_llm_test_config(default_use_case="agent_conversation_memory", sqlite_url=test_db_url)))

    harness, model = _build_harness(
        client,
        container_ref="chat:local-context",
        thread_ref="chat:local-context:thread1",
        turn_kind="new_thread",
        session_has_sufficient_local_context=False,
    )
    harness._mode = "chat-lite"
    harness.session.set_mode("chat-lite")

    harness.process_chat_message("We're discussing export limits.")
    assert model.calls[0]["local_thread_context"] == []

    assert harness._handle_command("/new") is True
    harness.process_chat_message("split them")

    assert model.calls[1]["local_thread_context"] == []
    second_request = harness.session.events[1]["query_debug"]["request"]
    assert "runtime_context" not in second_request


def test_chat_mode_keeps_cross_thread_memory_separate_from_local_thread_context(monkeypatch, test_db_url: str) -> None:
    monkeypatch.setattr("app.dependencies.build_llm_provider", lambda config, **_: TieredMemorySemanticProvider())
    client = TestClient(create_app(build_llm_test_config(default_use_case="agent_conversation_memory", sqlite_url=test_db_url)))

    _seed_history(
        client,
        [
            {
                "source_type": "assistant_artifact",
                "source_id": "history-decision-separate-1",
                "content_type": "text/plain",
                "content": "Decision: use item event time for reservation ordering to avoid missed hold updates during sync delays.",
                "artifact_kind": "assistant_output",
                "role": "assistant",
                "container_ref": "chat:local-vs-memory",
                "thread_ref": "chat:local-vs-memory:history",
                "visibility": "public",
            },
        ],
    )

    harness, model = _build_harness(
        client,
        container_ref="chat:local-vs-memory",
        thread_ref="chat:local-vs-memory:fresh",
        turn_kind="new_thread",
        session_has_sufficient_local_context=False,
    )
    harness._mode = "chat-lite"
    harness.session.set_mode("chat-lite")

    harness.process_chat_message("Why did we choose item event time for reservation ordering?")

    assert model.calls[0]["local_thread_context"] == []
    assert model.calls[0]["injectable_blocks"]
