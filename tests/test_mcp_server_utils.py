"""Unit tests for MCP server utility functions that don't require the mcp package."""

from __future__ import annotations

from app.mcp.server import _bounded_error, _json_text, _strip_pydantic_input


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
    # Simulate the 422 relay_send returns when payload exceeds 1500 chars.
    # Without stripping, 'input' alone pushes the detail over 2000 chars.
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


def test_bounded_error_preserves_status_code_in_truncation_path() -> None:
    # When error string is so long that detail was already dropped and the full
    # error+status_code payload still exceeds budget, the binary-search path must
    # keep status_code in the compact result.
    result = {
        "error": "x" * 3000,
        "status_code": 503,
    }
    out = _bounded_error(result, budget=200)
    assert out.get("status_code") == 503
    assert "error" in out
    assert len(_json_text(out)) <= 200
