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

    first_page = result
    seen = [hit["source_item_id"] for hit in result["results"]]
    while result["next_offset"] is not None:
        result = _compact_history(
            {"results": results, "lookup_event_id": "lookup-1"},
            "漢字",
            limit=3,
            thread_ref="current",
            search_mode="exact_work_ref",
            requested_work_ref=work_ref,
            result_offset=result["next_offset"],
            result_revision=result["result_revision"],
        )
        seen.extend(hit["source_item_id"] for hit in result["results"])

    assert seen == expected_ids
    assert first_page["requested_work_ref"] == work_ref
    assert all("thread_ref" not in hit for hit in first_page["results"])
    assert "query" not in first_page
    assert len(first_page["historical_reminder"]) <= 240
    assert "source_item_id" in first_page["historical_reminder"]
    assert "lookup_event_id" in first_page["historical_reminder"]
    assert first_page["results"][0]["recorded_at_source"] == "ingest"
    assert first_page["results"][0]["historical_updates"][0]["replacement_status"] == "current"
    assert len(_json_text(first_page)) <= _MCP_SEARCH_MAX_CHARS


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

    seen = [hit["source_item_id"] for hit in candidate["results"]]
    while candidate["next_offset"] is not None:
        candidate = _compact_history(
            {"results": results, "lookup_event_id": "l" * 36},
            "evidence",
            limit=10,
            thread_ref="current-session",
            search_mode="exact_work_ref",
            requested_work_ref=requested_work_ref,
            result_offset=candidate["next_offset"],
            result_revision=candidate["result_revision"],
        )
        seen.extend(hit["source_item_id"] for hit in candidate["results"])
        assert len(_json_text(candidate)) <= _MCP_SEARCH_MAX_CHARS

    assert seen == baseline_ids


def test_ten_hit_pressure_pages_all_retained_ids_with_nonempty_previews() -> None:
    ids = [f"hit-{index:02d}" for index in range(10)]
    result = {"results": [
        {"source_item_id": source_item_id, "excerpt": f"evidence {index}"}
        for index, source_item_id in enumerate(ids)
    ], "lookup_event_id": "l" * 36}

    seen: list[str] = []
    offset = 0
    revision = None
    while True:
        page = _compact_history(
            result,
            "evidence",
            limit=10,
            result_offset=offset,
            result_revision=revision,
        )
        revision = page["result_revision"]
        seen.extend(hit["source_item_id"] for hit in page["results"])
        assert all(hit.get("excerpt") for hit in page["results"])
        if page["next_offset"] is None:
            break
        offset = page["next_offset"]

    assert seen == ids


def test_fifty_candidates_remain_reachable_across_bounded_pages() -> None:
    ids = [f"candidate-{index:02d}" for index in range(50)]
    result = {"results": [
        {"source_item_id": source_item_id, "excerpt": f"evidence {index}"}
        for index, source_item_id in enumerate(ids)
    ], "lookup_event_id": "l" * 36}

    seen: list[str] = []
    offset = 0
    revision = None
    for _ in range(50):
        page = _compact_history(
            result,
            "evidence",
            limit=50,
            result_offset=offset,
            result_revision=revision,
        )
        revision = page["result_revision"]
        seen.extend(hit["source_item_id"] for hit in page["results"])
        if page["next_offset"] is None:
            break
        offset = page["next_offset"]
    else:
        pytest.fail("bounded paging did not terminate")

    assert seen == ids
    assert page["total_count"] == 50


def test_empty_backend_excerpt_is_navigation_only() -> None:
    page = _compact_history(
        {
            "results": [{"source_item_id": "empty", "excerpt": "   "}],
            "lookup_event_id": "l" * 36,
        },
        "missing",
        limit=1,
    )

    hit = page["results"][0]
    assert hit["preview_unavailable"] is True
    assert "excerpt" not in hit
    assert page["lookup_event_id"] == "l" * 36
    assert "lookup_event_id" in page["historical_reminder"]


def test_navigation_only_under_pressure_keeps_replacement_guidance_and_status() -> None:
    page = _compact_history(
        {
            "results": [{
                "source_item_id": "outdated",
                "excerpt": "",
                "historical_updates": [{
                    "status": "outdated",
                    "replacement_status": "current",
                    "current_text": "replacement " * 1000,
                }],
            }],
            "lookup_event_id": "l" * 36,
        },
        "missing",
        limit=1,
    )

    hit = page["results"][0]
    assert hit["preview_unavailable"] is True
    assert hit["replacement_guidance"]
    update = hit["historical_updates"][0]
    assert update["status"] == "outdated"
    assert update["replacement_status"] == "current"
    assert len(update.get("current_text", "")) < len("replacement " * 1000)
    assert len(_json_text(page)) <= _MCP_SEARCH_MAX_CHARS


def test_terminal_offsets_and_equal_length_revision_changes_are_explicit() -> None:
    result = {
        "results": [
            {"source_item_id": "a", "excerpt": "alpha"},
            {"source_item_id": "b", "excerpt": "bravo"},
        ],
        "lookup_event_id": "l" * 36,
    }
    first = _compact_history(result, "", limit=2)
    terminal = _compact_history(
        result,
        "",
        limit=2,
        result_offset=first["total_count"],
        result_revision=first["result_revision"],
    )
    over_end = _compact_history(
        result,
        "",
        limit=2,
        result_offset=first["total_count"] + 1,
        result_revision=first["result_revision"],
    )
    assert terminal["results"] == over_end["results"] == []
    assert terminal["next_offset"] is over_end["next_offset"] is None

    changed = {**result, "results": [result["results"][1], result["results"][0]]}
    stale = _compact_history(
        changed,
        "",
        limit=2,
        result_offset=1,
        result_revision=first["result_revision"],
    )
    assert stale["error"] == "history_result_revision_stale"


def test_serialized_unicode_and_escaped_pages_stay_within_budget() -> None:
    result = {
        "results": [{
            "source_item_id": f"unicode-{index}",
            "excerpt": ('quoted \\"漢字😀\\" evidence ' * 300),
        } for index in range(10)],
        "lookup_event_id": "l" * 36,
    }
    page = _compact_history(result, "漢字", limit=10)

    assert len(_json_text(page)) <= _MCP_SEARCH_MAX_CHARS
    assert page["effective_max_chars"] <= _MCP_SEARCH_MAX_CHARS



def test_revision_binds_request_even_when_candidates_are_identical() -> None:
    result = {
        "results": [{"source_item_id": "same", "excerpt": "same evidence"}],
        "lookup_event_id": "l" * 36,
    }
    first = _compact_history(
        result,
        "same",
        limit=1,
        revision_context={"mode": "broad", "query": "first"},
    )

    stale = _compact_history(
        result,
        "same",
        limit=1,
        result_offset=0,
        result_revision=first["result_revision"],
        revision_context={"mode": "broad", "query": "second"},
    )

    assert stale["error"] == "history_result_revision_stale"


def test_impossible_singleton_fails_without_skipping_candidate() -> None:
    page = _compact_history(
        {
            "results": [{"source_item_id": "x" * 2200, "excerpt": "evidence"}],
            "lookup_event_id": "l" * 36,
        },
        "evidence",
        limit=1,
    )

    assert page["error"] == "history_result_exceeds_response_budget"
    assert page["result_offset"] == 0
    assert page["retryable"] is False

def test_compactor_exposes_creation_observation_without_changing_normal_shape() -> None:
    payload = {
        "results": [
            {
                "source_item_id": str(i),
                "excerpt": "長い 😀 " * 80,
                "retrieval_source": "both",
                "historical_updates": [{"replacement_status": "current"}],
            }
            for i in range(8)
        ]
    }
    normal = _compact_history(payload, "unicode query", limit=8)
    observed = _compact_history(payload, "unicode query", limit=8, include_packaging_observation=True)
    assert "packaging_observation" not in normal
    assert set(normal).issubset(observed)
    observation = observed["packaging_observation"]
    assert set(observation) <= {"observed_at", "budget", "retained_final_ranks", "omitted_count", "fit_status"}
    assert observation["observed_at"] == "creation"
    assert observation["retained_final_ranks"] == list(range(1, len(normal["results"]) + 1))
    assert observation["omitted_count"] == max(0, len(payload["results"]) - len(normal["results"]))
    assert observation["fit_status"] in {"fit", "truncated"}
