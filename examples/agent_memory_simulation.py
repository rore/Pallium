from __future__ import annotations

import json
import sys
import urllib.request


BASE_URL = "http://127.0.0.1:8000"
VISIBILITY_CONTEXT = {"kind": "limited", "id": "library-help"}
THREAD_REF = "chat:library-help:1730000000.000100"
SESSION_REF = "agent-session-1"

SAMPLE_ITEMS = [
    {
        "source_type": "chat_message",
        "source_id": "thread-001-msg-1",
        "content_type": "text/plain",
        "content": "We need to decide whether reservation ordering should use arrival time or item event time. Arrival time may miss hold updates during catalog sync delays.",
        "metadata": {"topic": "library_sync"},
        "artifact_kind": "message",
        "role": "user",
        "container_ref": "chat:library-help",
        "thread_ref": THREAD_REF,
        "session_ref": SESSION_REF,
        "actor_ref": "chat:user-123",
        "source_ref": "https://example.test/chat/thread-001-msg-1",
        "visibility_context": VISIBILITY_CONTEXT,
    },
    {
        "source_type": "tool_summary",
        "source_id": "artifact-001",
        "content_type": "text/plain",
        "content": "Investigation found that arrival-time ordering skipped hold updates during catalog sync delays because the catalog provider delivered updates late.",
        "metadata": {"topic": "library_sync"},
        "artifact_kind": "tool_use_summary",
        "role": "assistant",
        "container_ref": "chat:library-help",
        "thread_ref": THREAD_REF,
        "session_ref": SESSION_REF,
        "actor_ref": "agent:assistant",
        "source_ref": "https://example.test/chat/artifact-001",
        "visibility_context": VISIBILITY_CONTEXT,
    },
    {
        "source_type": "assistant_artifact",
        "source_id": "artifact-002",
        "content_type": "text/plain",
        "content": "Decision: use item event time for reservation ordering to avoid missed hold updates during sync delays.",
        "metadata": {"topic": "library_sync"},
        "artifact_kind": "assistant_output",
        "role": "assistant",
        "container_ref": "chat:library-help",
        "thread_ref": THREAD_REF,
        "session_ref": SESSION_REF,
        "actor_ref": "agent:assistant",
        "source_ref": "https://example.test/chat/artifact-002",
        "visibility_context": VISIBILITY_CONTEXT,
    },
    {
        "source_type": "assistant_artifact",
        "source_id": "artifact-003",
        "content_type": "text/plain",
        "content": "Partial progress: confirmed delayed catalog sync is the reason hold updates were missed. Next step: switch reservation ordering to item event time and add a regression test.",
        "metadata": {"topic": "library_sync"},
        "artifact_kind": "todo_snapshot",
        "role": "assistant",
        "container_ref": "chat:library-help",
        "thread_ref": THREAD_REF,
        "session_ref": SESSION_REF,
        "actor_ref": "agent:assistant",
        "source_ref": "https://example.test/chat/artifact-003",
        "visibility_context": VISIBILITY_CONTEXT,
    },
]


def _post(path: str, payload: dict) -> dict:
    request = urllib.request.Request(
        f"{BASE_URL}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request) as response:
        return json.loads(response.read().decode("utf-8"))


def _scoped_query_payload(text: str) -> dict:
    return {
        "text": text,
        "limit": 6,
        "thread_ref": THREAD_REF,
        "session_ref": SESSION_REF,
        "visibility_context": VISIBILITY_CONTEXT,
    }


def main() -> int:
    for item in SAMPLE_ITEMS:
        result = _post("/items", item)
        print(f"ingested {item['source_id']}: {result['memory_object_ids']}")

    decision_query = _post(
        "/query",
        _scoped_query_payload("why did we choose item event time for reservation ordering?"),
    )
    print("decision query")
    print(json.dumps(decision_query, indent=2))

    investigation_query = _post(
        "/query",
        _scoped_query_payload("what did the investigation find about missed hold updates?"),
    )
    print("investigation query")
    print(json.dumps(investigation_query, indent=2))

    resumed_work_query = _post(
        "/query",
        _scoped_query_payload("what should we do next when we resume this work?"),
    )
    print("resumed-work query")
    print(json.dumps(resumed_work_query, indent=2))

    debug_query = _post(
        "/query/debug",
        _scoped_query_payload("show evidence for the reservation ordering decision"),
    )
    print("debug query")
    print(json.dumps(debug_query, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())