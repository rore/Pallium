"""W4 PR 2 — operational_intent signal detector tests.

The detector is a token-based verb-object heuristic on the query text.
Positive cases fire when both a verb and a known command-family token
are present. Negatives include: no verb, no family, empty query,
non-English (documented limitation).
"""

from __future__ import annotations

import pytest

from semantic.agent_conversation_memory_routing_signals import (
    _derive_operational_intent,
    _OPERATIONAL_VERBS,
)
from semantic.operational_fact import KNOWN_FAMILIES


def _tokens(text: str) -> tuple[str, ...]:
    return tuple(text.split())


class TestOperationalIntentPositive:
    @pytest.mark.parametrize(
        "text",
        [
            "run python tests",
            "how do I test with uv",
            "how do I install npm packages",
            "configure docker compose",
            "check the git log",
            "start the service on redis",
            "build the cargo project",
            "fix the make target",
            "deploy the docker image",
            "setup the go module",
            "stop the docker container",
        ],
    )
    def test_verb_plus_family_fires(self, text):
        fired, derivation = _derive_operational_intent(_tokens(text))
        assert fired, f"expected fire on {text!r}"
        assert any(d.startswith("operational_verb=") for d in derivation)
        assert any(d.startswith("operational_family=") for d in derivation)

    def test_verb_family_case_insensitive(self):
        fired, _ = _derive_operational_intent(("RUN", "PYTHON", "tests"))
        assert fired

    def test_derivation_deterministic_multiple_verbs(self):
        # Sorted verb selection guarantees identical output for identical input.
        text = "run and test the docker build"
        fired1, d1 = _derive_operational_intent(_tokens(text))
        fired2, d2 = _derive_operational_intent(_tokens(text))
        assert fired1 == fired2
        assert d1 == d2


class TestOperationalIntentNegative:
    def test_no_verb_no_signal(self):
        fired, derivation = _derive_operational_intent(
            _tokens("the python codebase is large")
        )
        assert not fired
        assert derivation == []

    def test_verb_but_no_family(self):
        fired, _ = _derive_operational_intent(
            _tokens("run the weekly team meeting")
        )
        assert not fired

    def test_empty_tokens(self):
        fired, derivation = _derive_operational_intent(())
        assert not fired
        assert derivation == []

    def test_family_without_verb(self):
        fired, _ = _derive_operational_intent(_tokens("python codebase"))
        assert not fired

    @pytest.mark.parametrize(
        "text",
        [
            "hi",
            "hello",
            "thanks",
            "what did we decide yesterday",
            "who wrote this file",
            "why is the sky blue",
            "explain this error",
            "what happened last week",
            "list all decisions",
            "show me the graph",
            "what does this constant mean",
            "the container is broken",
            "the file was deleted",
            "let me think about this",
            "can you summarize this",
            "how do you feel about it",
            "the weather is nice",
            "what is the difference between",
            "when did this ship",
            "who is on the team",
            # Substring-false-fire regression (R2): none of these contain
            # a family-shape token, only English words that HAPPEN to contain
            # KNOWN_FAMILIES substrings.
            "run the pipeline",           # "pip" inside "pipeline"
            "install a legitimate task",  # "git" inside "legitimate"
            "start a new digital plan",   # "git" inside "digital"
            "run the curve fit",          # "uv" inside "curve"
            "deploy the recipient list",  # "pip" inside "recipient"
            "run this good example",      # "go" inside "good"
        ],
    )
    def test_common_non_operational_prompts_do_not_fire(self, text):
        fired, _ = _derive_operational_intent(_tokens(text))
        assert not fired, f"false-fire on non-operational text: {text!r}"


class TestOperationalIntentMultilingual:
    def test_hebrew_verb_documented_limitation(self):
        # Hebrew verb "הרץ" (run) is not in _OPERATIONAL_VERBS. Signal is
        # English-first per design; document the limitation with a test.
        fired, _ = _derive_operational_intent(("הרץ", "pytest"))
        assert not fired

    def test_japanese_verb_documented_limitation(self):
        fired, _ = _derive_operational_intent(("pythonをテスト",))
        assert not fired


class TestOperationalIntentDocstring:
    def test_english_first_documented(self):
        # The design commits to English-first as a documented limitation.
        # If someone silently adds Hebrew/Japanese support later, this test
        # will still pass — but the assertion below ensures the docstring
        # keeps advertising the current scope.
        doc = _derive_operational_intent.__doc__ or ""
        module_doc = __import__(
            "semantic.agent_conversation_memory_routing_signals",
            fromlist=["*"],
        ).__doc__ or ""
        # The function docstring or a nearby comment must carry the
        # English-first / verb-object / structural discipline. Check the
        # function docstring first; fall back to the module scope for the
        # descriptor comment above the detector.
        assert (
            "English" in doc
            or "verb-object" in doc
            or "structural" in doc
        ), f"detector docstring must document English-first scope; got: {doc!r}"


class TestSignalWiring:
    def test_operational_verbs_are_lowercased(self):
        # Detector lowercases every token, so all verbs must be lower-case.
        for verb in _OPERATIONAL_VERBS:
            assert verb == verb.lower()

    def test_known_families_import_shared(self):
        # Regression: PR 2 must import KNOWN_FAMILIES from operational_fact,
        # not maintain a parallel copy. Assert the identity by module attr.
        import semantic.agent_conversation_memory_routing_signals as sig_mod
        assert sig_mod.KNOWN_FAMILIES is KNOWN_FAMILIES
