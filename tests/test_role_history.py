from __future__ import annotations

import pytest


def _ingest(client, *, source_id: str, role: str, thread: str, turn: str, name: str | None, state: str = "named", content: str = "shared planning marker"):
    payload = {
        "source_type": "codex",
        "source_id": source_id,
        "content_type": "text/plain",
        "content": content,
        "artifact_kind": "message",
        "role": role,
        "container_ref": "project:role-history",
        "thread_ref": thread,
        "visibility": "private",
        "source_turn_id": turn,
        "relay_name": name,
        "relay_attribution_state": state,
    }
    response = client.post("/items", json=[payload])
    assert response.status_code == 200, response.text
    return response.json()[0]["source_item_id"]


def _search(client, name: str, *, query: str = "shared planning marker", limit: int = 10):
    response = client.post("/query", json={
        "text": query,
        "limit": limit,
        "source_only": True,
        "trigger_origin": "agent_pull",
        "source_type": "codex",
        "relay_name": name,
        "container_ref": "project:role-history",
        "visibility": "private",
    })
    assert response.status_code == 200, response.text
    return response.json()


def _search_debug(client, name: str, *, query: str = "shared planning marker", limit: int = 10):
    response = client.post("/query/debug", json={
        "text": query,
        "limit": limit,
        "source_only": True,
        "trigger_origin": "agent_pull",
        "source_type": "codex",
        "relay_name": name,
        "container_ref": "project:role-history",
        "visibility": "private",
    })
    assert response.status_code == 200, response.text
    return response.json()


def test_relay_name_history_keeps_turn_start_name_across_sessions(client):
    first_user = _ingest(
        client, source_id="turn-a-user", role="user", thread="session-a",
        turn="turn-a", name="planner",
    )
    first_assistant = _ingest(
        client, source_id="turn-a-assistant", role="assistant", thread="session-a",
        turn="turn-a", name="taken-over-name", state="unavailable",
        content="shared planning marker assistant response after external takeover",
    )
    _ingest(
        client, source_id="turn-b-user", role="user", thread="session-b",
        turn="turn-b", name="planner",
        content="shared planning marker in successor session",
    )

    result = _search(client, "planner")
    hits = {item["source_item_id"]: item for item in result["results"]}
    assert first_user in hits
    assert first_assistant in hits
    assert len(hits) == 3
    assert hits[first_assistant]["relay_name"] == "planner"
    assert hits[first_assistant]["relay_attribution_state"] == "named"
    assert _search(client, "taken-over-name")["results"] == []


def test_relay_name_filter_runs_before_candidate_limit_and_reports_unavailable_coverage(client):
    for index in range(8):
        _ingest(
            client, source_id=f"wrong-{index}", role="user", thread=f"wrong-session-{index}",
            turn=f"wrong-turn-{index}", name="another-name",
        )
    matching = _ingest(
        client, source_id="matching-last", role="user", thread="matching-session",
        turn="matching-turn", name="target-name",
    )
    legacy = {
        "source_type": "codex", "source_id": "legacy-unknown", "content_type": "text/plain",
        "content": "shared planning marker from a legacy source", "artifact_kind": "message",
        "role": "user", "container_ref": "project:role-history", "thread_ref": "legacy-session",
        "visibility": "private",
    }
    assert client.post("/items", json=[legacy]).status_code == 200

    result = _search(client, "target-name", limit=1)
    assert [item["source_item_id"] for item in result["results"]] == [matching]
    assert result["incomplete_attribution"] is True

    debug_result = _search_debug(client, "target-name", limit=1)
    assert [item["source_item_id"] for item in debug_result["results"]] == [matching]
    assert debug_result["incomplete_attribution"] is True


def test_forgotten_turn_is_excluded_from_results_and_attribution_coverage(client):
    source_id = _ingest(
        client, source_id="forgotten-user", role="user", thread="forgotten-session",
        turn="forgotten-turn", name="planner",
    )
    forgotten = client.post("/source/forget", json={
        "source_item_id": source_id,
        "reason": "user requested removal",
    })
    assert forgotten.status_code == 200, forgotten.text
    assert forgotten.json()["forgotten"] is True

    result = _search(client, "planner")
    assert result["results"] == []
    assert result["incomplete_attribution"] is False


def test_repeated_codex_user_snapshot_reuses_only_same_attribution(client):
    source_id = _ingest(
        client, source_id="snapshot-first", role="user", thread="snapshot-session",
        turn="snapshot-turn", name="fixed-name",
    )
    retry = _ingest(
        client, source_id="snapshot-retry", role="user", thread="snapshot-session",
        turn="snapshot-turn", name="fixed-name",
    )
    assert retry == source_id

    service = client.app.state.pallium_service
    with pytest.raises(ValueError, match="conflicting source turn snapshot"):
        service.ingest_item(
            source_type="codex", source_id="snapshot-conflict", content_type="text/plain",
            content="shared planning marker", metadata=None, use_case=None, role="user", container_ref="project:role-history",
            thread_ref="snapshot-session", visibility="private", source_turn_id="snapshot-turn",
            relay_name="different-name", relay_attribution_state="named",
        )

    api_conflict = client.post("/items", json=[{
        "source_type": "codex", "source_id": "snapshot-api-conflict",
        "content_type": "text/plain", "content": "shared planning marker",
        "artifact_kind": "message", "role": "user",
        "container_ref": "project:role-history", "thread_ref": "snapshot-session",
        "visibility": "private", "source_turn_id": "snapshot-turn",
        "relay_name": "different-name", "relay_attribution_state": "named",
    }])
    assert api_conflict.status_code == 409, api_conflict.text


@pytest.mark.parametrize(
    ("competing_name", "expected_status"),
    [("fixed-name", 200), ("different-name", 409)],
)
def test_concurrent_user_snapshot_insert_reuses_equal_or_rejects_conflict(
    client, monkeypatch, competing_name: str, expected_status: int
):
    from dataclasses import replace
    from uuid import uuid4

    service = client.app.state.pallium_service
    storage = service._storage
    original_create = storage.create_source_item_with_packages
    competing_item_ids: list[str] = []

    def insert_competing_snapshot(source_item, package_names, *, skip_packages=None):
        competing = replace(
            source_item,
            id=uuid4().hex,
            source_id=f"concurrent-{uuid4().hex}",
            relay_name=competing_name,
        )
        original_create(competing, package_names, skip_packages=skip_packages)
        competing_item_ids.append(competing.id)
        return original_create(source_item, package_names, skip_packages=skip_packages)

    monkeypatch.setattr(storage, "create_source_item_with_packages", insert_competing_snapshot)
    response = client.post("/items", json=[{
        "source_type": "codex", "source_id": "concurrent-retry",
        "content_type": "text/plain", "content": "shared planning marker",
        "artifact_kind": "message", "role": "user",
        "container_ref": "project:role-history", "thread_ref": "concurrent-session",
        "visibility": "private", "source_turn_id": "concurrent-turn",
        "relay_name": "fixed-name", "relay_attribution_state": "named",
    }])

    assert response.status_code == expected_status, response.text
    if expected_status == 200:
        assert response.json()[0]["source_item_id"] == competing_item_ids[0]
    else:
        assert response.json()["detail"] == "conflicting source turn snapshot"


def test_codex_hooks_capture_start_name_and_link_delayed_stop(client, monkeypatch, tmp_path):
    from types import SimpleNamespace

    from integrations.codex.hooks import stop as stop_hook
    from integrations.codex.hooks import user_prompt_submit as prompt_hook

    container_ref = "project:role-history"
    session_id = "codex-session-a"
    second_session = "codex-session-b"
    registered = client.post("/relay/turn", json={
        "runtime": "codex", "session_ref": session_id, "container_ref": container_ref,
    })
    assert registered.status_code == 200, registered.text
    named = client.post("/relay/sessions/name", json={
        "runtime": "codex", "session_ref": session_id, "container_ref": container_ref,
        "alias": "planner",
    })
    assert named.status_code == 200, named.text

    def current_relay_turn(runtime, session_ref, scope, **_kwargs):
        response = client.post("/relay/turn", json={
            "runtime": runtime, "session_ref": session_ref, "container_ref": scope,
        })
        assert response.status_code == 200, response.text
        return response.json()

    monkeypatch.setattr(prompt_hook, "start_hook_deadline", lambda *a, **k: None)
    monkeypatch.setattr(prompt_hook, "record_codex_hook_execution", lambda **k: True)
    monkeypatch.setattr(prompt_hook, "record_codex_wake_event", lambda **k: None)
    monkeypatch.setattr(prompt_hook, "resolve_container_ref", lambda *a, **k: container_ref)
    monkeypatch.setattr(prompt_hook, "derive_actor_ref", lambda *a, **k: "codex-actor")
    monkeypatch.setattr(prompt_hook, "discover_work_refs", lambda *_a, **_k: None)
    monkeypatch.setattr(prompt_hook, "injected_work_ref", lambda *_a, **_k: None)
    monkeypatch.setattr(prompt_hook, "structural_work_refs_payload", lambda *_a, **_k: [])
    monkeypatch.setattr(prompt_hook, "confirmed_registry_work_refs", lambda *_a, **_k: [])
    monkeypatch.setattr(prompt_hook, "relay_turn", current_relay_turn)
    monkeypatch.setattr(prompt_hook, "format_injection", lambda *_a, **_k: "scope")
    monkeypatch.setattr(prompt_hook, "emit_context", lambda *_a, **_k: True)
    monkeypatch.setattr(prompt_hook, "check_dedup", lambda *_a, **_k: False)
    monkeypatch.setattr(prompt_hook, "build_work_refs_metadata", lambda *_a, **_k: {})
    monkeypatch.setattr(prompt_hook, "work_ref_warning", lambda *_a, **_k: "")
    monkeypatch.setattr(prompt_hook, "pallium_request", lambda method, path, body, **_k: client.post(path, json=body).json())

    def run_prompt(turn_id: str, prompt: str) -> None:
        monkeypatch.setattr(prompt_hook, "read_hook_input", lambda: {
            "cwd": str(tmp_path), "session_id": session_id, "turn_id": turn_id, "prompt": prompt,
        })
        with pytest.raises(SystemExit) as exit_result:
            prompt_hook.main()
        assert exit_result.value.code == 0

    def run_stop(turn_id: str, text: str) -> None:
        monkeypatch.setattr(stop_hook, "start_hook_deadline", lambda *a, **k: None)
        monkeypatch.setattr(stop_hook, "read_hook_input", lambda: {
            "cwd": str(tmp_path), "session_id": session_id, "turn_id": turn_id,
            "transcript_path": str(tmp_path / "transcript.jsonl"),
        })
        monkeypatch.setattr(stop_hook, "read_turn", lambda *_a, **_k: SimpleNamespace(
            assistant_text=text, tool_calls=[], files_modified=[]
        ))
        monkeypatch.setattr(stop_hook, "resolve_container_ref", lambda *a, **k: container_ref)
        monkeypatch.setattr(stop_hook, "derive_actor_ref", lambda *a, **k: "codex-actor")
        monkeypatch.setattr(stop_hook, "fetch_confirmed_work_refs", lambda *_a, **_k: ([], "complete"))
        monkeypatch.setattr(stop_hook, "build_work_refs_metadata", lambda *_a, **_k: {})
        monkeypatch.setattr(stop_hook, "work_ref_warning", lambda *_a, **_k: "")
        monkeypatch.setattr(stop_hook, "pallium_request", lambda method, path, body, **_k: client.post(path, json=body).json())
        with pytest.raises(SystemExit) as exit_result:
            stop_hook.main()
        assert exit_result.value.code == 0

    run_prompt("codex-native-turn-42", "whole-turn marker from user")
    client.post("/relay/turn", json={
        "runtime": "codex", "session_ref": second_session, "container_ref": container_ref,
    })
    takeover = client.post("/relay/sessions/name", json={
        "runtime": "codex", "session_ref": second_session, "container_ref": container_ref,
        "alias": "planner", "replace_existing": True,
    })
    assert takeover.status_code == 200, takeover.text
    resumed_identity = current_relay_turn("codex", session_id, container_ref)
    assert resumed_identity["session"]["alias"] is None
    run_stop("codex-native-turn-42", "whole-turn marker from assistant after takeover")

    # When the original session resumes, the turn-start response now says
    # explicitly unnamed. Stop continues to inherit that source snapshot.
    run_prompt("codex-native-turn-43", "second-turn marker from resumed session")
    resumed_snapshot = client.app.state.pallium_service._storage.find_source_turn_snapshot(
        "codex", container_ref, session_id, "codex-native-turn-43"
    )
    assert resumed_snapshot.relay_attribution_state == "unnamed"
    run_stop("codex-native-turn-43", "second-turn marker assistant output")

    result = _search(client, "planner", query="whole-turn marker")
    assert len(result["results"]) == 2
    assert {item["role"] for item in result["results"]} == {"user", "assistant"}
    assert {item["relay_name"] for item in result["results"]} == {"planner"}
    assert _search(client, "planner", query="resumed session")["results"] == []


def test_codex_native_turn_and_relay_name_fields_fail_closed():
    from integrations.codex.hooks.common import relay_name_snapshot, source_turn_key

    assert relay_name_snapshot({"session": {"alias": "planner"}}) == ("named", "planner")
    assert relay_name_snapshot({"session": {"alias": None}}) == ("unnamed", None)
    assert relay_name_snapshot({"session": {}}) == ("unavailable", None)
    assert relay_name_snapshot({"session": {"alias": "Bad Name"}}) == ("unavailable", None)
    assert source_turn_key("codex-turn-1") == "codex-turn-1"
    assert source_turn_key(" codex-turn-1") is None
    assert source_turn_key("bad\nturn") is None
    assert source_turn_key("x" * 513) is None

def test_existing_sqlite_rows_migrate_to_unknown_attribution(tmp_path):
    from core.models import SourceItem
    from storage.sqlite import SQLiteStorageProvider

    db_path = tmp_path / "role-history-legacy.db"
    db_url = f"sqlite:///{db_path}"
    storage = SQLiteStorageProvider(db_url)
    legacy = SourceItem(
        source_type="codex", source_id="old-turn", content_type="text/plain",
        content="historic source", role="user", container_ref="project:role-history",
        thread_ref="old-session", visibility="private", source_turn_id="old-key",
        relay_name="planner", relay_attribution_state="named",
    )
    storage.create_source_item(legacy)
    with storage._engine.begin() as connection:
        connection.exec_driver_sql("DROP INDEX uq_source_items_user_turn_snapshot")
        connection.exec_driver_sql("ALTER TABLE source_items DROP COLUMN source_turn_id")
        connection.exec_driver_sql("ALTER TABLE source_items DROP COLUMN relay_name")
        connection.exec_driver_sql("ALTER TABLE source_items DROP COLUMN relay_attribution_state")
    storage.close()

    migrated = SQLiteStorageProvider(db_url)
    restored = migrated.get_source_item(legacy.id)
    assert restored.source_turn_id is None
    assert restored.relay_name is None
    assert restored.relay_attribution_state == "unknown"
    migrated.close()

