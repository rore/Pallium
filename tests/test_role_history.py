from __future__ import annotations

import pytest


def _ingest(client, *, source_id: str, role: str, thread: str, turn: str, name: str | None, state: str = "named", content: str = "shared planning marker", source_type: str = "codex"):
    payload = {
        "source_type": source_type,
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


def _search(client, name: str, *, query: str = "shared planning marker", limit: int = 10, source_type: str = "codex"):
    response = client.post("/query", json={
        "text": query,
        "limit": limit,
        "source_only": True,
        "trigger_origin": "agent_pull",
        "source_type": source_type,
        "relay_name": name,
        "container_ref": "project:role-history",
        "visibility": "private",
    })
    assert response.status_code == 200, response.text
    return response.json()


def _search_debug(client, name: str, *, query: str = "shared planning marker", limit: int = 10, source_type: str = "codex"):
    response = client.post("/query/debug", json={
        "text": query,
        "limit": limit,
        "source_only": True,
        "trigger_origin": "agent_pull",
        "source_type": source_type,
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


def test_claude_prompt_turn_snapshot_inherits_name_and_keeps_stop_captures_distinct(client):
    prompt_id = "550e8400-e29b-41d4-a716-446655440000"
    user_id = _ingest(
        client, source_type="claude-code", source_id="claude-user-first", role="user",
        thread="claude-session", turn=prompt_id, name="planner",
    )
    retry_id = _ingest(
        client, source_type="claude-code", source_id="claude-user-retry", role="user",
        thread="claude-session", turn=prompt_id, name="planner",
    )
    assert retry_id == user_id

    first_stop = _ingest(
        client, source_type="claude-code", source_id="claude-stop-one", role="assistant",
        thread="claude-session", turn=prompt_id, name="different-name", state="unavailable",
        content="shared planning marker first response",
    )
    second_stop = _ingest(
        client, source_type="claude-code", source_id="claude-stop-retry", role="assistant",
        thread="claude-session", turn=prompt_id, name=None, state="unavailable",
        content="shared planning marker repeated Stop response",
    )
    assert first_stop != second_stop

    hits = _search(client, "planner", source_type="claude-code")["results"]
    by_id = {item["source_item_id"]: item for item in hits}
    assert {user_id, first_stop, second_stop} <= by_id.keys()
    assert by_id[first_stop]["relay_name"] == by_id[second_stop]["relay_name"] == "planner"

    conflict = client.post("/items", json=[{
        "source_type": "claude-code", "source_id": "claude-user-conflict",
        "content_type": "text/plain", "content": "conflicting retry",
        "artifact_kind": "message", "role": "user",
        "container_ref": "project:role-history", "thread_ref": "claude-session",
        "visibility": "private", "source_turn_id": prompt_id,
        "relay_name": "other-name", "relay_attribution_state": "named",
    }])
    assert conflict.status_code == 409, conflict.text


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


@pytest.mark.parametrize("source_type", ("codex", "claude-code"))
def test_forgotten_turn_is_excluded_from_results_and_attribution_coverage(client, source_type):
    source_id = _ingest(
        client, source_id="forgotten-user", role="user", thread="forgotten-session",
        turn=("550e8400-e29b-41d4-a716-446655440003" if source_type == "claude-code" else "forgotten-turn"),
        name="planner", source_type=source_type,
    )
    forgotten = client.post("/source/forget", json={
        "source_item_id": source_id,
        "reason": "user requested removal",
    })
    assert forgotten.status_code == 200, forgotten.text
    assert forgotten.json()["forgotten"] is True

    result = _search(client, "planner", source_type=source_type)
    assert result["results"] == []
    assert result["incomplete_attribution"] is False


def test_claude_stop_without_correlating_prompt_id_stays_unavailable(client):
    _ingest(
        client, source_type="claude-code", source_id="claude-compacted-user", role="user",
        thread="claude-compacted-session", turn="550e8400-e29b-41d4-a716-446655440002",
        name="planner",
    )
    response = client.post("/items", json=[{
        "source_type": "claude-code", "source_id": "claude-compacted-stop-no-key",
        "content_type": "text/plain", "content": "assistant output after compact resumed",
        "artifact_kind": "message", "role": "assistant",
        "container_ref": "project:role-history", "thread_ref": "claude-compacted-session",
        "visibility": "private",
    }])
    assert response.status_code == 200, response.text
    result = _search(
        client, "planner", query="assistant output after compact resumed",
        source_type="claude-code",
    )
    assert result["results"] == []
    assert result["incomplete_attribution"] is True


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


@pytest.mark.parametrize("source_type", ("opencode", "hermes"))
def test_additional_adapters_inherit_the_existing_immutable_turn_snapshot(client, source_type):
    user_id = _ingest(
        client, source_type=source_type, source_id=f"{source_type}-user", role="user",
        thread=f"{source_type}-session", turn=f"{source_type}-native-turn", name="planner",
    )
    assistant_id = _ingest(
        client, source_type=source_type, source_id=f"{source_type}-assistant", role="assistant",
        thread=f"{source_type}-session", turn=f"{source_type}-native-turn", name="ignored-name",
        state="unavailable", content=f"{source_type} assistant turn marker",
    )

    result = _search(
        client, "planner", query=f"{source_type} assistant turn marker", source_type=source_type,
    )
    hits = {item["source_item_id"]: item for item in result["results"]}
    assert set(hits) == {user_id, assistant_id}
    assert hits[user_id]["role"] == "user"
    assert hits[user_id]["relay_name"] == "planner"
    assert hits[assistant_id]["role"] == "assistant"
    assert hits[assistant_id]["relay_name"] == "planner"
    assert hits[assistant_id]["relay_attribution_state"] == "named"


def test_role_source_id_retries_reject_key_snapshot_scope_and_forgotten_conflicts(client):
    source_id = _ingest(
        client, source_id="role-source-id", role="user", thread="source-id-session",
        turn="source-id-turn", name="planner",
    )
    base = {
        "source_type": "codex", "source_id": "role-source-id", "content_type": "text/plain",
        "content": "same source item", "artifact_kind": "message", "role": "user",
        "container_ref": "project:role-history", "thread_ref": "source-id-session",
        "visibility": "private",
    }
    conflicting_retries = (
        {**base, "source_turn_id": "different-turn", "relay_name": "planner", "relay_attribution_state": "named"},
        {**base, "source_turn_id": "source-id-turn", "relay_name": "different-name", "relay_attribution_state": "named"},
        {**base, "source_turn_id": "source-id-turn", "relay_name": "planner", "relay_attribution_state": "named", "thread_ref": "other-session"},
        {**base, "source_turn_id": None, "relay_attribution_state": "unavailable"},
    )
    for payload in conflicting_retries:
        response = client.post("/items", json=[payload])
        assert response.status_code == 409, response.text

    forgotten = client.post("/source/forget", json={
        "source_item_id": source_id, "reason": "user requested removal",
    })
    assert forgotten.status_code == 200, forgotten.text
    response = client.post("/items", json=[{
        **base, "source_turn_id": "source-id-turn", "relay_name": "planner",
        "relay_attribution_state": "named",
    }])
    assert response.status_code == 409, response.text


def test_forgotten_assistant_source_id_retry_fails_closed(client):
    _ingest(
        client, source_id="forgotten-assistant-user", role="user", thread="forgotten-assistant-session",
        turn="forgotten-assistant-turn", name="planner",
    )
    assistant_id = _ingest(
        client, source_id="forgotten-assistant-row", role="assistant", thread="forgotten-assistant-session",
        turn="forgotten-assistant-turn", name=None, state="unavailable", content="assistant output",
    )
    forgotten = client.post("/source/forget", json={
        "source_item_id": assistant_id, "reason": "user requested removal",
    })
    assert forgotten.status_code == 200, forgotten.text

    retry = client.post("/items", json=[{
        "source_type": "codex", "source_id": "forgotten-assistant-row",
        "content_type": "text/plain", "content": "assistant output",
        "artifact_kind": "message", "role": "assistant",
        "container_ref": "project:role-history", "thread_ref": "forgotten-assistant-session",
        "visibility": "private", "source_turn_id": "forgotten-assistant-turn",
    }])
    assert retry.status_code == 409, retry.text


def test_assistant_requires_exact_unforgotten_user_snapshot(client):
    assistant = {
        "source_type": "opencode", "source_id": "orphan-assistant",
        "content_type": "text/plain", "content": "delayed assistant output",
        "artifact_kind": "message", "role": "assistant",
        "container_ref": "project:role-history", "thread_ref": "orphan-session",
        "visibility": "private", "source_turn_id": "orphan-native-user",
    }
    response = client.post("/items", json=[assistant])
    assert response.status_code == 409, response.text

    user_id = _ingest(
        client, source_type="opencode", source_id="orphan-user", role="user",
        thread="orphan-session", turn="orphan-native-user", name="planner",
    )
    recovered = client.post("/items", json=[assistant])
    assert recovered.status_code == 200, recovered.text
    assistant_id = recovered.json()[0]["source_item_id"]
    history = _search(
        client, "planner", query="delayed assistant output", source_type="opencode",
    )
    assert [item["source_item_id"] for item in history["results"]] == [assistant_id]
    assert history["results"][0]["role"] == "assistant"
    assert history["results"][0]["relay_name"] == "planner"
    assert history["results"][0]["relay_attribution_state"] == "named"

    forgotten = client.post("/source/forget", json={
        "source_item_id": user_id, "reason": "user requested removal",
    })
    assert forgotten.status_code == 200, forgotten.text
    second_assistant = {
        **assistant, "source_id": "assistant-after-forgotten-user",
        "content": "another delayed assistant output",
    }
    after_forget = client.post("/items", json=[second_assistant])
    assert after_forget.status_code == 409, after_forget.text


def test_integrity_error_source_id_recovery_checks_role_snapshot_conflict(client, monkeypatch):
    from dataclasses import replace
    from uuid import uuid4

    service = client.app.state.pallium_service
    storage = service._storage
    original_create = storage.create_source_item_with_packages
    inserted: list[str] = []

    def insert_conflicting_source_id(source_item, package_names, *, skip_packages=None):
        competing = replace(
            source_item,
            id=uuid4().hex,
            source_turn_id="other-turn",
            relay_name="other-name",
            relay_attribution_state="named",
        )
        original_create(competing, package_names, skip_packages=skip_packages)
        inserted.append(competing.id)
        return original_create(source_item, package_names, skip_packages=skip_packages)

    monkeypatch.setattr(storage, "create_source_item_with_packages", insert_conflicting_source_id)
    response = client.post("/items", json=[{
        "source_type": "opencode", "source_id": "integrity-collision",
        "content_type": "text/plain", "content": "integrity collision marker",
        "artifact_kind": "message", "role": "user",
        "container_ref": "project:role-history", "thread_ref": "integrity-session",
        "visibility": "private", "source_turn_id": "requested-turn",
        "relay_name": "planner", "relay_attribution_state": "named",
    }])

    assert inserted
    assert response.status_code == 409, response.text


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
