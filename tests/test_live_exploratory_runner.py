from __future__ import annotations

import json
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import AppConfig
from storage.vector_index import VectorIndexConfig
from tests.config_helpers import _vector_index_path_for_sqlite
from app.live_exploratory_runner import (
    BackgroundProcessor,
    StageTimeoutError,
    _aggregate_drift_metrics,
    _build_shadow_diff,
    _extract_drift_signals,
    build_summary,
    wait_for_item_processing,
    wait_for_turn_event_processing,
)
from app.main import create_app
from core.contracts import ItemProcessingResult
from tools.replay_promotion.promote_to_replay import (
    _build_scenario_from_result,
    _validate_scenario,
    main as promote_main,
)

import pytest

pytestmark = pytest.mark.slow


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
    config = AppConfig(storage_backend="sqlite", sqlite_url=test_db_url, default_use_case="demo_agent_memory", vector_index=VectorIndexConfig(index_path=_vector_index_path_for_sqlite(test_db_url)))
    client = TestClient(create_app(config))
    try:
        user_response = client.post("/items", json=[_item_payload("targeted-user", "Decision: user stage.")])
        assistant_response = client.post("/items", json=[_item_payload("targeted-assistant", "Decision: assistant stage.")])
        assert user_response.status_code == 200
        assert assistant_response.status_code == 200
        event = {
            "user_item": {"response": user_response.json()[0]},
            "assistant": {"response": assistant_response.json()[0]},
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
    config = AppConfig(storage_backend="sqlite", sqlite_url=test_db_url, default_use_case="demo_agent_memory", vector_index=VectorIndexConfig(index_path=_vector_index_path_for_sqlite(test_db_url)))
    client = TestClient(create_app(config))
    try:
        response = client.post("/items", json=[_item_payload("background-processor-1", "Decision: process this item.")])
        assert response.status_code == 200
        source_item_id = response.json()[0]["source_item_id"]
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

    first_config = AppConfig(storage_backend="sqlite", sqlite_url=first_db_url, default_use_case="demo_agent_memory", vector_index=VectorIndexConfig(index_path=_vector_index_path_for_sqlite(first_db_url)))
    second_config = AppConfig(storage_backend="sqlite", sqlite_url=second_db_url, default_use_case="demo_agent_memory", vector_index=VectorIndexConfig(index_path=_vector_index_path_for_sqlite(second_db_url)))

    first_client = TestClient(create_app(first_config))
    second_client = TestClient(create_app(second_config))
    try:
        first_response = first_client.post("/items", json=[_item_payload(shared_source_id, "Decision: first db content.")])
        second_response = second_client.post("/items", json=[_item_payload(shared_source_id, "Decision: second db content.")])
        assert first_response.status_code == 200
        assert second_response.status_code == 200

        with BackgroundProcessor(config=first_config, worker_id="isolation-first", poll_interval_seconds=0.01):
            wait_for_item_processing(
                first_client.app.state.pallium_service.get_item_processing,
                first_response.json()[0]["source_item_id"],
                stage_timeout_label="user_item_processing_timeout",
                timeout_seconds=2.0,
                poll_interval_seconds=0.01,
            )
        with BackgroundProcessor(config=second_config, worker_id="isolation-second", poll_interval_seconds=0.01):
            wait_for_item_processing(
                second_client.app.state.pallium_service.get_item_processing,
                second_response.json()[0]["source_item_id"],
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


# --- Drift metrics tests ---

def _make_result(
    *,
    has_trace: bool = True,
    should_inject: bool | None = True,
    selected_layer: str | None = "decision",
    fallback_applied: bool = False,
    sharp_miss_stages: list[str] | None = None,
    thread_rebuild_seconds: float | None = None,
    scenario_id: str = "test-s",
    classification: str = "pass",
) -> dict:
    routing: dict = {}
    if has_trace:
        routing = {
            "selected_layer": selected_layer,
            "fallback": {"applied": fallback_applied},
            "sharp_candidate_diagnostics": [
                {"loss_stage": stage} for stage in (sharp_miss_stages or [])
            ],
        }
    return {
        "scenario_id": scenario_id,
        "classification": classification,
        "followup_query_response": {"trace": {"routing": routing}} if has_trace else {},
        "followup_evaluation": {
            "should_inject": should_inject,
            "selected_layer": selected_layer,
            "decision_reason": "carry_forward_available",
            "must_include_hits": [],
            "must_not_include_hits": [],
        },
        "timings": {"thread_rebuild_wait_seconds": thread_rebuild_seconds},
    }


def test_extract_drift_signals_with_full_trace() -> None:
    result = _make_result(
        has_trace=True,
        should_inject=True,
        selected_layer="decision",
        fallback_applied=False,
        sharp_miss_stages=["routing"],
        thread_rebuild_seconds=1.5,
    )
    signals = _extract_drift_signals(result)
    assert signals["has_trace"] is True
    assert signals["should_inject"] is True
    assert signals["selected_layer"] == "decision"
    assert signals["fallback_applied"] is False
    assert signals["has_sharp_miss"] is True
    assert signals["sharp_miss_stages"] == ["routing"]
    assert signals["has_thread_rebuild"] is True


def test_extract_drift_signals_with_missing_trace() -> None:
    signals = _extract_drift_signals({})
    assert signals["has_trace"] is False
    assert signals["should_inject"] is None
    assert signals["selected_layer"] is None
    assert signals["fallback_applied"] is False
    assert signals["has_sharp_miss"] is False
    assert signals["sharp_miss_stages"] == []
    assert signals["has_thread_rebuild"] is False


def test_aggregate_drift_metrics_correct_aggregation() -> None:
    results = [
        _make_result(should_inject=True, selected_layer="decision", sharp_miss_stages=["retrieval"], thread_rebuild_seconds=1.0),
        _make_result(should_inject=False, selected_layer=None, fallback_applied=True, thread_rebuild_seconds=0.0),
        _make_result(should_inject=True, selected_layer="thread_summary"),
    ]
    metrics = _aggregate_drift_metrics(results)
    assert metrics["scenarios_with_trace"] == 3
    assert metrics["injection_rate"] == round(2 / 3, 4)
    assert metrics["sharp_miss_rate"] == round(1 / 3, 4)
    assert metrics["sharp_miss_by_loss_stage"]["retrieval"] == 1
    assert metrics["fallback_rate"] == round(1 / 3, 4)
    assert metrics["rebuild_rate"] == round(1 / 3, 4)
    # injected_total = 2; generic_summary_wins = 1 (thread_summary)
    assert metrics["generic_summary_win_rate"] == round(1 / 2, 4)


def test_build_summary_includes_drift_metrics_key(tmp_path: Path) -> None:
    results = [_make_result()]
    summary = build_summary(tmp_path, results, [])
    assert "drift_metrics" in summary
    assert "scenarios_with_trace" in summary["drift_metrics"]


def test_build_summary_includes_shadow_summary_when_shadow_present(tmp_path: Path) -> None:
    shadow_diff = {
        "should_inject_primary": True, "should_inject_shadow": False, "should_inject_changed": True,
        "decision_reason_primary": "a", "decision_reason_shadow": "b", "decision_reason_changed": True,
        "selected_layer_primary": "decision", "selected_layer_shadow": None, "selected_layer_changed": True,
        "fallback_applied_primary": False, "fallback_applied_shadow": False, "fallback_changed": False,
        "primary_eval_pass": True, "shadow_eval_pass": False,
        "shadow_improves": False, "shadow_regresses": True, "shadow_neutral": False,
    }
    result = _make_result()
    result["shadow_comparison"] = shadow_diff
    summary = build_summary(tmp_path, [result], [])
    assert summary["shadow_summary"] is not None
    assert summary["shadow_summary"]["shadow_regresses_count"] == 1
    assert summary["shadow_summary"]["injection_flip_count"] == 1


def test_build_summary_shadow_summary_none_when_no_shadow(tmp_path: Path) -> None:
    result = _make_result()
    result["shadow_comparison"] = None
    summary = build_summary(tmp_path, [result], [])
    assert summary["shadow_summary"] is None


# --- Shadow diff tests ---

def _make_eval(*, should_inject: bool, decision_reason: str, selected_layer: str, pass_: bool) -> dict:
    return {
        "should_inject": should_inject,
        "decision_reason": decision_reason,
        "selected_layer": selected_layer,
        "should_inject_match": pass_,
        "decision_reason_match": pass_,
        "selected_layer_match": pass_,
        "must_include_ok": pass_,
        "must_not_include_ok": pass_,
    }


def test_build_shadow_diff_shadow_improves() -> None:
    primary_eval = _make_eval(should_inject=False, decision_reason="none", selected_layer="none", pass_=False)
    shadow_eval = _make_eval(should_inject=True, decision_reason="carry_forward_available", selected_layer="decision", pass_=True)
    diff = _build_shadow_diff({}, {}, primary_eval, shadow_eval)
    assert diff["shadow_improves"] is True
    assert diff["shadow_regresses"] is False
    assert diff["shadow_neutral"] is False
    assert diff["should_inject_changed"] is True


def test_build_shadow_diff_shadow_regresses() -> None:
    primary_eval = _make_eval(should_inject=True, decision_reason="carry_forward_available", selected_layer="decision", pass_=True)
    shadow_eval = _make_eval(should_inject=False, decision_reason="none", selected_layer="none", pass_=False)
    diff = _build_shadow_diff({}, {}, primary_eval, shadow_eval)
    assert diff["shadow_improves"] is False
    assert diff["shadow_regresses"] is True
    assert diff["shadow_neutral"] is False


def test_build_shadow_diff_shadow_neutral() -> None:
    primary_eval = _make_eval(should_inject=True, decision_reason="carry_forward_available", selected_layer="decision", pass_=True)
    shadow_eval = _make_eval(should_inject=True, decision_reason="carry_forward_available", selected_layer="decision", pass_=True)
    diff = _build_shadow_diff({}, {}, primary_eval, shadow_eval)
    assert diff["shadow_improves"] is False
    assert diff["shadow_regresses"] is False
    assert diff["shadow_neutral"] is True
    assert diff["should_inject_changed"] is False


# --- create_app routing_overrides dependency path ---

def test_create_app_with_routing_overrides_reaches_plugin(test_db_url: str) -> None:
    from semantic.agent_conversation_memory import AgentConversationMemoryPlugin
    config = AppConfig(storage_backend="sqlite", sqlite_url=test_db_url, default_use_case="demo_agent_memory", vector_index=VectorIndexConfig(index_path=_vector_index_path_for_sqlite(test_db_url)))
    overrides = {"fallback_margin": 999}
    app = create_app(config, routing_overrides=overrides)
    service = app.state.pallium_service
    plugins = service._semantic_plugins
    acm_plugin = plugins.get("agent_conversation_memory")
    if acm_plugin is not None:
        assert isinstance(acm_plugin, AgentConversationMemoryPlugin)
        assert acm_plugin._routing_overrides == overrides


# --- Replay promotion tests ---

def _make_live_result(scenario_id: str = "test-scenario") -> dict:
    return {
        "scenario_id": scenario_id,
        "description": "A test scenario",
        "classification": "pass",
        "followup_evaluation": {
            "should_inject": True,
            "selected_layer": "decision",
            "decision_reason": "carry_forward_available",
        },
        "followup_query_request": {
            "text": "What was the decision?",
            "limit": 6,
            "container_ref": "chat:test",
        },
        "followup_message": "What was the decision?",
        "ingested_items": [
            {"source_type": "chat_message", "source_id": "msg-1", "content": "Prior content.", "content_type": "text/plain", "artifact_kind": "message", "role": "user"},
        ],
    }


def test_build_scenario_from_result_has_required_fields() -> None:
    result = _make_live_result()
    scenario = _build_scenario_from_result(result, expected_value=None)
    missing = _validate_scenario(scenario)
    assert missing == [], f"missing fields: {missing}"
    assert scenario["scenario_kind"] == "replay_capture"
    assert scenario["scenario_id"].startswith("replay_test-scenario_")
    assert scenario["description"].startswith("[REPLAY]")
    assert scenario["expected_value"] == "__FILL_IN__"
    assert len(scenario["prior_events"]) == 1
    assert "dataset_tier" not in scenario
    assert "_replay_metadata" not in scenario


def test_build_scenario_from_result_expected_value_true() -> None:
    result = _make_live_result()
    scenario = _build_scenario_from_result(result, expected_value="true")
    assert scenario["expected_value"] is True


def test_promote_main_creates_output_and_sidecar(tmp_path: Path) -> None:
    result = _make_live_result("promo-test")
    source_file = tmp_path / "promo-test.json"
    source_file.write_text(json.dumps(result), encoding="utf-8")
    output_file = tmp_path / "scenarios_replay.json"

    exit_code = promote_main(["--source", str(source_file), "--output", str(output_file)])
    assert exit_code == 0

    scenarios = json.loads(output_file.read_text())
    assert isinstance(scenarios, list)
    assert len(scenarios) == 1
    scenario = scenarios[0]
    missing = _validate_scenario(scenario)
    assert missing == []
    assert "dataset_tier" not in scenario
    assert "_replay_metadata" not in scenario

    sidecar_files = list(tmp_path.glob("*_source.json"))
    assert len(sidecar_files) == 1
    sidecar = json.loads(sidecar_files[0].read_text())
    assert sidecar["source_scenario_id"] == "promo-test"
    assert sidecar["review_status"] == "pending"


def test_promote_main_appends_to_existing_output(tmp_path: Path) -> None:
    existing = [{"scenario_id": "existing-1", "scenario_kind": "cross_thread_value", "description": "old", "prior_events": [], "current_query": {"text": "q", "limit": 6}, "expected_value": True, "expected_memory_types": []}]
    output_file = tmp_path / "scenarios_replay.json"
    output_file.write_text(json.dumps(existing), encoding="utf-8")

    source_file = tmp_path / "new.json"
    source_file.write_text(json.dumps(_make_live_result("new-scenario")), encoding="utf-8")

    promote_main(["--source", str(source_file), "--output", str(output_file)])

    scenarios = json.loads(output_file.read_text())
    assert len(scenarios) == 2
    ids = [s["scenario_id"] for s in scenarios]
    assert "existing-1" in ids
