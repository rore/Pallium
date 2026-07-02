"""W4 follow-up — routing-constants wiring for operational_fact.

Verifies that ``operational_fact`` is present in every hardcoded
routing constant that gates retrieval:

- ``STRUCTURED_LAYERS`` — the load-bearing gate. Without membership,
  ``_result_layer`` collapses the type to ``lower_level_memory`` and
  the intent-specific weights are never read.
- ``ROUTING_PREFERRED_LAYERS`` for all four intents.
- ``ROUTING_LAYER_WEIGHTS`` for all four intents.
- ``ROUTING_SAFE_FALLBACK_LAYERS`` for the recall / structured_recall
  intents (where fact-tier surfacing on weak support matters).

Also pins the invariant "registered weights == hardcoded weights":
if a future PR changes ``AgentWorkTracePlugin.register_routing_types``
without updating ``ROUTING_LAYER_WEIGHTS``, retrieval silently ignores
the new registration. This test catches that drift.
"""

from __future__ import annotations

import pytest

from core.type_registry import TypeRegistry
from providers.llm.base import LLMJsonResponse, LLMProvider
from semantic.agent_conversation_memory_routing_constants import (
    ROUTING_LAYER_WEIGHTS,
    ROUTING_PREFERRED_LAYERS,
    ROUTING_SAFE_FALLBACK_LAYERS,
    STRUCTURED_LAYERS,
)
from semantic.agent_work_trace import AgentWorkTracePlugin
from semantic.operational_fact import OPERATIONAL_FACT_TYPE


_INTENTS = ("recall", "structured_recall", "work_resumption", "evidence_trace")


class _StubProvider(LLMProvider):
    def generate_json(self, *, system_prompt, user_prompt, schema_description):
        return LLMJsonResponse(raw_text='{"outcome": null}', parsed_json={"outcome": None})


def _plugin() -> AgentWorkTracePlugin:
    return AgentWorkTracePlugin(provider=_StubProvider())


class TestStructuredLayersMembership:
    def test_operational_fact_in_structured_layers(self):
        assert OPERATIONAL_FACT_TYPE in STRUCTURED_LAYERS, (
            "Without STRUCTURED_LAYERS membership, `_result_layer` "
            "renames every operational_fact candidate to "
            "'lower_level_memory' at scoring time and the "
            "intent-specific weights are never applied."
        )


class TestRoutingPreferredLayers:
    @pytest.mark.parametrize("intent", _INTENTS)
    def test_operational_fact_in_all_intents(self, intent):
        assert OPERATIONAL_FACT_TYPE in ROUTING_PREFERRED_LAYERS[intent], (
            f"missing from ROUTING_PREFERRED_LAYERS[{intent!r}]; "
            f"got {ROUTING_PREFERRED_LAYERS[intent]}"
        )


class TestRoutingLayerWeights:
    @pytest.mark.parametrize("intent", _INTENTS)
    def test_operational_fact_weight_present(self, intent):
        assert OPERATIONAL_FACT_TYPE in ROUTING_LAYER_WEIGHTS[intent]

    def test_weights_match_plugin_registration(self):
        # Invariant guard: plugin's registered weight_by_intent must
        # equal the hardcoded ROUTING_LAYER_WEIGHTS. If a future PR
        # changes one without the other, retrieval silently drifts.
        registry = TypeRegistry()
        plugin = _plugin()
        plugin.register_routing_types(registry)
        registration = registry.get(OPERATIONAL_FACT_TYPE)
        assert registration is not None
        for intent, expected in registration.weight_by_intent.items():
            actual = ROUTING_LAYER_WEIGHTS[intent].get(OPERATIONAL_FACT_TYPE)
            assert actual == expected, (
                f"weight drift on intent={intent!r}: "
                f"plugin_registration={expected}, "
                f"ROUTING_LAYER_WEIGHTS={actual}. "
                "Update both to match."
            )


class TestSafeFallbackLayers:
    def test_operational_fact_in_recall_fallback(self):
        # Recall queries that yield weak support should still be able
        # to surface an operational_fact via fallback rather than
        # collapsing to atomic_fact / note only.
        assert OPERATIONAL_FACT_TYPE in ROUTING_SAFE_FALLBACK_LAYERS["recall"]

    def test_operational_fact_in_structured_recall_fallback(self):
        assert OPERATIONAL_FACT_TYPE in ROUTING_SAFE_FALLBACK_LAYERS[
            "structured_recall"
        ]


class TestAllConstantsInSync:
    """Cross-check: every intent-map must reference operational_fact if
    ANY intent-map does. Catches a partial edit that adds to weights
    but not preferred_layers (or vice versa).
    """

    @pytest.mark.parametrize("intent", _INTENTS)
    def test_preferred_and_weights_agree_per_intent(self, intent):
        in_preferred = OPERATIONAL_FACT_TYPE in ROUTING_PREFERRED_LAYERS[intent]
        in_weights = OPERATIONAL_FACT_TYPE in ROUTING_LAYER_WEIGHTS[intent]
        assert in_preferred == in_weights, (
            f"partial edit on intent={intent!r}: "
            f"preferred_layers has op_fact={in_preferred}, "
            f"weights has op_fact={in_weights}. "
            "Either add to both or remove from both."
        )
