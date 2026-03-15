from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import AppConfig
from app.main import create_app
from evals.integration_readiness_scenario import run_integration_readiness_scenario
from tests.test_work_resumption_benchmark import StubWorkResumptionAnswerProvider
from tests.stub_providers import TieredMemorySemanticProvider

SCENARIOS = Path("evals/integration_readiness/scenarios.json")


def _benchmark_config() -> AppConfig:
    return AppConfig(
        default_use_case="agent_conversation_memory",
        llm_provider="openai_compatible",
        llm_model="fake-answer-model",
        llm_base_url="http://fake-provider.local",
        llm_prompt_variant="strict_typed_memory_v4_evidence_guarded",
    )


def test_integration_readiness_scenario_builds_green_milestone_gate(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("app.dependencies.build_llm_provider", lambda config, **_: TieredMemorySemanticProvider())

    run_dir = run_integration_readiness_scenario(
        scenario_file=SCENARIOS,
        output_root=tmp_path / "output",
        config=_benchmark_config(),
        run_name="integration-readiness",
        answer_provider=StubWorkResumptionAnswerProvider(),
    )

    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    report = (run_dir / "report.md").read_text(encoding="utf-8")

    assert summary["scenario_count"] == 3
    assert summary["component_policy_successes"] == 3
    assert summary["gates"]["positive_value_passed"] is True
    assert summary["gates"]["no_value_control_passed"] is True
    assert summary["gates"]["scope_guard_passed"] is True
    assert summary["gates"]["integration_readiness_passed"] is True
    assert summary["roles"]["positive_value"]["top_layer"] == "task_checkpoint"
    assert summary["roles"]["no_value_control"]["winner"] != "memory_backed"
    assert "privacy_leak_failure" not in summary["roles"]["scope_guard"]["failure_families"]
    assert "## Manual Run" in report
    assert "`integration_readiness_passed`: PASS" in report



def test_downstream_query_returns_sharp_integration_ready_blocks(monkeypatch, test_db_url: str) -> None:
    monkeypatch.setattr("app.dependencies.build_llm_provider", lambda config, **_: TieredMemorySemanticProvider())
    client = TestClient(
        create_app(
            AppConfig(
                storage_backend="sqlite",
                sqlite_url=test_db_url,
                default_use_case="agent_conversation_memory",
                llm_provider="openai_compatible",
                llm_model="fake-answer-model",
                llm_base_url="http://fake-provider.local",
                llm_prompt_variant="strict_typed_memory_v4_evidence_guarded",
            )
        )
    )
    original_post = client.post

    def post_with_public_visibility(url: str, *args, **kwargs):
        payload = kwargs.get("json")
        if isinstance(payload, dict) and url in {"/items", "/query", "/query/debug"} and "visibility_context" not in payload:
            payload = dict(payload)
            payload["visibility_context"] = {"kind": "public", "id": None}
            kwargs["json"] = payload
        response = original_post(url, *args, **kwargs)
        if url == "/items" and response.status_code == 200:
            client.app.state.pallium_service.drain_processing_queue(worker_id="integration-ready-test")
        return response

    client.post = post_with_public_visibility

    for payload in (
        {
            "source_type": "chat_message",
            "source_id": "integration-msg-1",
            "content_type": "text/plain",
            "content": "Which repo changed more and why?",
            "artifact_kind": "message",
            "role": "user",
            "container_ref": "slack:CLOCAL001",
            "thread_ref": "slack:CLOCAL001:thread-integration",
            "session_ref": "pelican:integration",
        },
        {
            "source_type": "assistant_artifact",
            "source_id": "integration-artifact-1",
            "content_type": "text/plain",
            "content": "Understood. No browser auth, no Jira or Slack auth. I will use the local repos only.",
            "artifact_kind": "assistant_output",
            "role": "assistant",
            "container_ref": "slack:CLOCAL001",
            "thread_ref": "slack:CLOCAL001:thread-integration",
            "session_ref": "pelican:integration",
        },
        {
            "source_type": "assistant_artifact",
            "source_id": "integration-artifact-2",
            "content_type": "text/plain",
            "content": "Investigation found that transaction-transformer changed more than ledger-query because it touched more tickets, files, and transaction flows.",
            "artifact_kind": "assistant_output",
            "role": "assistant",
            "container_ref": "slack:CLOCAL001",
            "thread_ref": "slack:CLOCAL001:thread-integration",
            "session_ref": "pelican:integration",
        },
        {
            "source_type": "assistant_artifact",
            "source_id": "integration-artifact-3",
            "content_type": "text/plain",
            "content": "Task complete. No Slack message needed. Nothing new to report.",
            "artifact_kind": "assistant_output",
            "role": "assistant",
            "container_ref": "slack:CLOCAL001",
            "thread_ref": "slack:CLOCAL001:thread-integration",
            "session_ref": "pelican:integration",
        },
    ):
        response = client.post("/items", json=payload)
        assert response.status_code == 200

    response = client.post(
        "/query",
        json={
            "text": "which repo changed more and why?",
            "limit": 6,
            "container_ref": "slack:CLOCAL001",
            "runtime_context": {
                "turn_kind": "resumed_session",
                "session_has_sufficient_local_context": False,
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["should_inject"] is True
    assert payload["decision_reason"] == "carry_forward_available"
    assert payload["injectable_blocks"]
    assert payload["injectable_blocks"][0]["block_type"] == "memory"
    assert payload["injectable_blocks"][0]["memory_type"] == "investigation_outcome"
    assert any(block["memory_type"] == "investigation_outcome" for block in payload["injectable_blocks"])
    assert "transaction-transformer" in json.dumps(payload["injectable_blocks"]).lower()
    rendered_blocks = json.dumps(payload["injectable_blocks"]).lower()
    assert "task complete" not in rendered_blocks
    assert "nothing new to report" not in rendered_blocks
