from __future__ import annotations

import json

import httpx

from providers.llm.anthropic_claude import AnthropicClaudeLLMProvider
from providers.llm.openai_compatible import OpenAICompatibleLLMProvider


EXPECTED_OBJECT = {
    "summary": "Use event timestamp watermarking.",
    "candidate_type": "decision",
    "decision_text": "use event timestamp watermarking",
    "rationale_text": "to avoid skipped records during lag",
}


def test_openai_compatible_provider_parses_json_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path.endswith("/chat/completions")
        payload = json.loads(request.content.decode("utf-8"))
        assert payload["model"] == "gpt-test"
        assert payload["messages"][0]["role"] == "system"
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(EXPECTED_OBJECT),
                        }
                    }
                ]
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = OpenAICompatibleLLMProvider(
        model="gpt-test",
        base_url="https://example.test/v1",
        api_key="secret",
        timeout_seconds=5,
        client=client,
    )

    response = provider.generate_json(
        system_prompt="system",
        user_prompt="user",
        schema_description="schema",
    )

    assert response.parsed_json == EXPECTED_OBJECT
    assert json.loads(response.raw_text) == EXPECTED_OBJECT


def test_anthropic_claude_provider_parses_json_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path.endswith("/messages")
        payload = json.loads(request.content.decode("utf-8"))
        assert payload["model"] == "claude-test"
        assert payload["system"] == "system"
        assert request.headers["anthropic-version"] == "2023-06-01"
        return httpx.Response(
            200,
            json={
                "content": [
                    {
                        "type": "text",
                        "text": f"```json\n{json.dumps(EXPECTED_OBJECT)}\n```",
                    }
                ]
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = AnthropicClaudeLLMProvider(
        model="claude-test",
        base_url="https://example.test/v1",
        api_key="secret",
        timeout_seconds=5,
        client=client,
    )

    response = provider.generate_json(
        system_prompt="system",
        user_prompt="user",
        schema_description="schema",
    )

    assert response.parsed_json == EXPECTED_OBJECT
    assert EXPECTED_OBJECT["decision_text"] in response.raw_text
