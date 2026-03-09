from __future__ import annotations

import json
import sys
import urllib.request


BASE_URL = "http://127.0.0.1:8000"

SAMPLE_ITEMS = [
    {
        "source_type": "chat_thread",
        "source_id": "thread-001",
        "content_type": "text/plain",
        "content": "We need to decide whether export watermarking should use ingestion time or event time. Ingestion time may skip records when lag spikes.",
        "metadata": {"topic": "watermarking"},
    },
    {
        "source_type": "investigation_summary",
        "source_id": "investigation-001",
        "content_type": "text/plain",
        "content": "Skipped records were observed when EventHub lag increased. The issue correlates with using ingestion-time progress tracking.",
        "metadata": {"topic": "watermarking"},
    },
    {
        "source_type": "decision_note",
        "source_id": "decision-001",
        "content_type": "text/plain",
        "content": "Decision: use event timestamp watermarking for exports to avoid skipped records during lag.",
        "metadata": {"topic": "watermarking"},
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

    query_result = _post(
        "/query",
        {"text": "why did we choose event timestamp watermarking?", "limit": 6},
    )
    print(json.dumps(query_result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
