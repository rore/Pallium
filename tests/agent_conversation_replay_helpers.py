from __future__ import annotations

from fastapi.testclient import TestClient

from app.config import AppConfig
from app.main import create_app
from tests.tiered_memory_stub_providers import TieredMemorySemanticProvider


def _agent_conversation_client(monkeypatch, test_db_url: str, *, auto_drain_items: bool = True) -> TestClient:
    monkeypatch.setattr(
        "app.dependencies.build_llm_provider",
        lambda config, **_: TieredMemorySemanticProvider(),
    )
    client = TestClient(
        create_app(
            AppConfig(
                storage_backend="sqlite",
                sqlite_url=test_db_url,
                default_use_case="agent_conversation_memory",
                llm_provider="openai_compatible",
                llm_model="fake-model",
                llm_base_url="http://fake-provider.local",
                llm_prompt_variant="strict_typed_memory_v4_evidence_guarded",
            )
        )
    )
    original_post = client.post

    def post_with_public_visibility(url: str, *args, **kwargs):
        payload = kwargs.get("json")
        if isinstance(payload, dict) and url in {"/items", "/query", "/query/debug"} and "container_visibility" not in payload:
            payload = dict(payload)
            payload["container_visibility"] = {"kind": "public", "id": None}
            kwargs["json"] = payload
        response = original_post(url, *args, **kwargs)
        if auto_drain_items and url == "/items" and response.status_code == 200:
            client.app.state.pallium_service.drain_processing_queue(worker_id="api-contract-test")
        return response

    client.post = post_with_public_visibility
    return client


def _drain_processing_queue(client: TestClient, *, worker_id: str = "api-contract-test") -> None:
    client.app.state.pallium_service.drain_processing_queue(worker_id=worker_id)

def _render_injected_text(payload: dict[str, object]) -> str:
    blocks = payload.get("injectable_blocks", [])
    if not isinstance(blocks, list):
        return ""
    return " ".join(str(block.get("text") or "").lower() for block in blocks if isinstance(block, dict))


def _seed_batch_digest_polluted_history(client: TestClient) -> dict[str, object]:
    container_ref = "chat:workspace:local-memory"
    container_visibility = _replay_visibility_context()
    threads = {
        "constraint": "chat:workspace:local-memory:thread-batch-constraint",
        "auth_retry_old": "chat:workspace:local-memory:thread-batch-auth-retry-old",
        "auth_retry_new": "chat:workspace:local-memory:thread-batch-auth-retry-new",
        "same_thread": "chat:workspace:local-memory:thread-batch-reminder",
    }
    sessions = {
        "constraint": "agent-session:batch-constraint",
        "auth_retry_old": "agent-session:batch-auth-retry-old",
        "auth_retry_new": "agent-session:batch-auth-retry-new",
        "same_thread": "agent-session:batch-reminder",
    }
    payloads = (
        {
            "source_type": "chat_message",
            "source_id": "batch-digest-a-msg-1",
            "content_type": "text/plain",
            "content": "Please summarize the latest batch digest work for this workspace.",
            "artifact_kind": "message",
            "role": "user",
            "container_ref": container_ref,
            "thread_ref": threads["constraint"]["constraint"],
            "occurred_at": "2026-03-11T10:00:00Z",
            "container_visibility": container_visibility,
        },
        {
            "source_type": "assistant_artifact",
            "source_id": "batch-digest-a-artifact-1",
            "content_type": "text/plain",
            "content": "Partial progress: prepared the batch digest for SLOT-103, SLOT-204, SLOT-317, and SLOT-418.",
            "artifact_kind": "tool_use_summary",
            "role": "assistant",
            "container_ref": container_ref,
            "thread_ref": threads["constraint"]["constraint"],
            "occurred_at": "2026-03-11T10:01:00Z",
            "container_visibility": container_visibility,
        },
        {
            "source_type": "chat_message",
            "source_id": "batch-digest-a-msg-2",
            "content_type": "text/plain",
            "content": "Please remember not to use control-panel sign-in, and do not open a browser sign-in flow.",
            "artifact_kind": "message",
            "role": "user",
            "container_ref": container_ref,
            "thread_ref": threads["constraint"]["constraint"],
            "occurred_at": "2026-03-11T10:01:30Z",
            "container_visibility": container_visibility,
        },
        {
            "source_type": "assistant_artifact",
            "source_id": "batch-digest-a-artifact-2",
            "content_type": "text/plain",
            "content": "Next step: refresh the local digest token and rerun the batch digest from the last confirmed segment.",
            "artifact_kind": "todo_snapshot",
            "role": "assistant",
            "container_ref": container_ref,
            "thread_ref": threads["constraint"]["constraint"],
            "occurred_at": "2026-03-11T10:02:00Z",
            "container_visibility": container_visibility,
        },
        {
            "source_type": "chat_message",
            "source_id": "batch-digest-b-msg-1",
            "content_type": "text/plain",
            "content": "Please summarize the older batch digest blocker.",
            "artifact_kind": "message",
            "role": "user",
            "container_ref": container_ref,
            "thread_ref": threads["auth_retry_old"]["auth_retry_old"],
            "occurred_at": "2026-03-11T11:00:00Z",
            "container_visibility": container_visibility,
        },
        {
            "source_type": "assistant_artifact",
            "source_id": "batch-digest-b-artifact-0",
            "content_type": "text/plain",
            "content": "Partial progress: manifest filters and digest scheduling are staged.",
            "artifact_kind": "tool_use_summary",
            "role": "assistant",
            "container_ref": container_ref,
            "thread_ref": threads["auth_retry_old"]["auth_retry_old"],
            "occurred_at": "2026-03-11T11:00:30Z",
            "container_visibility": container_visibility,
        },
        {
            "source_type": "assistant_artifact",
            "source_id": "batch-digest-b-artifact-1",
            "content_type": "text/plain",
            "content": "Blocked: the batch digest is unauthenticated for the remote mirror.",
            "artifact_kind": "tool_use_summary",
            "role": "assistant",
            "container_ref": container_ref,
            "thread_ref": threads["auth_retry_old"]["auth_retry_old"],
            "occurred_at": "2026-03-11T11:01:00Z",
            "container_visibility": container_visibility,
        },
        {
            "source_type": "assistant_artifact",
            "source_id": "batch-digest-b-artifact-2",
            "content_type": "text/plain",
            "content": "Next step: retry the batch digest after authentication is restored.",
            "artifact_kind": "todo_snapshot",
            "role": "assistant",
            "container_ref": container_ref,
            "thread_ref": threads["auth_retry_old"]["auth_retry_old"],
            "occurred_at": "2026-03-11T11:02:00Z",
            "container_visibility": container_visibility,
        },
        {
            "source_type": "chat_message",
            "source_id": "batch-digest-c-msg-1",
            "content_type": "text/plain",
            "content": "Please summarize the newer batch digest blocker.",
            "artifact_kind": "message",
            "role": "user",
            "container_ref": container_ref,
            "thread_ref": threads["auth_retry_new"]["auth_retry_new"],
            "occurred_at": "2026-03-11T12:00:00Z",
            "container_visibility": container_visibility,
        },
        {
            "source_type": "assistant_artifact",
            "source_id": "batch-digest-c-artifact-0",
            "content_type": "text/plain",
            "content": "Partial progress: built the mirrored batch digest for the staged manifests.",
            "artifact_kind": "tool_use_summary",
            "role": "assistant",
            "container_ref": container_ref,
            "thread_ref": threads["auth_retry_new"]["auth_retry_new"],
            "occurred_at": "2026-03-11T12:00:30Z",
            "container_visibility": container_visibility,
        },
        {
            "source_type": "assistant_artifact",
            "source_id": "batch-digest-c-artifact-1",
            "content_type": "text/plain",
            "content": "Blocked: the mirrored batch digest cannot proceed until remote authentication succeeds.",
            "artifact_kind": "tool_use_summary",
            "role": "assistant",
            "container_ref": container_ref,
            "thread_ref": threads["auth_retry_new"]["auth_retry_new"],
            "occurred_at": "2026-03-11T12:01:00Z",
            "container_visibility": container_visibility,
        },
        {
            "source_type": "assistant_artifact",
            "source_id": "batch-digest-c-artifact-2",
            "content_type": "text/plain",
            "content": "Next step: attempt control-panel sign-in and auxiliary-console sign-in before retrying the batch digest.",
            "artifact_kind": "todo_snapshot",
            "role": "assistant",
            "container_ref": container_ref,
            "thread_ref": threads["auth_retry_new"]["auth_retry_new"],
            "occurred_at": "2026-03-11T12:02:00Z",
            "container_visibility": container_visibility,
        },
        {
            "source_type": "chat_message",
            "source_id": "batch-digest-d-msg-1",
            "content_type": "text/plain",
            "content": "good morning",
            "artifact_kind": "message",
            "role": "user",
            "container_ref": container_ref,
            "thread_ref": threads["same_thread"]["same_thread"],
            "occurred_at": "2026-03-11T13:00:00Z",
            "container_visibility": container_visibility,
        },
        {
            "source_type": "assistant_artifact",
            "source_id": "batch-digest-d-artifact-1",
            "content_type": "text/plain",
            "content": "Good morning. I can help with the latest digest status when you are ready.",
            "artifact_kind": "assistant_output",
            "role": "assistant",
            "container_ref": container_ref,
            "thread_ref": threads["same_thread"]["same_thread"],
            "occurred_at": "2026-03-11T13:00:10Z",
            "container_visibility": container_visibility,
        },
        {
            "source_type": "chat_message",
            "source_id": "batch-digest-d-msg-2",
            "content_type": "text/plain",
            "content": "can you remind me what we had latest about batch digests?",
            "artifact_kind": "message",
            "role": "user",
            "container_ref": container_ref,
            "thread_ref": threads["same_thread"]["same_thread"],
            "occurred_at": "2026-03-11T13:00:20Z",
            "container_visibility": container_visibility,
        },
    )
    for payload in payloads:
        response = client.post("/items", json=payload)
        assert response.status_code == 200

    thread_memory_ids = _collect_thread_memory_ids(client, container_ref=container_ref, threads=threads)
    constraint_rendered = _render_thread_memory(client, container_ref=container_ref, thread_ref=threads["constraint"])
    auth_retry_old_rendered = _render_thread_memory(client, container_ref=container_ref, thread_ref=threads["auth_retry_old"])
    auth_retry_new_rendered = _render_thread_memory(client, container_ref=container_ref, thread_ref=threads["auth_retry_new"])
    assert any("batch digest" in rendered for rendered in constraint_rendered)
    assert any("browser sign-in" in rendered or "control-panel sign-in" in rendered for rendered in constraint_rendered)
    assert any("authentication is restored" in rendered for rendered in auth_retry_old_rendered)
    assert any("control-panel sign-in" in rendered or "auxiliary-console sign-in" in rendered for rendered in auth_retry_new_rendered)

    return {
        "container_ref": container_ref,
        "container_visibility": container_visibility,
        "threads": threads,
        "sessions": sessions,
        "thread_memory_ids": thread_memory_ids,
    }


def _seed_short_noun_isolation_history(client: TestClient) -> dict[str, object]:
    scenario = _seed_batch_digest_polluted_history(client)
    container_ref = scenario["container_ref"]
    container_visibility = scenario["container_visibility"]
    threads = dict(scenario["threads"])
    sessions = dict(scenario["sessions"])
    threads.update(
        {
            "same_thread_x": "chat:workspace:local-memory:thread-batch-same-thread-x",
            "same_thread_y": "chat:workspace:local-memory:thread-batch-same-thread-y",
            "reserve": "chat:workspace:local-memory:thread-reserve-snapshot",
            "noise": "chat:workspace:local-memory:thread-noise",
        }
    )
    sessions.update(
        {
            "same_thread_x": "agent-session:batch-same-thread-x",
            "same_thread_y": "agent-session:batch-same-thread-y",
            "reserve": "agent-session:reserve-snapshot",
            "noise": "agent-session:generic-noise",
        }
    )

    payloads = (
        {
            "source_type": "assistant_artifact",
            "source_id": "reserve-noise-capability",
            "content_type": "text/plain",
            "content": "Well, I can help with both batch digests and reserve summaries.",
            "artifact_kind": "assistant_output",
            "role": "assistant",
            "container_ref": container_ref,
            "thread_ref": threads["noise"]["noise"],
            "occurred_at": "2026-03-11T08:55:00Z",
            "container_visibility": container_visibility,
        },
        {
            "source_type": "assistant_artifact",
            "source_id": "reserve-noise-heartbeat",
            "content_type": "text/plain",
            "content": "Heartbeat: still monitoring the current workspace.",
            "artifact_kind": "assistant_output",
            "role": "assistant",
            "container_ref": container_ref,
            "thread_ref": threads["noise"]["noise"],
            "occurred_at": "2026-03-11T08:56:00Z",
            "container_visibility": container_visibility,
        },
        {
            "source_type": "chat_message",
            "source_id": "reserve-thread-msg-1",
            "content_type": "text/plain",
            "content": "Please summarize the latest reserve snapshot for the local reserve review.",
            "artifact_kind": "message",
            "role": "user",
            "container_ref": container_ref,
            "thread_ref": threads["reserve"]["reserve"],
            "occurred_at": "2026-03-11T12:30:00Z",
            "container_visibility": container_visibility,
        },
        {
            "source_type": "assistant_artifact",
            "source_id": "reserve-thread-artifact-1",
            "content_type": "text/plain",
            "content": "Partial progress: the reserve snapshot is reconciled for POUCH-102 and POUCH-208.",
            "artifact_kind": "tool_use_summary",
            "role": "assistant",
            "container_ref": container_ref,
            "thread_ref": threads["reserve"]["reserve"],
            "occurred_at": "2026-03-11T12:31:00Z",
            "container_visibility": container_visibility,
        },
        {
            "source_type": "assistant_artifact",
            "source_id": "reserve-thread-artifact-2",
            "content_type": "text/plain",
            "content": "Next step: publish the reserve note after confirming the local snapshot.",
            "artifact_kind": "todo_snapshot",
            "role": "assistant",
            "container_ref": container_ref,
            "thread_ref": threads["reserve"]["reserve"],
            "occurred_at": "2026-03-11T12:35:00Z",
            "container_visibility": container_visibility,
        },
        {
            "source_type": "chat_message",
            "source_id": "same-thread-x-msg-1",
            "content_type": "text/plain",
            "content": "good afternnon sir",
            "artifact_kind": "message",
            "role": "user",
            "container_ref": container_ref,
            "thread_ref": threads["same_thread_x"]["same_thread_x"],
            "occurred_at": "2026-03-11T13:00:00Z",
            "container_visibility": container_visibility,
        },
        {
            "source_type": "assistant_artifact",
            "source_id": "same-thread-x-artifact-1",
            "content_type": "text/plain",
            "content": "Good afternoon. I can help with the latest digest status when you are ready.",
            "artifact_kind": "assistant_output",
            "role": "assistant",
            "container_ref": container_ref,
            "thread_ref": threads["same_thread_x"]["same_thread_x"],
            "occurred_at": "2026-03-11T13:00:10Z",
            "container_visibility": container_visibility,
        },
        {
            "source_type": "chat_message",
            "source_id": "same-thread-y-msg-1",
            "content_type": "text/plain",
            "content": "hello again",
            "artifact_kind": "message",
            "role": "user",
            "container_ref": container_ref,
            "thread_ref": threads["same_thread_y"]["same_thread_y"],
            "occurred_at": "2026-03-11T13:05:00Z",
            "container_visibility": container_visibility,
        },
    )
    for payload in payloads:
        response = client.post("/items", json=payload)
        assert response.status_code == 200

    thread_memory_ids = _collect_thread_memory_ids(client, container_ref=container_ref, threads=threads)
    reserve_rendered = _render_thread_memory(client, container_ref=container_ref, thread_ref=threads["reserve"])
    assert any("reserve snapshot" in rendered for rendered in reserve_rendered)

    scenario["threads"] = threads
    scenario["sessions"] = sessions
    scenario["thread_memory_ids"] = thread_memory_ids
    return scenario


def _replay_visibility_context() -> str:
    return "limited"


def _collect_thread_memory_ids(
    client: TestClient,
    *,
    container_ref: str,
    threads: dict[str, str],
) -> dict[str, dict[str, list[str]]]:
    storage = client.app.state.pallium_service._storage
    collected: dict[str, dict[str, list[str]]] = {}
    for name, thread_ref in threads.items():
        memory_ids = {"task_checkpoint": [], "thread_summary": [], "discussion_summary": []}
        all_ids: list[str] = []
        for source_item in storage.list_source_items_for_thread(container_ref, thread_ref):
            for memory in storage.list_memory_objects_for_source_item(source_item.id):
                if memory.lifecycle != "active":
                    continue
                if memory.type in memory_ids:
                    memory_ids[memory.type].append(memory.id)
                    all_ids.append(memory.id)
        memory_ids["all"] = all_ids
        collected[name] = memory_ids
    return collected


def _render_thread_memory(client: TestClient, *, container_ref: str, thread_ref: str) -> list[str]:
    storage = client.app.state.pallium_service._storage
    rendered: list[str] = []
    for source_item in storage.list_source_items_for_thread(container_ref, thread_ref):
        for memory in storage.list_memory_objects_for_source_item(source_item.id):
            if memory.lifecycle != "active" or memory.type not in {"task_checkpoint", "thread_summary", "discussion_summary"}:
                continue
            payload = memory.payload or {}
            rendered.append(
                " ".join(
                    [
                        str(payload.get("summary") or ""),
                        str(payload.get("current_state") or ""),
                        str(payload.get("blocker_state") or ""),
                        str(payload.get("next_step") or ""),
                        *[str(value or "") for value in payload.get("key_findings", []) if isinstance(value, str)],
                        *[str(value or "") for value in payload.get("evidence", []) if isinstance(value, str)],
                    ]
                ).lower()
            )
    return rendered
