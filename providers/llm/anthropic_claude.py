from __future__ import annotations

from typing import Any

import httpx

from providers.llm.base import LLMJsonResponse, LLMProvider, LLMProviderError, parse_json_object


ANTHROPIC_VERSION = "2023-06-01"


class AnthropicClaudeLLMProvider(LLMProvider):
    def __init__(
        self,
        *,
        model: str,
        base_url: str,
        api_key: str | None,
        timeout_seconds: float,
        client: httpx.Client | None = None,
    ) -> None:
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._client = client or httpx.Client(timeout=timeout_seconds)

    def generate_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        schema_description: str,
    ) -> LLMJsonResponse:
        payload = {
            "model": self._model,
            "system": system_prompt,
            "messages": [
                {
                    "role": "user",
                    "content": f"{user_prompt}\n\nReturn exactly one JSON object matching this schema:\n{schema_description}",
                }
            ],
            "max_tokens": 512,
            "temperature": 0,
        }
        headers = {
            "Content-Type": "application/json",
            "anthropic-version": ANTHROPIC_VERSION,
        }
        if self._api_key:
            headers["x-api-key"] = self._api_key

        try:
            response = self._client.post(f"{self._base_url}/messages", json=payload, headers=headers)
            response.raise_for_status()
            body = response.json()
            raw_text = _extract_claude_content(body)
            return LLMJsonResponse(raw_text=raw_text, parsed_json=parse_json_object(raw_text))
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as exc:
            raise LLMProviderError("Anthropic Claude LLM request failed") from exc


def _extract_claude_content(body: dict[str, Any]) -> str:
    content_blocks = body["content"]
    if not isinstance(content_blocks, list):
        raise ValueError("Unsupported Claude content format")
    parts = [block.get("text", "") for block in content_blocks if isinstance(block, dict)]
    combined = "\n".join(part for part in parts if part).strip()
    if not combined:
        raise ValueError("Claude content blocks did not include text")
    return combined
