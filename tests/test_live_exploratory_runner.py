from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.config import AppConfig
from app.live_exploratory_runner import (
    BackgroundProcessor,
    StageTimeoutError,
    wait_for_item_processing,
    wait_for_turn_event_processing,
)
from app.main import create_app
from core.contracts import ItemProcessingResult


def _processing_result(
    source_item_id: str,
    *,
    processing_status: str = "completed",
    thread_rebuild_requested: bool = False,
    thread_rebuild_completed: bool = False,
) -> ItemProcessingResult:
    return ItemProcessingResult(
        source_item_id=source_item_id,
        use_case="demo_agent_memory",
        processing_status=processing_status,
        processing_attempts=1,
        processing_claimed_at=None,
        processing_completed_at=None,
        processing_error=None,
        annotation_ids=[],
        memory_object_ids=[],
        relation_ids=[],
        index_entry_ids=[],
        thread_rebuild_requested=thread_rebuild_requested,
        thread_rebuild_completed=thread_rebuild_completed,
    )


def _item_payload(source_id: str, content: str) -> dict[str, object]:
    return {
        "source_type": "decision_note",
        "source_id": source_id,
        "content_type": "text/plain",
        "content": content,
        "artifact_kind": "assistant_output",
        "role": "assistant",
    }


def test_wait_for_item_processing_waits_for_thread_rebuild_completion_when_requested() -> None:
    statuses = [
        _processing_result("source-1", thread_rebuild_requested=True, thread_rebuild_completed=False),
        _processing_result("source-1", thread_rebuild_requested=True, thread_rebuild_completed=True),
    ]

    def get_status(_source_item_id: str) -> ItemProcessingResult:
        if len(statuses) > 1:
            return statuses.pop(0)
        return statuses[0]

    outcome = wait_for_item_processing(
        get_status,
        "source-1",
        stage_timeout_label="thread_rebuild_timeout",
        timeout_seconds=0.5,
        poll_interval_seconds=0.01,
        wait_for_thread_rebuild=True,
    )

    assert outcome.status.thread_rebuild_completed is True
    assert outcome.thread_rebuild_wait_seconds > 0


def test_wait_for_item_processing_raises_stage_specific_timeout() -> None:
    def get_status(_source_item_id: str) -> ItemProcessingResult:
        return _processing_result("source-timeout", processing_status="pending")

    try:
        wait_for_item_processing(
            get_status,
            "source-timeout",
            stage_timeout_label="user_item_processing_timeout",
            timeout_seconds=0.01,
            poll_interval_seconds=0.0,
        )
    except StageTimeoutError as exc:
        assert exc.stage_label == "user_item_processing_timeout"
        assert exc.source_item_id == "source-timeout"
    else:  # pragma: no cover - defensive failure path
        raise AssertionError("expected StageTimeoutError")


def test_wait_for_turn_event_processing_skips_followup_wait_when_not_required() -> None:
    event = {
        "user_item": {"response": {"source_item_id": "user-1"}},
        "assistant": {"response": {"source_item_id": "assistant-1"}},
    }
    calls: list[str] = []
    drained: list[bool] = []

    def get_status(source_item_id: str) -> ItemProcessingResult:
        calls.append(source_item_id)
        return _processing_result(source_item_id)

    result = wait_for_turn_event_processing(
        get_status,
        event,
        wait_for_user_processing=False,
        wait_for_assistant_processing=False,
        wait_for_thread_rebuild=False,
        timeout_seconds=0.1,
        poll_interval_seconds=0.0,
        user_timeout_label="followup_user_processing_timeout",
        assistant_timeout_label="followup_processing_timeout",
        use_full_queue_drain=False,
        drain_fn=lambda: drained.append(True),
    )

    assert calls == []
    assert drained == []
    assert result["assistant_item_processing"] is None


def test_targeted_waits_complete_for_user_and_assistant_without_full_drain(test_db_url: str) -> None:
    config = AppConfig(storage_backend="sqlite", sqlite_url=test_db_url, default_use_case="demo_agent_memory")
    client = TestClient(create_app(config))
    try:
        user_response = client.post("/items", json=_item_payload("targeted-user", "Decision: user stage."))
        assistant_response = client.post("/items", json=_item_payload("targeted-assistant", "Decision: assistant stage."))
        assert user_response.status_code == 200
        assert assistant_response.status_code == 200
        event = {
            "user_item": {"response": user_response.json()},
            "assistant": {"response": assistant_response.json()},
        }

        with BackgroundProcessor(config=config, worker_id="targeted-waits", poll_interval_seconds=0.01):
            waits = wait_for_turn_event_processing(
                client.app.state.pallium_service.get_item_processing,
                event,
                wait_for_user_processing=True,
                wait_for_assistant_processing=True,
                wait_for_thread_rebuild=False,
                timeout_seconds=2.0,
                poll_interval_seconds=0.01,
                user_timeout_label="user_item_processing_timeout",
                assistant_timeout_label="assistant_item_processing_timeout",
                use_full_queue_drain=False,
            )

        assert waits["used_full_queue_drain"] is False
        assert waits["user_item_processing"]["final_status"]["processing_status"] == "completed"
        assert waits["assistant_item_processing"]["final_status"]["processing_status"] == "completed"
    finally:
        client.close()


def test_background_processor_processes_pending_item_and_stops_cleanly(test_db_url: str) -> None:
    config = AppConfig(storage_backend="sqlite", sqlite_url=test_db_url, default_use_case="demo_agent_memory")
    client = TestClient(create_app(config))
    try:
        response = client.post("/items", json=_item_payload("background-processor-1", "Decision: process this item."))
        assert response.status_code == 200
        source_item_id = response.json()["source_item_id"]
        processor = BackgroundProcessor(config=config, worker_id="background-processor", poll_interval_seconds=0.01)
        processor.start()
        outcome = wait_for_item_processing(
            client.app.state.pallium_service.get_item_processing,
            source_item_id,
            stage_timeout_label="user_item_processing_timeout",
            timeout_seconds=2.0,
            poll_interval_seconds=0.01,
        )
        processor.stop()

        assert outcome.status.processing_status == "completed"
        assert processor.is_alive is False
    finally:
        client.close()


def test_scenario_isolation_keeps_separate_sqlite_dbs(test_db_url: str) -> None:
    first_db_url = test_db_url.replace("test.db", "live-runner-first.db")
    second_db_url = test_db_url.replace("test.db", "live-runner-second.db")
    shared_source_id = "live-runner-isolation"

    first_config = AppConfig(storage_backend="sqlite", sqlite_url=first_db_url, default_use_case="demo_agent_memory")
    second_config = AppConfig(storage_backend="sqlite", sqlite_url=second_db_url, default_use_case="demo_agent_memory")

    first_client = TestClient(create_app(first_config))
    second_client = TestClient(create_app(second_config))
    try:
        first_response = first_client.post("/items", json=_item_payload(shared_source_id, "Decision: first db content."))
        second_response = second_client.post("/items", json=_item_payload(shared_source_id, "Decision: second db content."))
        assert first_response.status_code == 200
        assert second_response.status_code == 200

        with BackgroundProcessor(config=first_config, worker_id="isolation-first", poll_interval_seconds=0.01):
            wait_for_item_processing(
                first_client.app.state.pallium_service.get_item_processing,
                first_response.json()["source_item_id"],
                stage_timeout_label="user_item_processing_timeout",
                timeout_seconds=2.0,
                poll_interval_seconds=0.01,
            )
        with BackgroundProcessor(config=second_config, worker_id="isolation-second", poll_interval_seconds=0.01):
            wait_for_item_processing(
                second_client.app.state.pallium_service.get_item_processing,
                second_response.json()["source_item_id"],
                stage_timeout_label="user_item_processing_timeout",
                timeout_seconds=2.0,
                poll_interval_seconds=0.01,
            )

        first_item = first_client.app.state.pallium_service._storage.find_source_item(source_type="decision_note", source_id=shared_source_id)
        second_item = second_client.app.state.pallium_service._storage.find_source_item(source_type="decision_note", source_id=shared_source_id)
        assert first_item is not None
        assert second_item is not None
        assert first_item.content == "Decision: first db content."
        assert second_item.content == "Decision: second db content."
        assert Path(first_db_url.removeprefix("sqlite:///")) != Path(second_db_url.removeprefix("sqlite:///"))
    finally:
        first_client.close()
        second_client.close()
