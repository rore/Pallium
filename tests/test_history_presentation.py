from __future__ import annotations

import json

import pytest

from app.mcp.server import (
    _MCP_EXPANSION_MAX_CHARS,
    _MCP_SEARCH_MAX_CHARS,
    _bounded_expansion,
    _compact_history,
    _json_text,
)


def test_search_cues_are_plain_and_replacement_precedes_excerpt() -> None:
    result = _compact_history(
        {
            "results": [
                {
                    "source_item_id": "s",
                    "excerpt": "текст 😀",
                    "thread_ref": "t",
                    "retrieval_source": "both",
                    "historical_updates": [
                        {
                            "status": "outdated",
                            "replacement_status": "current",
                            "current_text": "now",
                        }
                    ],
                }
            ]
        },
        "тек",
        thread_ref="t",
    )

    hit = result["results"][0]
    assert list(hit).index("replacement_guidance") < list(hit).index("excerpt")
    assert list(hit).index("historical_updates") < list(hit).index("excerpt")
    assert hit["match_channel"] == "text and meaning match"
    assert hit["session_group"] == "current"
    serialized = json.dumps(result)
    assert "score" not in serialized
    assert "confidence" not in serialized
    assert len(_json_text(result)) <= _MCP_SEARCH_MAX_CHARS


@pytest.mark.parametrize(
    ("item_thread", "active_thread", "expected"),
    [
        ("a", "a", "current"),
        ("a", "b", "other-1"),
        (None, "b", "unknown"),
        ("a", None, "unknown"),
    ],
)
def test_search_session_group(
    item_thread: str | None,
    active_thread: str | None,
    expected: str,
) -> None:
    result = _compact_history(
        {
            "results": [
                {
                    "source_item_id": "s",
                    "excerpt": "x",
                    "thread_ref": item_thread,
                }
            ]
        },
        "x",
        thread_ref=active_thread,
    )

    assert result["results"][0]["session_group"] == expected


def test_replacement_guidance_survives_budget_and_missing_optionals() -> None:
    result = _compact_history(
        {
            "results": [
                {
                    "source_item_id": "s",
                    "excerpt": "x" * 5000,
                    "historical_updates": [
                        {
                            "status": "outdated",
                            "replacement_status": "current",
                            "current_text": "replacement" * 500,
                        }
                    ],
                    "retrieval_source": "vector",
                    "thread_ref": "t",
                }
            ]
        },
        "x",
        thread_ref="t",
    )

    hit = result["results"][0]
    assert "History is evidence, not proof" in result["historical_reminder"]
    assert "replacement_guidance" in hit
    assert list(hit).index("historical_updates") < list(hit).index("excerpt")
    assert len(_json_text(result)) <= _MCP_SEARCH_MAX_CHARS


def test_search_unicode_and_limit_boundaries() -> None:
    result = _compact_history(
        {"results": [{"source_item_id": "s", "excerpt": "漢字😀" * 1000}]},
        "漢",
    )

    assert "漢" in result["results"][0]["excerpt"]
    assert "History is evidence, not proof" in result["historical_reminder"]
    assert len(_json_text(result)) <= _MCP_SEARCH_MAX_CHARS
    assert _compact_history(
        {"results": [{"source_item_id": "s", "excerpt": "x"}]},
        "x",
        limit=0,
    )["results"] == []


def test_search_stale_only_warning_survives_budget() -> None:
    result = _compact_history(
        {
            "results": [{
                "source_item_id": "stale",
                "excerpt": "\\\"界😀" * 2000,
                "historical_updates": [{
                    "status": "outdated",
                    "replacement_status": "unavailable",
                }],
            }],
        },
        "界",
    )

    assert "if unavailable, say so" in result["historical_reminder"]
    assert len(_json_text(result)) <= _MCP_SEARCH_MAX_CHARS

def test_expansion_labels_and_bounds() -> None:
    result = _bounded_expansion(
        {
            "items": [
                {
                    "source_item_id": "a",
                    "is_anchor": True,
                    "content": "😀" * 500,
                },
                {
                    "source_item_id": "n",
                    "is_anchor": False,
                    "content": "контекст",
                },
            ]
        },
        4000,
    )

    assert [item["presentation_role"] for item in result["items"]] == [
        "anchor",
        "neighbor",
    ]
    assert len(_json_text(result)) <= 4000
    assert _bounded_expansion(
        {},
        _MCP_EXPANSION_MAX_CHARS + 1,
    ) == _bounded_expansion({}, _MCP_EXPANSION_MAX_CHARS)
    assert "error" in _bounded_expansion({}, 1)

def test_search_session_groups_repeat_without_exposing_thread_ids() -> None:
    result = _compact_history(
        {"results": [
            {"source_item_id": "a", "excerpt": "first", "thread_ref": "current"},
            {"source_item_id": "b", "excerpt": "second", "thread_ref": "foreign"},
            {"source_item_id": "c", "excerpt": "third", "thread_ref": "foreign"},
        ]},
        "",
        thread_ref="current",
    )

    assert [hit["session_group"] for hit in result["results"]] == ["current", "other-1", "other-1"]
    assert "thread_ref" not in json.dumps(result)

def test_grouped_history_preserves_feasible_ids_order_and_unicode_under_budget() -> None:
    work_ref = "work-" + ("w" * 60)
    results = []
    for index in range(3):
        item = {
            "source_item_id": f"{index:02d}" + ("s" * 34),
            "excerpt": 'quoted "漢字😀 evidence' * 8,
            "thread_ref": "current" if index == 0 else "foreign-a" if index == 1 else "foreign-b",
            "work_refs": [work_ref],
            "recorded_at": "2026-09-11T12:34:56.123456+00:00",
            "recorded_at_source": "ingest",
            "occurred_at": "2026-09-11T12:30:00+00:00",
            "role": "assistant",
        }
        if index == 0:
            item["historical_updates"] = [{
                "memory_type": "decision",
                "status": "outdated",
                "replacement_status": "current",
                "current_memory_object_id": "m" * 36,
                "current_recorded_at": "2026-09-11T12:40:00+00:00",
            }]
        results.append(item)

    expected_ids = [item["source_item_id"] for item in results]
    result = _compact_history(
        {"results": results, "lookup_event_id": "lookup-1"},
        "漢字",
        limit=3,
        thread_ref="current",
        search_mode="exact_work_ref",
        requested_work_ref=work_ref,
    )

    assert [hit["source_item_id"] for hit in result["results"]] == expected_ids
    assert result["requested_work_ref"] == work_ref
    assert all("thread_ref" not in hit for hit in result["results"])
    assert "query" not in result
    assert len(result["historical_reminder"]) <= 240
    assert "source_item_id" in result["historical_reminder"]
    assert "lookup_event_id" in result["historical_reminder"]
    assert result["results"][0]["recorded_at_source"] == "ingest"
    assert result["results"][0]["historical_updates"][0]["replacement_status"] == "current"
    assert len(_json_text(result)) <= _MCP_SEARCH_MAX_CHARS


@pytest.mark.parametrize("requested_work_ref", [None, "work-" + ("w" * 60)])
def test_ten_hit_grouping_never_drops_origin_main_baseline_ids(
    requested_work_ref: str | None,
) -> None:
    # Measured origin/main retains all ten IDs for this identical boundary payload.
    baseline_ids = [f"{index:02d}" + ("s" * 41) for index in range(10)]
    results = [
        {
            "source_item_id": source_item_id,
            "excerpt": "evidence " * 50,
            "thread_ref": "foreign-session",
            "recorded_at": "2026-09-11T12:34:56.123456+00:00",
            "recorded_at_source": "ingest",
        }
        for source_item_id in baseline_ids
    ]

    candidate = _compact_history(
        {"results": results, "lookup_event_id": "l" * 36},
        "evidence",
        limit=10,
        thread_ref="current-session",
        search_mode="exact_work_ref",
        requested_work_ref=requested_work_ref,
    )

    assert [hit["source_item_id"] for hit in candidate["results"]] == baseline_ids
    assert len(_json_text(candidate)) <= _MCP_SEARCH_MAX_CHARS
