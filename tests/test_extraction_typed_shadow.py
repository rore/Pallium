"""W5 PR 2 — unit tests for the typed shadow extractor.

Core invariants:

- ``run_typed_shadow_extraction`` never raises. LLM errors and
  schema failures become ``TypedShadowExtraction`` return values
  with an appropriate ``parse_status``.
- Well-formed responses parse into typed dataclasses.
- Individual malformed items are dropped; the rest survive.
- Length caps are enforced (over-max strings are truncated).
- No live-path imports (verified in
  ``tests/test_extraction_typed_shadow_isolation.py``, but a
  smoke assertion here too).
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timezone

import pytest

from core.models import SourceItem
from providers.llm.base import LLMCallMetadata, LLMJsonResponse, LLMProvider, LLMProviderError
from semantic.extraction_typed_shadow import (
    MAX_ARTIFACT_LEN,
    MAX_COMMAND_FAMILY_LEN,
    MAX_EVIDENCE_LEN,
    MAX_ITEMS_PER_ARRAY,
    MAX_PROMPT_BYTES,
    MAX_STATEMENT_LEN,
    MAX_SUBJECT_LEN,
    MAX_SUPERSESSION_ITEMS,
    TYPED_SHADOW_PROMPT_VERSION,
    TypedShadowConstraint,
    TypedShadowDecision,
    TypedShadowExtraction,
    TypedShadowInvestigation,
    TypedShadowOperationalFact,
    TypedShadowSupersession,
    run_typed_shadow_extraction,
)


# --------------------------------------------------------------------------- #
# Stub LLM providers                                                          #
# --------------------------------------------------------------------------- #


class StubProvider(LLMProvider):
    """LLM provider that returns a canned JSON response."""

    def __init__(self, response: dict, *, metadata: LLMCallMetadata | None = None):
        self._response = response
        self._metadata = metadata

    def generate_json(
        self, *, system_prompt: str, user_prompt: str, schema_description: str
    ) -> LLMJsonResponse:
        return LLMJsonResponse(
            raw_text=json.dumps(self._response),
            parsed_json=self._response,
            metadata=self._metadata,
        )


class ErrorProvider(LLMProvider):
    """LLM provider that raises a specific exception."""

    def __init__(self, exc: BaseException):
        self._exc = exc

    def generate_json(
        self, *, system_prompt: str, user_prompt: str, schema_description: str
    ) -> LLMJsonResponse:
        raise self._exc


def _source_item(content: str = "test content") -> SourceItem:
    return SourceItem(
        source_type="claude-code",
        source_id="cc-test",
        content_type="text/plain",
        content=content,
        container_ref="git:example/repo",
        thread_ref="thread-1",
    )


# --------------------------------------------------------------------------- #
# Happy path — well-formed JSON                                               #
# --------------------------------------------------------------------------- #


class TestHappyPath:
    def test_all_arrays_empty(self):
        provider = StubProvider({
            "decisions": [],
            "investigations": [],
            "constraints": [],
            "operational_facts": [],
            "supersessions": [],
        })
        result = run_typed_shadow_extraction(_source_item(), provider=provider)
        assert result.parse_status == "ok"
        assert result.parse_error is None
        assert result.total_items() == 0

    def test_one_decision_extracted(self):
        provider = StubProvider({
            "decisions": [{
                "subject": "abstention gate",
                "statement": "use per-type block-score thresholds",
                "rationale": "separable distributions on rated corpus",
                "evidence_span": "user: let's not use an LLM classifier",
                "alternatives_rejected": ["LLM classifier"],
            }],
            "investigations": [], "constraints": [],
            "operational_facts": [], "supersessions": [],
        })
        result = run_typed_shadow_extraction(_source_item(), provider=provider)
        assert result.parse_status == "ok"
        assert len(result.decisions) == 1
        d = result.decisions[0]
        assert d.subject == "abstention gate"
        assert d.statement == "use per-type block-score thresholds"
        assert d.rationale == "separable distributions on rated corpus"
        assert d.alternatives_rejected == ("LLM classifier",)

    def test_one_investigation_extracted(self):
        provider = StubProvider({
            "decisions": [],
            "investigations": [{
                "subject": "flaky test",
                "hypothesis": "test depends on ordering",
                "outcome": "confirmed",
                "resolution": "add explicit sort",
                "evidence_span": "logs show intermittent failures",
            }],
            "constraints": [], "operational_facts": [], "supersessions": [],
        })
        result = run_typed_shadow_extraction(_source_item(), provider=provider)
        assert len(result.investigations) == 1
        assert result.investigations[0].outcome == "confirmed"

    def test_one_constraint_extracted(self):
        provider = StubProvider({
            "decisions": [], "investigations": [],
            "constraints": [{
                "subject": "python interpreter on windows",
                "modality": "require",
                "action": "use_surface",
                "statement": "use the absolute-path interpreter",
                "evidence_span": "ASR blocks Scripts/python.exe",
            }],
            "operational_facts": [], "supersessions": [],
        })
        result = run_typed_shadow_extraction(_source_item(), provider=provider)
        assert len(result.constraints) == 1
        c = result.constraints[0]
        assert c.modality == "require"
        assert c.action == "use_surface"

    def test_one_operational_fact_extracted(self):
        provider = StubProvider({
            "decisions": [], "investigations": [], "constraints": [],
            "operational_facts": [{
                "command_family": "python",
                "subject": "python interpreter on this machine",
                "artifact": "C:/Users/x/.venv/Scripts/python.exe",
                "outcome": "success",
                "evidence_span": "python --version returned 3.13",
            }],
            "supersessions": [],
        })
        result = run_typed_shadow_extraction(_source_item(), provider=provider)
        assert len(result.operational_facts) == 1
        assert result.operational_facts[0].outcome == "success"

    def test_one_supersession_extracted(self):
        provider = StubProvider({
            "decisions": [], "investigations": [], "constraints": [],
            "operational_facts": [],
            "supersessions": [{
                "subject": "abstention gate",
                "supersedes_statement": "use LLM classifier",
                "new_statement": "use per-type thresholds",
                "evidence_span": "decision changed 2026-06-27",
            }],
        })
        result = run_typed_shadow_extraction(_source_item(), provider=provider)
        assert len(result.supersessions) == 1

    def test_all_five_arrays_populated(self):
        provider = StubProvider({
            "decisions": [{"subject": "s", "statement": "st", "evidence_span": "e"}],
            "investigations": [{
                "subject": "s", "hypothesis": "h", "outcome": "inconclusive",
                "evidence_span": "e",
            }],
            "constraints": [{
                "subject": "s", "modality": "prefer", "action": "perform_step",
                "statement": "st", "evidence_span": "e",
            }],
            "operational_facts": [{
                "command_family": "python", "subject": "s", "artifact": "a",
                "evidence_span": "e",
            }],
            "supersessions": [{
                "subject": "s", "supersedes_statement": "old",
                "new_statement": "new", "evidence_span": "e",
            }],
        })
        result = run_typed_shadow_extraction(_source_item(), provider=provider)
        assert result.parse_status == "ok"
        assert result.total_items() == 5

    def test_prompt_version_propagates(self):
        provider = StubProvider({
            "decisions": [], "investigations": [], "constraints": [],
            "operational_facts": [], "supersessions": [],
        })
        result = run_typed_shadow_extraction(
            _source_item(), provider=provider, prompt_version="custom_v99"
        )
        assert result.prompt_version == "custom_v99"

    def test_metadata_propagates(self):
        meta = LLMCallMetadata(
            provider_name="stub",
            provider_kind="openai_compatible",
            model="stub-model",
            attempt_count=1,
        )
        provider = StubProvider(
            {
                "decisions": [], "investigations": [], "constraints": [],
                "operational_facts": [], "supersessions": [],
            },
            metadata=meta,
        )
        result = run_typed_shadow_extraction(_source_item(), provider=provider)
        assert result.llm_call_metadata is meta

    def test_shadow_run_id_unique_across_calls(self):
        provider = StubProvider({
            "decisions": [], "investigations": [], "constraints": [],
            "operational_facts": [], "supersessions": [],
        })
        r1 = run_typed_shadow_extraction(_source_item(), provider=provider)
        r2 = run_typed_shadow_extraction(_source_item(), provider=provider)
        assert r1.shadow_run_id != r2.shadow_run_id

    def test_evidence_span_required_on_every_type(self):
        # Regression: a decision without evidence_span must be dropped.
        provider = StubProvider({
            "decisions": [{"subject": "s", "statement": "st"}],  # no evidence
            "investigations": [], "constraints": [],
            "operational_facts": [], "supersessions": [],
        })
        result = run_typed_shadow_extraction(_source_item(), provider=provider)
        assert result.decisions == ()
        assert result.parse_status == "schema_failure"

    def test_over_max_array_length_truncated(self):
        provider = StubProvider({
            "decisions": [
                {
                    "subject": f"decision-{i}",
                    "statement": f"stmt-{i}",
                    "evidence_span": f"ev-{i}",
                }
                for i in range(MAX_ITEMS_PER_ARRAY + 5)
            ],
            "investigations": [], "constraints": [],
            "operational_facts": [], "supersessions": [],
        })
        result = run_typed_shadow_extraction(_source_item(), provider=provider)
        assert len(result.decisions) == MAX_ITEMS_PER_ARRAY
        # Truncation counts as schema divergence.
        assert result.parse_status == "schema_failure"


# --------------------------------------------------------------------------- #
# Schema failures                                                             #
# --------------------------------------------------------------------------- #


class TestSchemaFailure:
    def test_top_level_not_object(self):
        provider = StubProvider(["not", "an", "object"])
        result = run_typed_shadow_extraction(_source_item(), provider=provider)
        assert result.parse_status == "schema_failure"
        assert "top-level not an object" in (result.parse_error or "")

    def test_missing_top_level_key(self):
        # Missing every array.
        provider = StubProvider({})
        result = run_typed_shadow_extraction(_source_item(), provider=provider)
        assert result.parse_status == "schema_failure"
        assert "missing" in (result.parse_error or "")

    def test_wrong_array_type(self):
        provider = StubProvider({
            "decisions": "not-a-list",
            "investigations": [], "constraints": [],
            "operational_facts": [], "supersessions": [],
        })
        result = run_typed_shadow_extraction(_source_item(), provider=provider)
        assert result.parse_status == "schema_failure"
        assert result.decisions == ()

    def test_individual_bad_item_dropped_others_kept(self):
        provider = StubProvider({
            "decisions": [
                {"subject": "good", "statement": "s", "evidence_span": "e"},
                "not-an-object",
                {"subject": "also good", "statement": "s2", "evidence_span": "e2"},
            ],
            "investigations": [], "constraints": [],
            "operational_facts": [], "supersessions": [],
        })
        result = run_typed_shadow_extraction(_source_item(), provider=provider)
        # The middle item drops; the other two survive.
        assert len(result.decisions) == 2
        assert result.parse_status == "schema_failure"

    def test_constraint_invalid_modality_enum(self):
        provider = StubProvider({
            "decisions": [], "investigations": [],
            "constraints": [{
                "subject": "s",
                "modality": "not-valid",
                "action": "use_source",
                "statement": "st",
                "evidence_span": "e",
            }],
            "operational_facts": [], "supersessions": [],
        })
        result = run_typed_shadow_extraction(_source_item(), provider=provider)
        assert result.constraints == ()

    def test_investigation_invalid_outcome_enum(self):
        provider = StubProvider({
            "decisions": [],
            "investigations": [{
                "subject": "s", "hypothesis": "h",
                "outcome": "maybe",
                "evidence_span": "e",
            }],
            "constraints": [], "operational_facts": [], "supersessions": [],
        })
        result = run_typed_shadow_extraction(_source_item(), provider=provider)
        assert result.investigations == ()

    def test_operational_fact_invalid_outcome_dropped_to_none(self):
        # Invalid outcome is a soft failure — item is kept, outcome set to None.
        provider = StubProvider({
            "decisions": [], "investigations": [], "constraints": [],
            "operational_facts": [{
                "command_family": "python",
                "subject": "s",
                "artifact": "a",
                "outcome": "unclear",
                "evidence_span": "e",
            }],
            "supersessions": [],
        })
        result = run_typed_shadow_extraction(_source_item(), provider=provider)
        assert len(result.operational_facts) == 1
        assert result.operational_facts[0].outcome is None
        # Still counts as schema_failure since a divergence occurred.
        assert result.parse_status == "schema_failure"

    def test_empty_string_subject_dropped(self):
        provider = StubProvider({
            "decisions": [{"subject": "", "statement": "s", "evidence_span": "e"}],
            "investigations": [], "constraints": [],
            "operational_facts": [], "supersessions": [],
        })
        result = run_typed_shadow_extraction(_source_item(), provider=provider)
        assert result.decisions == ()

    def test_whitespace_only_statement_dropped(self):
        provider = StubProvider({
            "decisions": [{"subject": "s", "statement": "   ", "evidence_span": "e"}],
            "investigations": [], "constraints": [],
            "operational_facts": [], "supersessions": [],
        })
        result = run_typed_shadow_extraction(_source_item(), provider=provider)
        assert result.decisions == ()

    def test_over_max_string_truncated_not_dropped(self):
        long_statement = "x" * (MAX_STATEMENT_LEN + 500)
        provider = StubProvider({
            "decisions": [{
                "subject": "s",
                "statement": long_statement,
                "evidence_span": "e",
            }],
            "investigations": [], "constraints": [],
            "operational_facts": [], "supersessions": [],
        })
        result = run_typed_shadow_extraction(_source_item(), provider=provider)
        assert len(result.decisions) == 1
        assert len(result.decisions[0].statement) == MAX_STATEMENT_LEN


# --------------------------------------------------------------------------- #
# Never-raises contract                                                       #
# --------------------------------------------------------------------------- #


class TestNeverRaises:
    @pytest.mark.parametrize(
        "message",
        [
            "rate limited",
            "timeout",
            "connection error",
            "auth error",
            "bad request",
            "unknown provider error",
        ],
    )
    def test_llm_provider_error_never_propagates(self, message):
        exc = LLMProviderError(message)
        provider = ErrorProvider(exc)
        result = run_typed_shadow_extraction(_source_item(), provider=provider)
        assert result.parse_status == "llm_error"
        assert result.total_items() == 0
        assert message in (result.parse_error or "")

    def test_unexpected_exception_never_propagates(self):
        provider = ErrorProvider(RuntimeError("something unexpected"))
        result = run_typed_shadow_extraction(_source_item(), provider=provider)
        assert result.parse_status == "llm_error"
        assert "RuntimeError" in (result.parse_error or "")

    def test_keyboard_interrupt_propagates(self):
        # KeyboardInterrupt is NOT caught by BaseException — this is a
        # signal-level interrupt and must propagate. Ensure our contract
        # only catches Exception + LLMProviderError.
        provider = ErrorProvider(KeyboardInterrupt())
        with pytest.raises(KeyboardInterrupt):
            run_typed_shadow_extraction(_source_item(), provider=provider)


# --------------------------------------------------------------------------- #
# Prompt contract                                                             #
# --------------------------------------------------------------------------- #


class TestPromptContract:
    def test_system_prompt_bounded(self):
        from semantic.extraction_typed_shadow import _SYSTEM_PROMPT
        assert len(_SYSTEM_PROMPT.encode("utf-8")) <= MAX_PROMPT_BYTES

    def test_system_prompt_names_all_five_arrays(self):
        from semantic.extraction_typed_shadow import _SYSTEM_PROMPT
        for name in ("decisions", "investigations", "constraints",
                     "operational_facts", "supersessions"):
            assert name in _SYSTEM_PROMPT

    def test_prompt_version_constant_matches_default(self):
        # Default arg equals the module-level constant.
        assert TYPED_SHADOW_PROMPT_VERSION == "typed_shadow_v1"

    def test_user_prompt_truncates_long_content(self):
        from semantic.extraction_typed_shadow import _build_user_prompt
        huge = "x" * (MAX_PROMPT_BYTES * 2)
        prompt = _build_user_prompt(_source_item(content=huge))
        assert len(prompt.encode("utf-8")) <= MAX_PROMPT_BYTES
        assert "[truncated]" in prompt

    def test_combined_prompt_bounded(self):
        from semantic.extraction_typed_shadow import _SYSTEM_PROMPT, _build_user_prompt
        huge = "x" * (MAX_PROMPT_BYTES * 2)
        combined_len = len(_SYSTEM_PROMPT.encode("utf-8")) + len(
            _build_user_prompt(_source_item(content=huge)).encode("utf-8")
        )
        # System + user must fit inside 2×MAX (system alone is under MAX,
        # user is also under MAX after truncation).
        assert combined_len <= 2 * MAX_PROMPT_BYTES


# --------------------------------------------------------------------------- #
# Isolation                                                                   #
# --------------------------------------------------------------------------- #


class TestIsolation:
    def test_module_does_not_import_live_write_paths(self):
        import importlib
        source = importlib.import_module(
            "semantic.extraction_typed_shadow"
        ).__file__
        with open(source, "r", encoding="utf-8") as f:
            text = f.read()
        forbidden_prefixes = (
            "from storage.sqlite import",
            "import storage.sqlite\n",
            "from core.routing",
            "from core.query",
            "from core.service",
            "from semantic.llm_agent_memory",
            "from semantic.agent_conversation_memory",
        )
        for prefix in forbidden_prefixes:
            assert prefix not in text, (
                f"semantic/extraction_typed_shadow.py must not use '{prefix}'"
            )
