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
    assert hit["session_cue"] == "same session"
    serialized = json.dumps(result)
    assert "score" not in serialized
    assert "confidence" not in serialized
    assert len(_json_text(result)) <= _MCP_SEARCH_MAX_CHARS


@pytest.mark.parametrize(
    ("item_thread", "active_thread", "expected"),
    [
        ("a", "a", "same session"),
        ("a", "b", "different session"),
        (None, "b", "session unknown"),
    ],
)
def test_search_session_cue(
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

    assert result["results"][0]["session_cue"] == expected


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
    assert "cannot prove messages were received or sent" in result["historical_reminder"]
    assert "replacement_guidance" in hit
    assert list(hit).index("historical_updates") < list(hit).index("excerpt")
    assert len(_json_text(result)) <= _MCP_SEARCH_MAX_CHARS


def test_search_unicode_and_limit_boundaries() -> None:
    result = _compact_history(
        {"results": [{"source_item_id": "s", "excerpt": "漢字😀" * 1000}]},
        "漢",
    )

    assert "漢" in result["results"][0]["excerpt"]
    assert "cannot prove messages were received or sent" in result["historical_reminder"]
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
