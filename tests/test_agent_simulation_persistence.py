from __future__ import annotations

from dataclasses import dataclass

from app.agent_simulation import AgentSimulationApp, TerminalIO
from app.agent_simulation_render import render_replay_diff
from app.agent_simulation_session import HarnessSession, ScopeDefaults, SessionStore, rewrite_payload_for_replay


class FakeIO:
    def __init__(self) -> None:
        self.outputs: list[str] = []

    def prompt(self, text: str) -> str:
        raise AssertionError(f"unexpected prompt: {text}")

    def write(self, text: str) -> None:
        self.outputs.append(text)


class ReplayHTTPClient:
    def __init__(self) -> None:
        self.base_url = "http://example.test"
        self.created_items: list[dict] = []
        self.query_requests: list[dict] = []
        self.query_debug_requests: list[dict] = []

    def create_item(self, payload):
        self.created_items.append(payload)
        return {"source_item_id": payload["source_id"], "processing_status": "pending"}

    def query(self, payload):
        self.query_requests.append(payload)
        return {
            "results": [{"result_kind": "memory_hit", "type": "decision", "payload": {"summary": "current query result"}}],
            "should_inject": False,
            "decision_reason": "same_thread_context_sufficient",
            "injectable_blocks": [],
        }

    def query_debug(self, payload):
        self.query_debug_requests.append(payload)
        return {
            "results": [],
            "should_inject": False,
            "decision_reason": "same_thread_context_sufficient",
            "injectable_blocks": [],
            "trace": {"routing": {}, "visibility": {}, "stages": []},
        }

    def close(self):
        return None


@dataclass(frozen=True)
class FakeResolution:
    def to_dict(self):
        return {"available": False, "provider_name": None, "provider_kind": None, "model": None, "failure_reason": "not configured"}


class FakeModel:
    def resolution(self):
        return FakeResolution()


def test_session_store_roundtrip_preserves_metadata_and_events(tmp_path) -> None:
    store = SessionStore(tmp_path)
    session = HarnessSession(
        session_id="session-1",
        created_at="2026-03-16T10:00:00+00:00",
        updated_at="2026-03-16T10:00:00+00:00",
        base_url="http://127.0.0.1:8000",
        mode="chat",
        debug_enabled=True,
        defaults=ScopeDefaults(
            container_ref="container-1",
            thread_ref="thread-1",
            session_ref="session-1",
            visibility_context={"kind": "limited", "id": "scope-1"},
            runtime_context={"turn_kind": "new_thread", "session_has_sufficient_local_context": False},
            runtime_context_overrides={"turn_kind": True},
        ),
        model={"provider_name": "fake", "model": "fake-model"},
        events=[{"event_type": "chat_turn", "user_message": "hello"}],
    )

    path = store.save(session, "roundtrip")
    loaded = store.load(path)

    assert loaded.session_id == "session-1"
    assert loaded.debug_enabled is True
    assert loaded.defaults.visibility_context == {"kind": "limited", "id": "scope-1"}
    assert loaded.defaults.runtime_context_overrides == {"turn_kind": True}
    assert loaded.events[0]["user_message"] == "hello"


def test_rewrite_payload_for_replay_prefixes_source_and_scope_refs() -> None:
    payload = {
        "source_id": "msg-1",
        "thread_ref": "thread-1",
        "session_ref": "session-1",
        "container_ref": "container-1",
    }

    rewritten = rewrite_payload_for_replay(payload, "replay-1")

    assert rewritten["source_id"] == "replay-1:msg-1"
    assert rewritten["thread_ref"] == "replay-1:thread-1"
    assert rewritten["session_ref"] == "replay-1:session-1"
    assert rewritten["container_ref"] == "container-1"


def test_render_replay_diff_ignores_rewritten_ids_when_semantics_are_stable() -> None:
    recorded = {
        "results": [
            {
                "result_kind": "memory_hit",
                "result_id": "memory_object:old-1",
                "type": "decision",
                "payload": {"summary": "Use item event time."},
            }
        ],
        "should_inject": True,
        "decision_reason": "carry_forward_available",
        "injectable_blocks": [{"text": "Use item event time."}],
        "trace": {"routing": {"selected_layer": "decision", "query_intent": "recurring_question"}},
    }
    current = {
        "results": [
            {
                "result_kind": "memory_hit",
                "result_id": "memory_object:new-1",
                "type": "decision",
                "payload": {"summary": "Use item event time."},
            }
        ],
        "should_inject": True,
        "decision_reason": "carry_forward_available",
        "injectable_blocks": [{"text": "Use item event time."}],
        "trace": {"routing": {"selected_layer": "decision", "query_intent": "recurring_question"}},
    }

    lines = render_replay_diff(recorded, current)

    assert not any("top_results changed" in line for line in lines)


def test_replay_reruns_saved_chat_turns_with_rewritten_refs_and_reports_diff(tmp_path) -> None:
    store = SessionStore(tmp_path)
    saved_session = HarnessSession(
        session_id="saved-session",
        created_at="2026-03-16T10:00:00+00:00",
        updated_at="2026-03-16T10:00:00+00:00",
        base_url="http://127.0.0.1:8000",
        mode="chat",
        debug_enabled=False,
        defaults=ScopeDefaults(
            container_ref="container-1",
            thread_ref="thread-1",
            session_ref="session-1",
            visibility_context={"kind": "public", "id": None},
            runtime_context={"turn_kind": "same_thread_continuation", "session_has_sufficient_local_context": None},
        ),
        model={"provider_name": "fake", "model": "fake-model"},
        events=[
            {
                "event_type": "chat_turn",
                "user_message": "hello",
                "user_item": {
                    "request": {"source_id": "msg-1", "source_type": "chat_message", "content_type": "text/plain", "content": "hello", "thread_ref": "thread-1", "session_ref": "session-1", "container_ref": "container-1", "artifact_kind": "message", "role": "user", "visibility_context": {"kind": "public", "id": None}},
                    "response": {"source_item_id": "msg-1"},
                },
                "query_debug": {
                    "request": {"text": "hello", "thread_ref": "thread-1", "session_ref": "session-1", "container_ref": "container-1", "visibility_context": {"kind": "public", "id": None}},
                    "response": {"results": [], "should_inject": True, "decision_reason": "carry_forward_available", "injectable_blocks": [{"text": "recorded block"}], "trace": {"routing": {"selected_layer": "decision", "query_intent": "recurring_question"}}},
                },
                "assistant": {
                    "request": {"source_id": "assistant-1", "source_type": "assistant_artifact", "content_type": "text/plain", "content": "saved answer", "thread_ref": "thread-1", "session_ref": "session-1", "container_ref": "container-1", "artifact_kind": "assistant_output", "role": "assistant", "visibility_context": {"kind": "public", "id": None}},
                    "response": {"source_item_id": "assistant-1"},
                },
            }
        ],
    )
    path = store.save(saved_session, "replay-source")
    io = FakeIO()
    http_client = ReplayHTTPClient()
    app = AgentSimulationApp(
        http_client=http_client,
        io=TerminalIO(input_func=io.prompt, output_func=io.write),
        session_store=store,
        model=FakeModel(),
    )

    app.run(mode="replay", replay_path=str(path))

    assert http_client.created_items[0]["source_id"].startswith("replay:")
    assert http_client.created_items[0]["thread_ref"].startswith("replay:")
    assert http_client.created_items[0]["session_ref"].startswith("replay:")
    assert http_client.query_debug_requests[0]["thread_ref"].startswith("replay:")
    assert any("recorded should_inject=True current=False" in line for line in io.outputs)


def test_replay_reports_diff_for_saved_manual_query_events(tmp_path) -> None:
    store = SessionStore(tmp_path)
    saved_session = HarnessSession(
        session_id="saved-session",
        created_at="2026-03-16T10:00:00+00:00",
        updated_at="2026-03-16T10:00:00+00:00",
        base_url="http://127.0.0.1:8000",
        mode="manual",
        debug_enabled=False,
        defaults=ScopeDefaults(
            container_ref="container-1",
            thread_ref="thread-1",
            session_ref="session-1",
            visibility_context={"kind": "public", "id": None},
            runtime_context={"turn_kind": None, "session_has_sufficient_local_context": None},
        ),
        model={"provider_name": "fake", "model": "fake-model"},
        events=[
            {
                "event_type": "manual_query",
                "request": {"text": "hello", "thread_ref": "thread-1", "session_ref": "session-1", "container_ref": "container-1", "visibility_context": {"kind": "public", "id": None}},
                "response": {"results": [{"result_kind": "memory_hit", "type": "decision", "payload": {"summary": "recorded query result"}}], "should_inject": True, "decision_reason": "carry_forward_available", "injectable_blocks": [{"text": "recorded block"}]},
            }
        ],
    )
    path = store.save(saved_session, "manual-query-replay")
    io = FakeIO()
    http_client = ReplayHTTPClient()
    app = AgentSimulationApp(
        http_client=http_client,
        io=TerminalIO(input_func=io.prompt, output_func=io.write),
        session_store=store,
        model=FakeModel(),
    )

    app.run(mode="replay", replay_path=str(path))

    assert http_client.query_requests[0]["thread_ref"].startswith("replay:")
    assert any("recorded should_inject=True current=False" in line for line in io.outputs)
    assert any("top_results changed" in line for line in io.outputs)
