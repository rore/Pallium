from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any


OBSERVABILITY_METADATA_KEY = "observability_debug"


class IntegrationDebugLogger:
    def __init__(self, *, enabled: bool) -> None:
        self.enabled = enabled

    def emit(self, event_type: str, **fields: Any) -> None:
        if not self.enabled:
            return
        event = {
            "event_type": event_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **fields,
        }
        print(json.dumps(event, default=_json_default, sort_keys=True), flush=True)


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, set):
        return sorted(value)
    raise TypeError(f"Object of type {value.__class__.__name__} is not JSON serializable")
