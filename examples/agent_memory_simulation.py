from __future__ import annotations

import json
import sys
import urllib.request


BASE_URL = "http://127.0.0.1:8000"

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
        "thread_ref": "chat:library-help:1730000000.000100",
        "session_ref": "agent-session-1",
        "actor_ref": "chat:user-123",
        "source_ref": "https://example.test/chat/thread-001-msg-1",
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
        "thread_ref": "chat:library-help:1730000000.000100",
        "session_ref": "agent-session-1",
        "actor_ref": "agent:assistant",
        "source_ref": "https://example.test/chat/artifact-001",
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
        "thread_ref": "chat:library-help:1730000000.000100",
        "session_ref": "agent-session-1",
        "actor_ref": "agent:assistant",
        "source_ref": "https://example.test/chat/artifact-002",
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


def main() -> int:
    for item in SAMPLE_ITEMS:
        result = _post("/items", item)
        print(f"ingested {item['source_id']}: {result['memory_object_ids']}")

    decision_query = _post(
        "/query",
        {
            "text": "why did we choose item event time for reservation ordering?",
            "limit": 6,
            "thread_ref": "chat:library-help:1730000000.000100",
            "session_ref": "agent-session-1",
        },
    )
    print("decision query")
    print(json.dumps(decision_query, indent=2))

    investigation_query = _post(
        "/query",
        {
            "text": "what did the investigation find about missed hold updates?",
            "limit": 6,
            "thread_ref": "chat:library-help:1730000000.000100",
            "session_ref": "agent-session-1",
        },
    )
    print("investigation query")
    print(json.dumps(investigation_query, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
