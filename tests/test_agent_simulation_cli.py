from __future__ import annotations

import json
from dataclasses import dataclass

from app.agent_simulation import AgentSimulationApp, TerminalIO, build_parser
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


def _build_app(tmp_path, responses: list[str] | None = None) -> tuple[AgentSimulationApp, FakeIO]:
    io = FakeIO(responses)
    app = AgentSimulationApp(
        http_client=FakeHTTPClient(),
        io=TerminalIO(input_func=io.prompt, output_func=io.write),
        session_store=SessionStore(tmp_path),
        model=FakeModel(),
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
    app, _io = _build_app(tmp_path, ["container-1", "thread-1", "session-1", "limited", "scope-1"])

    assert app._handle_command("/scope") is True
    assert app._handle_command("/turn resumed_session") is True
    assert app._handle_command("/local-context true") is True
    assert app._handle_command("/mode chat-lite") is True
    assert app._handle_command("/mode manual") is True

    defaults = app.session.defaults
    assert defaults.container_ref == "container-1"
    assert defaults.thread_ref == "thread-1"
    assert defaults.session_ref == "session-1"
    assert defaults.visibility_context == {"kind": "limited", "id": "scope-1"}
    assert defaults.runtime_context["turn_kind"] == "resumed_session"
    assert defaults.runtime_context["session_has_sufficient_local_context"] is True
    assert app.session.mode == "manual"


def test_fork_preserves_session_by_default_and_can_rotate_with_flag(tmp_path) -> None:
    app, _io = _build_app(tmp_path)
    original_container = app.session.defaults.container_ref
    original_session = app.session.defaults.session_ref
    original_thread = app.session.defaults.thread_ref

    assert app._handle_command("/fork") is True
    assert app.session.defaults.container_ref == original_container
    assert app.session.defaults.session_ref == original_session
    assert app.session.defaults.thread_ref != original_thread

    forked_thread = app.session.defaults.thread_ref
    assert app._handle_command("/fork --new-session") is True
    assert app.session.defaults.container_ref == original_container
    assert app.session.defaults.thread_ref != forked_thread
    assert app.session.defaults.session_ref != original_session


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
