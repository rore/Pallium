"""Pure native-journey fixture checks; these do not launch Hermes."""

import json

import pytest

from tests.test_hermes_tui_native_e2e import MEMORY_PROMPTS, ScriptedProvider


@pytest.mark.parametrize("stage,expected_id,statement", [
    ("expand", "first", "Quartz lantern remains in vault"),
    ("expand_corrected", "first", "Opal compass stays in archive"),
    ("expand_current", "current", "Cobalt key stays in cabinet"),
])
@pytest.mark.parametrize("variant,accepted", [
    ("nullable", True), ("text", True), ("wrong_id", False),
    ("wrong_payload", False), ("missing_payload", False),
    ("stale_hint", False), ("empty_hint", False),
    ("bool_hint", False), ("list_hint", False), ("number_hint", False),
])
def test_native_memory_expansion_requires_exact_payload_with_nullable_hint(stage, expected_id, statement,
                                                                        variant, accepted):
    provider = ScriptedProvider(memory_enabled=True)
    provider.memory_ids = {"first": "first", "current": "current"}
    value = {"memory_object_id": expected_id, "payload": {"statement": statement}, "match_text": None}
    if variant != "nullable":
        value["match_text"] = statement
    if variant == "wrong_id":
        value["memory_object_id"] = "other"
    elif variant == "wrong_payload":
        value["payload"] = {"statement": "stale"}
    elif variant == "missing_payload":
        value["payload"] = None
    elif variant.endswith("_hint"):
        value["match_text"] = {"stale_hint": "stale", "empty_hint": "", "bool_hint": True,
                               "list_hint": [statement], "number_hint": 7}[variant]
    body = {"tools": [{"function": {"name": "pallium_expand"}}], "messages": [
        {"role": "user", "content": MEMORY_PROMPTS[stage]},
        {"role": "assistant", "tool_calls": [{"id": "expand", "function": {
            "name": "pallium_expand", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "expand", "content": json.dumps(value)},
    ]}
    if accepted:
        assert provider.respond(body) == (f"Completed {stage}.", None)
    else:
        with pytest.raises(AssertionError):
            provider.respond(body)
