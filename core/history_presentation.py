"""Shared bounded presentation for source-only History search results."""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Callable

from retrieval.common import build_excerpt

MCP_SEARCH_MAX_CHARS = 2000
MCP_SEARCH_EMPTY_MAX_CHARS = 300


def _json_text(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def _history_fields(item: dict) -> dict:
    fields = {
        key: item[key]
        for key in ("recorded_at", "recorded_at_source")
        if item.get(key) is not None
    }
    updates = [
        {
            key: update[key]
            for key in (
                "memory_type",
                "status",
                "replacement_status",
                "current_memory_object_id",
                "current_text",
                "current_text_truncated",
                "current_recorded_at",
            )
            if update.get(key) is not None
        }
        for update in item.get("historical_updates") or []
    ]
    if updates:
        fields["historical_updates"] = updates
    if omitted := item.get("historical_updates_omitted") or 0:
        fields["historical_updates_omitted"] = omitted
    return fields


def _trim_update_details(payload: dict, items: list[dict], budget: int) -> None:
    while len(_json_text(payload)) > budget:
        texts = [
            update
            for item in items
            for update in item.get("historical_updates") or []
            if update.get("current_text")
        ]
        if not texts:
            break
        longest = max(texts, key=lambda update: len(update["current_text"]))
        excess = len(_json_text(payload)) - budget
        longest["current_text_truncated"] = True
        longest["current_text"] = longest["current_text"][
            : max(0, len(longest["current_text"]) - excess - 1)
        ]
        if not longest["current_text"]:
            longest.pop("current_text", None)
    while len(_json_text(payload)) > budget:
        removable = [
            (item, index, update)
            for item in items
            if len(item.get("historical_updates") or []) > 1
            for index, update in enumerate(item["historical_updates"])
        ]
        if not removable:
            break
        item, index, _ = min(
            removable,
            key=lambda candidate: candidate[2].get("replacement_status") == "current",
        )
        item["historical_updates"].pop(index)
        item["historical_updates_omitted"] = item.get("historical_updates_omitted", 0) + 1


def _history_page_request_error(limit: object, result_offset: object, result_revision: object) -> dict | None:
    if type(limit) is not int or not 1 <= limit <= 50:
        return {
            "error": "limit must be an integer between 1 and 50",
            "error_kind": "invalid_history_limit",
            "retryable": False,
        }
    if type(result_offset) is not int or result_offset < 0:
        return {
            "error": "result_offset must be a non-negative integer",
            "error_kind": "invalid_result_offset",
            "retryable": False,
        }
    if result_revision is not None and (not isinstance(result_revision, str) or len(result_revision) != 64 or any(character not in "0123456789abcdef" for character in result_revision)):
        return {
            "error": "result_revision must be a 64-character lowercase hex digest",
            "error_kind": "invalid_result_revision",
            "retryable": False,
        }
    if result_offset and result_revision is None:
        return {
            "error": "result_revision is required for a nonzero result_offset",
            "error_kind": "result_revision_required",
            "retryable": True,
            "action": "restart at result_offset 0 to obtain the current result_revision",
        }
    return None


def _fit_history_hit(
    hit: dict, envelope: Callable[[list[dict]], dict], budget: int
) -> dict | None:
    fitted = copy.deepcopy(hit)
    def fits() -> bool:
        return len(_json_text(envelope([fitted]))) <= budget
    if fits():
        return fitted
    for key in ("match_channel", "session_group", "work_refs", "role", "occurred_at"):
        fitted.pop(key, None)
        if fits():
            return fitted
    _trim_update_details(envelope([fitted]), [fitted], budget)
    if fits():
        return fitted
    updates = fitted.get("historical_updates") or []
    if updates:
        minimal_updates = [
            {
                key: update[key]
                for key in ("status", "replacement_status")
                if update.get(key) is not None
            }
            for update in updates
        ]
        minimal_updates = [update for update in minimal_updates if update]
        if minimal_updates:
            fitted["historical_updates"] = minimal_updates
            if not fits() and len(minimal_updates) > 1:
                preferred = next(
                    (
                        update
                        for update in minimal_updates
                        if update.get("replacement_status") == "current"
                    ),
                    minimal_updates[0],
                )
                fitted["historical_updates"] = [preferred]
                fitted["historical_updates_omitted"] = fitted.get("historical_updates_omitted", 0) + len(minimal_updates) - 1
        else:
            fitted.pop("historical_updates", None)
        if fits():
            return fitted
    excerpt = fitted.get("excerpt")
    if isinstance(excerpt, str) and excerpt:
        low, high = 0, len(excerpt)
        while low < high:
            middle = (low + high + 1) // 2
            fitted["excerpt"] = excerpt[:middle]
            if len(_json_text(envelope([fitted]))) <= budget:
                low = middle
            else:
                high = middle - 1
        if low:
            fitted["excerpt"] = excerpt[:low]
            return fitted
        fitted.pop("excerpt", None)
    fitted["preview_unavailable"] = True
    return fitted if fits() else None


def compact_history(
    result: dict,
    query: str,
    limit: int = 3,
    container_ref: str | None = None,
    thread_ref: str | None = None,
    search_mode: str | None = None,
    requested_work_ref: str | None = None,
    *,
    result_offset: int = 0,
    result_revision: str | None = None,
    revision_context: dict[str, object] | None = None,
    include_packaging_observation: bool = False,
) -> dict:
    page_error = _history_page_request_error(1, result_offset, result_revision)
    if page_error is not None:
        return page_error
    hits: list[dict] = []
    foreign_sessions: dict[str, str] = {}
    for item in result.get("results", [])[:max(0, limit)]:
        if item.get("source_item_id") is None:
            continue
        updates = item.get("historical_updates") or []
        guidance = (
            "A current replacement is available; prefer it for current guidance."
            if any(update.get("replacement_status") == "current" for update in updates)
            else (
                "This is historical evidence and may need live verification for current-state questions."
                if any(update.get("status") == "outdated" for update in updates)
                else None
            )
        )
        hit = {"source_item_id": item["source_item_id"]}
        if item.get("work_refs"):
            hit["work_refs"] = item["work_refs"]
        if guidance:
            hit["replacement_guidance"] = guidance
        hit.update(_history_fields(item))
        excerpt = build_excerpt(item.get("excerpt") or "", max_length=240, query=query).strip()
        if excerpt:
            hit["excerpt"] = excerpt
        else:
            hit["preview_unavailable"] = True
        if (source := item.get("retrieval_source")) is not None:
            hit["match_channel"] = {
                "lexical": "text match",
                "vector": "meaning match",
                "both": "text and meaning match",
            }.get(source, "match")
        source_thread = item.get("thread_ref")
        if not source_thread or not thread_ref:
            hit["session_group"] = "unknown"
        elif source_thread == thread_ref:
            hit["session_group"] = "current"
        else:
            hit["session_group"] = foreign_sessions.setdefault(source_thread, f"other-{len(foreign_sessions) + 1}")
        for key in ("role", "occurred_at"):
            if item.get(key) is not None:
                hit[key] = item[key]
        hits.append(hit)
    current_revision = hashlib.sha256(
        _json_text(
            {
                "contract": "history-result-page/v1",
                "request": revision_context or {},
                "results": hits,
            }
        ).encode("utf-8")
    ).hexdigest()
    if result_revision is not None and result_revision != current_revision:
        return {
            "error": "history_result_revision_stale",
            "error_kind": "stale_result_revision",
            "retryable": True,
            "action": "restart at result_offset 0 to obtain the current result_revision",
        }
    lookup_event_id = result.get("lookup_event_id")
    if lookup_event_id is None and result.get("delivery_attempt_id"):
        lookup_event_id = "0" * 36
    def base_payload(page: list[dict], offset: int) -> dict:
        next_index = offset + len(page)
        payload = {
            "results": page,
            "lookup_event_id": lookup_event_id,
            "effective_max_chars": MCP_SEARCH_MAX_CHARS,
            "result_offset": offset,
            "next_offset": next_index if next_index < len(hits) else None,
            "has_more": next_index < len(hits),
            "total_count": len(hits),
            "result_revision": current_revision,
        }
        if search_mode is not None:
            payload["search_mode"] = search_mode
        if requested_work_ref is not None:
            payload["requested_work_ref"] = requested_work_ref
        if hits:
            payload["historical_reminder"] = "History is evidence, not proof of messages, approval, live state, or actions. Expand source_item_id; use this page's lookup_event_id as parent_lookup_id. Verify volatile claims live; if unavailable, say so."
        if result.get("decision_reason") is not None:
            payload["decision_reason"] = result["decision_reason"]
        return payload
    def observed(payload: dict, page: list[dict], offset: int) -> dict:
        if include_packaging_observation:
            payload["packaging_observation"] = {
                "observed_at": "creation",
                "budget": MCP_SEARCH_MAX_CHARS,
                "retained_final_ranks": list(range(offset + 1, offset + len(page) + 1)),
                "omitted_count": max(0, len(hits) - offset - len(page)),
                "fit_status": "fit" if offset + len(page) >= len(hits) else "truncated",
            }
        return payload
    if not hits and result_offset == 0 and result_revision is None:
        payload = {"results": [], "lookup_event_id": lookup_event_id}
        if search_mode is not None:
            payload["search_mode"] = search_mode
        if requested_work_ref is not None:
            payload["requested_work_ref"] = requested_work_ref
        if result.get("decision_reason") is not None:
            payload["decision_reason"] = result["decision_reason"]
        if result.get("decision_reason") == "source_only_search" and container_ref:
            if requested_work_ref is not None:
                payload["empty_result_hint"] = "Copy injected work_ref. If absent, use broad search; never guess. Add query for a question."
            else:
                payload["requested_container_ref"] = container_ref[:64]
                if len(container_ref) > 64:
                    payload["container_ref_truncated"] = True
                payload["empty_result_hint"] = "Copy the injected container_ref exactly; never derive or guess it."
        for key in ("requested_work_ref", "requested_container_ref", "container_ref_truncated", "empty_result_hint"):
            if len(_json_text(payload)) <= MCP_SEARCH_EMPTY_MAX_CHARS:
                break
            payload.pop(key, None)
        return observed(payload, [], 0)
    effective_offset = min(result_offset, len(hits))
    if effective_offset == len(hits):
        return observed(base_payload([], effective_offset), [], effective_offset)
    page: list[dict] = []
    for candidate in hits[effective_offset:]:
        if len(_json_text(base_payload([*page, candidate], effective_offset))) <= MCP_SEARCH_MAX_CHARS:
            page.append(candidate)
            continue
        if page:
            break
        fitted = _fit_history_hit(
            candidate,
            lambda items: base_payload(items, effective_offset),
            MCP_SEARCH_MAX_CHARS,
        )
        if fitted is None:
            return {
                "error": "history_result_exceeds_response_budget",
                "error_kind": "history_result_exceeds_response_budget",
                "result_offset": effective_offset,
                "retryable": False,
                "action": "the retained result cannot be represented safely",
            }
        page.append(fitted)
    return observed(base_payload(page, effective_offset), page, effective_offset)