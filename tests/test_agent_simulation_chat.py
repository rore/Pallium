from __future__ import annotations

from dataclasses import dataclass

from app.agent_simulation import AgentSimulationApp, TerminalIO
from app.agent_simulation_model import ModelUnavailableError
from app.agent_simulation_session import SessionStore


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


class FakeHTTPClient:
    def __init__(self, query_debug_responses: list[dict]) -> None:
        self.base_url = "http://example.test"
        self.created_items: list[dict] = []
        self.query_debug_requests: list[dict] = []
        self._query_debug_responses = list(query_debug_responses)

    def create_item(self, payload):
        self.created_items.append(payload)
        return {"source_item_id": payload["source_id"], "processing_status": "pending"}

    def query(self, payload):
        return {"results": [], "should_inject": False, "decision_reason": "no_relevant_memory", "injectable_blocks": []}

    def query_debug(self, payload):
        self.query_debug_requests.append(payload)
        return self._query_debug_responses.pop(0)

    def close(self) -> None:
        return None


@dataclass(frozen=True)
class FakeResolution:
    available: bool = True
    provider_name: str | None = "fake"
    provider_kind: str | None = "openai_compatible"
    model: str | None = "fake-model"
    failure_reason: str | None = None

    def to_dict(self):
        return {
            "available": self.available,
            "provider_name": self.provider_name,
            "provider_kind": self.provider_kind,
            "model": self.model,
            "failure_reason": self.failure_reason,
        }


@dataclass(frozen=True)
class FakeDraft:
    answer: str
    model_request: dict
    model_response: dict
    resolution: FakeResolution


class CapturingModel:
    def __init__(self, *, answer: str = "draft answer", error: Exception | None = None) -> None:
        self.calls: list[dict] = []
        self._answer = answer
        self._error = error
        self._resolution = FakeResolution(available=error is None)

    def resolution(self):
        return self._resolution

    def draft_answer(self, *, user_message: str, injectable_blocks: list[dict]):
        self.calls.append({"user_message": user_message, "injectable_blocks": injectable_blocks})
        if self._error is not None:
            raise self._error
        return FakeDraft(
            answer=self._answer,
            model_request={"user_prompt": user_message, "injectable_blocks": injectable_blocks},
            model_response={"parsed_json": {"answer": self._answer}},
            resolution=self._resolution,
        )


def _query_debug_payload(*, should_inject: bool, injectable_blocks: list[dict], results: list[dict]) -> dict:
    return {
        "results": results,
        "should_inject": should_inject,
        "decision_reason": "carry_forward_available" if should_inject else "same_thread_context_sufficient",
        "injectable_blocks": injectable_blocks,
        "trace": {
            "routing": {"selected_layer": "decision", "query_intent": "recurring_question", "excluded_high_scoring_candidates": []},
            "visibility": {"excluded_candidates": [], "fail_closed_reason": None},
            "stages": [],
        },
    }


def _build_app(tmp_path, responses: list[str], query_debug_response: dict, *, model: CapturingModel) -> tuple[AgentSimulationApp, FakeIO, FakeHTTPClient]:
    io = FakeIO(responses)
    http_client = FakeHTTPClient([query_debug_response])
    app = AgentSimulationApp(
        http_client=http_client,
        io=TerminalIO(input_func=io.prompt, output_func=io.write),
        session_store=SessionStore(tmp_path),
        model=model,
    )
    return app, io, http_client


def test_chat_accepts_model_draft_and_only_passes_injectable_blocks(tmp_path) -> None:
    blocks = [{"block_type": "memory", "memory_type": "decision", "title": "Decision", "text": "Use item event time."}]
    results = [{"result_kind": "source_hit", "score": 11, "result_id": "source_item:1", "excerpt": "raw candidate text"}]
    model = CapturingModel(answer="Accepted answer")
    app, _io, http_client = _build_app(tmp_path, ["a", "n"], _query_debug_payload(should_inject=True, injectable_blocks=blocks, results=results), model=model)

    app.process_chat_message("Why did we choose this?")

    assert model.calls == [{"user_message": "Why did we choose this?", "injectable_blocks": blocks}]
    assert len(http_client.created_items) == 2
    assert http_client.created_items[0]["artifact_kind"] == "message"
    assert http_client.created_items[1]["artifact_kind"] == "assistant_output"
    event = app.session.events[0]
    assert event["operator_action"] == "accepted"
    assert event["assistant"]["content"] == "Accepted answer"
    assert event["model"]["request"]["injectable_blocks"] == blocks
    assert "raw candidate text" not in str(event["model"]["request"])


def test_chat_does_not_forward_raw_results_when_injection_is_false(tmp_path) -> None:
    results = [{"result_kind": "source_hit", "score": 9, "result_id": "source_item:2", "excerpt": "candidate not for prompt"}]
    model = CapturingModel(answer="No memory needed")
    app, _io, _http_client = _build_app(tmp_path, ["a", "n"], _query_debug_payload(should_inject=False, injectable_blocks=[{"text": "should not pass"}], results=results), model=model)

    app.process_chat_message("Answer from local context")

    assert model.calls == [{"user_message": "Answer from local context", "injectable_blocks": []}]
    event = app.session.events[0]
    assert event["model"]["request"]["injectable_blocks"] == []
    assert "candidate not for prompt" not in str(event["model"]["request"])


def test_chat_edit_and_artifact_ingest_record_operator_choices(tmp_path) -> None:
    blocks = [{"block_type": "memory", "memory_type": "task_checkpoint", "title": "Checkpoint", "text": "Resume from batch 313."}]
    model = CapturingModel(answer="Draft answer")
    app, _io, http_client = _build_app(
        tmp_path,
        ["e", "Edited answer", "y", "tool_use_summary", "Artifact summary"],
        _query_debug_payload(should_inject=True, injectable_blocks=blocks, results=[]),
        model=model,
    )

    app.process_chat_message("What should we do next?")

    assert len(http_client.created_items) == 3
    assert http_client.created_items[1]["content"] == "Edited answer"
    assert http_client.created_items[2]["artifact_kind"] == "tool_use_summary"
    event = app.session.events[0]
    assert event["operator_action"] == "edited"
    assert event["artifact"]["content"] == "Artifact summary"


def test_chat_blank_edit_and_artifact_prompts_retry_without_losing_event(tmp_path) -> None:
    blocks = [{"block_type": "memory", "memory_type": "task_checkpoint", "title": "Checkpoint", "text": "Resume from batch 313."}]
    model = CapturingModel(answer="Draft answer")
    app, io, http_client = _build_app(
        tmp_path,
        ["e", "", "Edited answer", "y", "tool_use_summary", "", "Artifact summary"],
        _query_debug_payload(should_inject=True, injectable_blocks=blocks, results=[]),
        model=model,
    )

    app.process_chat_message("What should we do next?")

    assert len(http_client.created_items) == 3
    assert len(app.session.events) == 1
    assert app.session.events[0]["assistant"]["content"] == "Edited answer"
    assert app.session.events[0]["artifact"]["content"] == "Artifact summary"
    assert any("Required input missing for prompt: edited assistant reply:" in line for line in io.outputs)
    assert any("Required input missing for prompt: artifact text:" in line for line in io.outputs)


def test_chat_discard_skips_assistant_ingest(tmp_path) -> None:
    model = CapturingModel(answer="Discard me")
    app, _io, http_client = _build_app(
        tmp_path,
        ["d"],
        _query_debug_payload(should_inject=True, injectable_blocks=[], results=[]),
        model=model,
    )

    app.process_chat_message("Question")

    assert len(http_client.created_items) == 1
    assert app.session.events[0]["operator_action"] == "discarded"
    assert "assistant" not in app.session.events[0]


def test_model_failure_falls_back_to_manual_entry_and_records_reason(tmp_path) -> None:
    model = CapturingModel(error=ModelUnavailableError("provider failed"))
    app, _io, http_client = _build_app(
        tmp_path,
        ["Manual assistant reply", "n"],
        _query_debug_payload(should_inject=True, injectable_blocks=[], results=[]),
        model=model,
    )

    app.process_chat_message("Need fallback")

    assert len(http_client.created_items) == 2
    event = app.session.events[0]
    assert event["operator_action"] == "manual_entry"
    assert event["assistant"]["origin"] == "manual_fallback"
    assert event["assistant"]["content"] == "Manual assistant reply"
    assert event["model"]["origin"] == "manual_fallback"
    assert "provider failed" in event["model"]["failure_reason"]


def test_chat_lite_auto_accepts_and_skips_operator_prompts(tmp_path) -> None:
    blocks = [{"block_type": "memory", "memory_type": "decision", "title": "Decision", "text": "Use item event time."}]
    model = CapturingModel(answer="Light reply")
    app, io, http_client = _build_app(tmp_path, [], _query_debug_payload(should_inject=True, injectable_blocks=blocks, results=[]), model=model)
    app._mode = "chat-lite"
    app.session.set_mode("chat-lite")

    app.process_chat_message("Just answer")

    assert model.calls == [{"user_message": "Just answer", "injectable_blocks": blocks}]
    assert len(http_client.created_items) == 2
    event = app.session.events[0]
    assert event["mode"] == "chat-lite"
    assert event["operator_action"] == "auto_accepted"
    assert event["assistant"]["content"] == "Light reply"
    assert all("accept/edit/discard" not in line for line in io.outputs)
    assert all("Add artifact now?" not in line for line in io.outputs)
    assert all("should_inject:" not in line for line in io.outputs)
    assert "Light reply" in io.outputs


def test_chat_lite_model_failure_does_not_prompt_manual_entry(tmp_path) -> None:
    model = CapturingModel(error=ModelUnavailableError("provider failed"))
    app, io, http_client = _build_app(
        tmp_path,
        [],
        _query_debug_payload(should_inject=True, injectable_blocks=[], results=[]),
        model=model,
    )
    app._mode = "chat-lite"
    app.session.set_mode("chat-lite")

    app.process_chat_message("Need light fallback")

    assert len(http_client.created_items) == 1
    event = app.session.events[0]
    assert event["operator_action"] == "auto_skipped"
    assert "assistant" not in event
    assert any("Model unavailable: provider failed" in line for line in io.outputs)
    assert all("assistant>" not in line for line in io.outputs)
