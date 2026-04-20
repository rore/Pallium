from __future__ import annotations

import json
import threading
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


_MAX_SKIP_REASON_KEYS = 50
_SNAPSHOT_SKIP_REASON_LIMIT = 20


class QueryStats:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._total_queries = 0
        self._total_injections = 0
        self._total_skips = 0
        self._total_blocks_injected = 0
        self._total_flags = 0
        self._total_suppressions = 0
        self._skip_reasons: dict[str, int] = {}
        self._last_query_at: str | None = None
        self._stats_since = datetime.now(timezone.utc).isoformat()

    def record_query(self, result: object) -> None:
        try:
            should_inject = getattr(result, "should_inject", False)
            decision_reason = getattr(result, "decision_reason", "unknown")
            injectable_blocks = getattr(result, "injectable_blocks", [])
            with self._lock:
                self._total_queries += 1
                self._last_query_at = datetime.now(timezone.utc).isoformat()
                if should_inject and len(injectable_blocks) > 0:
                    self._total_injections += 1
                    self._total_blocks_injected += len(injectable_blocks)
                else:
                    self._total_skips += 1
                    reason = str(decision_reason) if decision_reason else "unknown"
                    if reason in self._skip_reasons:
                        self._skip_reasons[reason] += 1
                    elif len(self._skip_reasons) < _MAX_SKIP_REASON_KEYS:
                        self._skip_reasons[reason] = 1
                    else:
                        self._skip_reasons["_other"] = self._skip_reasons.get("_other", 0) + 1
        except Exception:
            pass

    def record_flag(self, suppressed: bool) -> None:
        try:
            with self._lock:
                self._total_flags += 1
                if suppressed:
                    self._total_suppressions += 1
        except Exception:
            pass

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            sorted_reasons = dict(
                sorted(self._skip_reasons.items(), key=lambda kv: kv[1], reverse=True)[:_SNAPSHOT_SKIP_REASON_LIMIT]
            )
            return {
                "total_queries": self._total_queries,
                "total_injections": self._total_injections,
                "total_skips": self._total_skips,
                "total_blocks_injected": self._total_blocks_injected,
                "total_flags": self._total_flags,
                "total_suppressions": self._total_suppressions,
                "skip_reasons": sorted_reasons,
                "last_query_at": self._last_query_at,
                "stats_since": self._stats_since,
            }


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, set):
        return sorted(value)
    raise TypeError(f"Object of type {value.__class__.__name__} is not JSON serializable")
