"""Unit tests for ``providers.llm.redacting_wrapper`` (PR 0 step 7).

Locks the defense-in-depth barrier: even if an LLM re-materializes a
secret in its ``parsed_json`` output, the wrapper redacts every
string leaf before the response reaches the extractor.

Behavior invariants:
- Every string leaf in ``parsed_json`` and ``raw_text`` passes
  through :func:`semantic.redaction.redact_sensitive`.
- Container types (dict / list / tuple) are preserved.
- Numeric / boolean / None values are passed through unchanged.
- Cycle-safe (guarded by ``visited`` set) — in-process object
  graphs that back-reference never infinite-loop.
- Idempotent — wrapping an already-wrapped provider is a no-op.
- ``metadata`` field is passed through unchanged (never
  user-content-derived).
"""

from __future__ import annotations

import json

from providers.llm.base import (
    LLMCallMetadata,
    LLMErrorKind,
    LLMJsonResponse,
    LLMProvider,
)
from providers.llm.redacting_wrapper import (
    RedactingLLMProviderWrapper,
    _redact_parsed_json_value,
)


# --------------------------------------------------------------------------- #
# Stub inner provider — returns whatever we set                                #
# --------------------------------------------------------------------------- #


class _EchoProvider(LLMProvider):
    """Inner provider that returns a canned :class:`LLMJsonResponse`."""

    def __init__(self, response: LLMJsonResponse):
        self._response = response
        self.calls: list[dict] = []

    def generate_json(
        self, *, system_prompt, user_prompt, schema_description,
    ) -> LLMJsonResponse:
        self.calls.append({
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
            "schema_description": schema_description,
        })
        return self._response


_SAMPLE_METADATA = LLMCallMetadata(
    provider_name="test",
    provider_kind="stub",
    model="stub-1",
    error_kind=LLMErrorKind.NONE if hasattr(LLMErrorKind, "NONE") else LLMErrorKind.UNKNOWN,
)


# --------------------------------------------------------------------------- #
# Tier A shape secrets in the LLM output                                       #
# --------------------------------------------------------------------------- #


class TestParsedJsonStringsRedacted:
    def test_github_pat_in_top_level_string(self):
        secret = "ghp_" + ("Z" * 36)
        inner = _EchoProvider(LLMJsonResponse(
            raw_text=json.dumps({"key_finding": f"agent leaked {secret}"}),
            parsed_json={"key_finding": f"agent leaked {secret}"},
            metadata=_SAMPLE_METADATA,
        ))
        wrapped = RedactingLLMProviderWrapper(inner)
        response = wrapped.generate_json(
            system_prompt="", user_prompt="", schema_description="",
        )
        assert secret not in response.parsed_json["key_finding"]
        assert secret not in response.raw_text
        assert "[REDACTED]" in response.parsed_json["key_finding"]

    def test_nested_list_of_evidence_strings(self):
        secret = "sk-ant-api03-" + ("Q" * 40)
        inner = _EchoProvider(LLMJsonResponse(
            raw_text="{}",
            parsed_json={
                "evidence": [
                    "line 1: normal text",
                    f"line 2: {secret}",
                    "line 3: more normal text",
                ],
            },
            metadata=_SAMPLE_METADATA,
        ))
        wrapped = RedactingLLMProviderWrapper(inner)
        response = wrapped.generate_json(
            system_prompt="", user_prompt="", schema_description="",
        )
        assert secret not in json.dumps(response.parsed_json)
        # Container type preserved.
        assert isinstance(response.parsed_json["evidence"], list)

    def test_nested_dict_deep_structure(self):
        secret = "xoxb-1234567890-9876543210-" + ("a" * 30)
        inner = _EchoProvider(LLMJsonResponse(
            raw_text="{}",
            parsed_json={
                "outer": {
                    "middle": {
                        "inner": f"copied from source: {secret}",
                    },
                    "sibling_number": 42,
                },
            },
            metadata=_SAMPLE_METADATA,
        ))
        wrapped = RedactingLLMProviderWrapper(inner)
        response = wrapped.generate_json(
            system_prompt="", user_prompt="", schema_description="",
        )
        assert secret not in json.dumps(response.parsed_json)
        # Numeric leaf preserved.
        assert response.parsed_json["outer"]["sibling_number"] == 42


class TestTypesPreserved:
    def test_null_bool_int_float_pass_through(self):
        inner = _EchoProvider(LLMJsonResponse(
            raw_text="{}",
            parsed_json={
                "n": None,
                "b_true": True,
                "b_false": False,
                "i": 42,
                "f": 3.14,
                "s": "no secret here",
            },
            metadata=_SAMPLE_METADATA,
        ))
        wrapped = RedactingLLMProviderWrapper(inner)
        response = wrapped.generate_json(
            system_prompt="", user_prompt="", schema_description="",
        )
        payload = response.parsed_json
        assert payload["n"] is None
        assert payload["b_true"] is True
        assert payload["b_false"] is False
        assert payload["i"] == 42
        assert payload["f"] == 3.14
        assert payload["s"] == "no secret here"

    def test_container_types_preserved(self):
        inner = _EchoProvider(LLMJsonResponse(
            raw_text="{}",
            parsed_json={
                "as_list": ["a", "b"],
                "as_tuple_via_helper": ("a", "b"),  # dicts don't roundtrip via JSON but helper should preserve
                "as_dict": {"x": "y"},
            },
            metadata=_SAMPLE_METADATA,
        ))
        wrapped = RedactingLLMProviderWrapper(inner)
        response = wrapped.generate_json(
            system_prompt="", user_prompt="", schema_description="",
        )
        payload = response.parsed_json
        assert isinstance(payload["as_list"], list)
        assert isinstance(payload["as_tuple_via_helper"], tuple)
        assert isinstance(payload["as_dict"], dict)


class TestCycleSafety:
    def test_recursive_helper_survives_cycles(self):
        # The helper is exposed for direct testing. LLM providers
        # never return cyclic structures via JSON parsing — this is
        # defense against any in-process caller that constructs a
        # response with a back-reference.
        d: dict = {"a": "clean text"}
        d["self"] = d
        result = _redact_parsed_json_value(d)
        assert result["a"] == "clean text"
        # The cycle is broken: 'self' is the placeholder, not the
        # original object.
        assert result["self"] == "[REDACTED CYCLE]"


class TestIdempotence:
    def test_wrapping_twice_produces_same_output(self):
        secret = "ghp_" + ("Z" * 36)
        inner = _EchoProvider(LLMJsonResponse(
            raw_text=json.dumps({"note": f"contains {secret}"}),
            parsed_json={"note": f"contains {secret}"},
            metadata=_SAMPLE_METADATA,
        ))
        once = RedactingLLMProviderWrapper(inner)
        twice = RedactingLLMProviderWrapper(once)
        r1 = once.generate_json(system_prompt="", user_prompt="", schema_description="")
        r2 = twice.generate_json(system_prompt="", user_prompt="", schema_description="")
        assert r1.parsed_json == r2.parsed_json
        assert r1.raw_text == r2.raw_text
        assert secret not in r1.parsed_json["note"]


class TestMetadataUntouched:
    def test_metadata_passes_through(self):
        inner = _EchoProvider(LLMJsonResponse(
            raw_text="{}",
            parsed_json={"x": "no secret"},
            metadata=_SAMPLE_METADATA,
        ))
        wrapped = RedactingLLMProviderWrapper(inner)
        response = wrapped.generate_json(
            system_prompt="", user_prompt="", schema_description="",
        )
        assert response.metadata is _SAMPLE_METADATA


class TestEmptyResponses:
    def test_empty_raw_text_and_parsed_json(self):
        inner = _EchoProvider(LLMJsonResponse(
            raw_text="",
            parsed_json={},
            metadata=_SAMPLE_METADATA,
        ))
        wrapped = RedactingLLMProviderWrapper(inner)
        response = wrapped.generate_json(
            system_prompt="", user_prompt="", schema_description="",
        )
        # No crash, no exception.
        assert response.raw_text == ""
        assert response.parsed_json == {}


def test_model_call_guard_resets_after_exception() -> None:
    from providers.llm.base import ModelCallCancelledError, check_model_call_allowed, model_call_guard
    import pytest

    with pytest.raises(ModelCallCancelledError):
        with model_call_guard(lambda: False):
            check_model_call_allowed()
    check_model_call_allowed()


def test_redacting_wrapper_blocks_stale_guard_before_delegate() -> None:
    from providers.llm.base import model_call_guard
    import pytest

    inner = _EchoProvider(LLMJsonResponse(raw_text="{}", parsed_json={}))
    wrapped = RedactingLLMProviderWrapper(inner)
    with model_call_guard(lambda: False):
        with pytest.raises(RuntimeError, match="no longer current"):
            wrapped.generate_json(system_prompt="s", user_prompt="u", schema_description="d")
    assert inner.calls == []
