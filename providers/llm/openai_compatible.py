from __future__ import annotations

from typing import Any

import httpx

from providers.llm.base import LLMJsonResponse, LLMProvider, LLMProviderError, parse_json_object


class OpenAICompatibleLLMProvider(LLMProvider):
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
            "temperature": 0,
            "messages": [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": f"{user_prompt}\n\nReturn exactly one JSON object matching this schema:\n{schema_description}",
                },
            ],
        }
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        try:
            response = self._client.post(f"{self._base_url}/chat/completions", json=payload, headers=headers)
            response.raise_for_status()
            body = response.json()
            raw_text = _extract_openai_content(body)
            return LLMJsonResponse(raw_text=raw_text, parsed_json=parse_json_object(raw_text))
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as exc:
            raise LLMProviderError("OpenAI-compatible LLM request failed") from exc


def _extract_openai_content(body: dict[str, Any]) -> str:
    message_content = body["choices"][0]["message"]["content"]
    if isinstance(message_content, str):
        return message_content
    if isinstance(message_content, list):
        parts = [item.get("text", "") for item in message_content if isinstance(item, dict)]
        return "\n".join(part for part in parts if part).strip()
    raise ValueError("Unsupported OpenAI-compatible content format")
