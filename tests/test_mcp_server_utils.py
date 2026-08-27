"""Unit tests for MCP server utility functions that don't require the mcp package."""

from __future__ import annotations

from app.mcp.server import _bounded_error, _json_text, _relay_text, _strip_pydantic_input


def test_bounded_error_preserves_status_code() -> None:
    result = {"error": "bad request", "status_code": 422, "detail": {"detail": []}}
    out = _bounded_error(result, budget=2000)
    assert out["status_code"] == 422


def test_strip_pydantic_input_removes_input_and_url() -> None:
    detail = {
        "detail": [
            {
                "type": "string_too_long",
                "loc": ["body", "payload"],
                "msg": "too long",
                "input": "x" * 2000,
                "url": "https://example.com",
            },
            {"type": "missing", "loc": ["body", "actor_ref"], "msg": "required"},
        ]
    }
    stripped = _strip_pydantic_input(detail)
    assert isinstance(stripped, dict)
    for item in stripped["detail"]:
        assert "input" not in item
        assert "url" not in item
    assert stripped["detail"][0]["msg"] == "too long"
    assert stripped["detail"][1]["msg"] == "required"


def test_bounded_error_pydantic_422_fits_budget_after_strip() -> None:
    result = {
        "error": "Client error '422 Unprocessable Content'",
        "status_code": 422,
        "detail": {
            "detail": [
                {
                    "type": "string_too_long",
                    "loc": ["body", "payload"],
                    "msg": "String should have at most 1500 characters",
                    "input": "x" * 2000,
                    "url": "https://example.com",
                },
            ]
        },
    }
    out = _bounded_error(result, budget=2000)
    assert len(_json_text(out)) <= 2000
    assert out["status_code"] == 422
    assert out["detail"]["detail"][0]["msg"] == "String should have at most 1500 characters"
    assert "input" not in out["detail"]["detail"][0]


def test_strip_pydantic_input_preserves_sibling_fields() -> None:
    detail = {
        "detail": [
            {
                "type": "missing",
                "loc": ["body", "actor_ref"],
                "msg": "required",
                "input": "x" * 500,
                "url": "https://example.com",
            }
        ],
        "metadata": {"request_id": "abc123"},
        "extra": "preserved",
    }
    stripped = _strip_pydantic_input(detail)
    assert stripped["metadata"] == {"request_id": "abc123"}
    assert stripped["extra"] == "preserved"
    assert "input" not in stripped["detail"][0]
    assert "url" not in stripped["detail"][0]
    assert stripped["detail"][0]["msg"] == "required"


def test_bounded_error_binary_search_preserves_status_code() -> None:
    result = {
        "error": "x" * 3000,
        "status_code": 503,
    }
    out = _bounded_error(result, budget=200)
    assert out.get("status_code") == 503
    assert "error" in out
    assert len(_json_text(out)) <= 200


def test_relay_text_strips_pydantic_sibling_fields() -> None:
    """_relay_text (actual caller of _bounded_error) must strip input+sibling fields from 422 errors."""
    import json

    result = {
        "error": "Client error '422 Unprocessable Content'",
        "status_code": 422,
        "detail": {
            "detail": [
                {
                    "type": "string_too_long",
                    "loc": ["body", "payload"],
                    "msg": "too long",
                    "input": "x" * 2000,
                    "url": "https://example.com",
                }
            ],
            "metadata": {"request_id": "abc123"},
        },
    }
    out = json.loads(_relay_text(result))
    assert out["status_code"] == 422
    assert "input" not in out["detail"]["detail"][0]
    assert out["detail"]["metadata"] == {"request_id": "abc123"}

