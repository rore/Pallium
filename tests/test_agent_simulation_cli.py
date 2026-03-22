from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from app.agent_simulation import AgentSimulationApp, TerminalIO, build_parser, run
from app.agent_simulation_session import SessionStore


class FakeIO:
    def __init__(self, responses: list[str] | None = None) -> None:
        self._responses = list(responses or [])
        self.outputs: list[str] = []

    def prompt(self, text: str) -> str:
        self.outputs.append(text)
        if not self._responses:
            raise AssertionError(f"unexpected prompt: {text}")
        return self._responses.pop(0)

    def write(self, text: str) -> None:
        self.outputs.append(text)


class FakeHTTPClient:
    def __init__(self) -> None:
        self.base_url = "http://example.test"

    def create_item(self, payload):
        return {"source_item_id": payload["source_id"], "processing_status": "pending"}

    def query(self, payload):
        return {"results": [], "should_inject": False, "decision_reason": "no_relevant_memory", "injectable_blocks": []}

    def query_debug(self, payload):
        return {
            "results": [],
            "should_inject": False,
            "decision_reason": "no_relevant_memory",
            "injectable_blocks": [],
            "trace": {"routing": {}, "visibility": {}, "stages": []},
        }

    def close(self) -> None:
        return None


@dataclass(frozen=True)
class FakeResolution:
    def to_dict(self):
        return {
            "available": False,
            "provider_name": None,
            "provider_kind": None,
            "model": None,
            "failure_reason": "not configured",
        }


class FakeModel:
    def resolution(self):
        return FakeResolution()


@dataclass(frozen=True)
class FakeDraft:
    answer: str
    model_request: dict[str, Any]
    model_response: dict[str, Any]
    resolution: FakeResolution


class AcceptingModel:
    def __init__(self, answer: str = "accepted reply") -> None:
        self.answer = answer

    def resolution(self):
        return FakeResolution()

    def draft_answer(self, *, user_message: str, injectable_blocks: list[dict], local_thread_context: list[dict]):
        return FakeDraft(
            answer=self.answer,
            model_request={"user_message": user_message, "injectable_blocks": injectable_blocks, "local_thread_context": local_thread_context},
            model_response={"parsed_json": {"answer": self.answer}},
            resolution=FakeResolution(),
        )


def _build_app(tmp_path, responses: list[str] | None = None, *, model=None) -> tuple[AgentSimulationApp, FakeIO]:
    io = FakeIO(responses)
    app = AgentSimulationApp(
        http_client=FakeHTTPClient(),
        io=TerminalIO(input_func=io.prompt, output_func=io.write),
        session_store=SessionStore(tmp_path),
        model=model or FakeModel(),
    )
    return app, io


def test_build_parser_defaults_to_chat_and_local_base_url() -> None:
    parsed = build_parser().parse_args([])

    assert parsed.mode == "chat"
    assert parsed.base_url == "http://127.0.0.1:8000"
    assert parsed.provider is None
    assert parsed.model is None


def test_build_parser_accepts_chat_lite_mode() -> None:
    parsed = build_parser().parse_args(["chat-lite"])

    assert parsed.mode == "chat-lite"


def test_new_session_defaults_start_with_neutral_runtime_context(tmp_path) -> None:
    app, _io = _build_app(tmp_path)

    assert app.session.defaults.runtime_context["turn_kind"] is None
    assert app.session.defaults.runtime_context["session_has_sufficient_local_context"] is None


def test_scope_turn_local_context_and_mode_commands_update_session_defaults(tmp_path) -> None:
    app, _io = _build_app(tmp_path, ["container-1", "thread-1", "limited"])

    assert app._handle_command("/scope") is True
    assert app._handle_command("/turn resumed_session") is True
    assert app._handle_command("/local-context true") is True
    assert app._handle_command("/mode chat-lite") is True
    assert app._handle_command("/mode manual") is True

    defaults = app.session.defaults
    assert defaults.container_ref == "container-1"
    assert defaults.thread_ref == "thread-1"
    assert defaults.container_visibility == "limited" or (isinstance(defaults.container_visibility, dict) and defaults.container_visibility.get("kind") == "limited")
    assert defaults.runtime_context["turn_kind"] == "resumed_session"
    assert defaults.runtime_context["session_has_sufficient_local_context"] is True
    assert app.session.mode == "manual"


def test_fork_preserves_session_by_default_and_can_rotate_with_flag(tmp_path) -> None:
    app, _io = _build_app(tmp_path)
    original_container = app.session.defaults.container_ref
    original_thread = app.session.defaults.thread_ref

    assert app._handle_command("/fork") is True
    assert app.session.defaults.container_ref == original_container
    assert app.session.defaults.thread_ref != original_thread

    forked_thread = app.session.defaults.thread_ref
    assert app._handle_command("/fork --new-session") is True
    assert app.session.defaults.container_ref == original_container
    assert app.session.defaults.thread_ref != forked_thread


def test_save_and_export_write_replay_friendly_session_bundle(tmp_path) -> None:
    app, _io = _build_app(tmp_path)
    app.session.record_event({"event_type": "manual_query", "request": {"text": "hello"}, "response": {"results": []}})

    assert app._handle_command("/save sample-session") is True
    assert app._handle_command("/export exported-session") is True

    saved_path = tmp_path / "sample-session.json"
    exported_path = tmp_path / "exported-session.json"
    saved_payload = json.loads(saved_path.read_text(encoding="utf-8"))
    exported_payload = json.loads(exported_path.read_text(encoding="utf-8"))
    assert saved_payload["format_version"] == 1
    assert saved_payload["defaults"]["container_ref"] == app.session.defaults.container_ref
    assert saved_payload["events"][0]["event_type"] == "manual_query"
    assert exported_payload["events"][0]["event_type"] == "manual_query"


def test_blank_required_prompt_reports_error_and_keeps_repl_alive(tmp_path) -> None:
    app, io = _build_app(tmp_path, ["/query", "", "/quit"])

    exit_code = app.run(mode="manual")

    assert exit_code == 0
    assert any("Required input missing for prompt: query text:" in line for line in io.outputs)

def test_run_returns_clean_exit_code_on_keyboard_interrupt(monkeypatch) -> None:
    import app.agent_simulation as agent_simulation_module
    import app.agent_simulation_terminal as terminal_module

    class FakeHTTP:
        def __init__(self, base_url: str) -> None:
            self.base_url = base_url

        def close(self) -> None:
            return None

    class FakeModelForRun:
        def __init__(self, provider_override=None, model_override=None) -> None:
            self.provider_override = provider_override
            self.model_override = model_override

        def resolution(self):
            return FakeResolution()

    def _interrupting_run(self, *, mode: str, replay_path: str | None = None) -> int:
        raise KeyboardInterrupt()

    monkeypatch.setattr(agent_simulation_module, 'HarnessHttpClient', FakeHTTP)
    monkeypatch.setattr(agent_simulation_module, 'ThinAgentModel', FakeModelForRun)
    monkeypatch.setattr(terminal_module, 'build_terminal_io', lambda: TerminalIO())
    monkeypatch.setattr(agent_simulation_module.AgentSimulationApp, 'run', _interrupting_run)

    assert run(['chat-lite']) == 130

def test_new_conversation_starts_new_thread_with_cross_thread_recall_defaults(tmp_path) -> None:
    app, _io = _build_app(tmp_path)
    original_container = app.session.defaults.container_ref
    original_thread = app.session.defaults.thread_ref

    assert app._handle_command("/new") is True

    defaults = app.session.defaults
    assert defaults.container_ref == original_container
    assert defaults.thread_ref != original_thread
    assert defaults.runtime_context["turn_kind"] == "new_thread"
    assert defaults.runtime_context["session_has_sufficient_local_context"] is False



def test_chat_lite_infers_same_thread_defaults_after_successful_turn(tmp_path) -> None:
    app, _io = _build_app(tmp_path, model=AcceptingModel())
    app._mode = "chat-lite"
    app.session.set_mode("chat-lite")

    app.process_chat_message("First turn")

    assert app.session.defaults.runtime_context["turn_kind"] == "same_thread_continuation"
    assert app.session.defaults.runtime_context["session_has_sufficient_local_context"] is True
    assert app.session.defaults.runtime_context_overrides == {}


def test_manual_runtime_context_overrides_survive_inferred_chat_defaults(tmp_path) -> None:
    app, _io = _build_app(tmp_path, model=AcceptingModel())
    app._mode = "chat-lite"
    app.session.set_mode("chat-lite")

    assert app._handle_command("/turn resumed_session") is True
    assert app._handle_command("/local-context false") is True

    app.process_chat_message("Resume this")

    assert app.session.defaults.runtime_context["turn_kind"] == "resumed_session"
    assert app.session.defaults.runtime_context["session_has_sufficient_local_context"] is False


def test_normal_chat_omits_runtime_context_without_manual_overrides(tmp_path) -> None:
    app, _io = _build_app(tmp_path, model=AcceptingModel())
    app._mode = "chat-lite"
    app.session.set_mode("chat-lite")

    app.process_chat_message("First turn")

    request = app.session.events[0]["query_debug"]["request"]
    assert "runtime_context" not in request


def test_manual_runtime_context_override_is_sent_in_query_payload(tmp_path) -> None:
    app, _io = _build_app(tmp_path, model=AcceptingModel())
    app._mode = "chat-lite"
    app.session.set_mode("chat-lite")

    assert app._handle_command("/turn resumed_session") is True
    assert app._handle_command("/local-context false") is True

    app.process_chat_message("Resume this")

    request = app.session.events[0]["query_debug"]["request"]
    assert request["runtime_context"] == {
        "turn_kind": "resumed_session",
        "session_has_sufficient_local_context": False,
    }


def test_help_defaults_to_basic_commands_and_supports_advanced_section(tmp_path) -> None:
    app, io = _build_app(tmp_path)

    assert app._handle_command("/help") is True
    assert app._handle_command("/help advanced") is True

    assert "/help advanced" in io.outputs
    assert "/turn" in io.outputs
    assert "/query-debug <text>" in io.outputs
