from __future__ import annotations

import json
from typing import Any

import httpx

from providers.llm.base import (
    LLMJsonResponse, LLMProviderError, LLMRetryPolicy, ResilientLLMProvider,
    check_model_call_allowed,
)


class OpenAICompatibleLLMProvider(ResilientLLMProvider):
    def __init__(
        self,
        *,
        provider_name: str = "openai",
        model: str,
        base_url: str,
        api_key: str | None,
        timeout_seconds: float,
        retry_policy: LLMRetryPolicy | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        super().__init__(
            provider_name=provider_name,
            provider_kind="openai_compatible",
            model=model,
            retry_policy=retry_policy or LLMRetryPolicy(),
        )
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._client = client or httpx.Client(timeout=timeout_seconds)

    def _perform_request(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        schema_description: str,
    ) -> httpx.Response:
        payload = {
            "model": self._model,
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
        check_model_call_allowed()
        return self._client.post(f"{self._base_url}/chat/completions", json=payload, headers=headers)

    def _extract_text(self, body: dict[str, Any]) -> str:
        message_content = body["choices"][0]["message"]["content"]
        if isinstance(message_content, str):
            return message_content
        if isinstance(message_content, list):
            parts = [item.get("text", "") for item in message_content if isinstance(item, dict)]
            return "\n".join(part for part in parts if part).strip()
        raise ValueError("Unsupported OpenAI-compatible content format")

    def _classify_http_error(self, response: httpx.Response):
        error_kind = super()._classify_http_error(response)
        if response.status_code == 400:
            error_type = _extract_error_type(response)
            if error_type == "rate_limit_exceeded":
                return super()._classify_http_error(httpx.Response(429, headers=response.headers, request=response.request))
        return error_kind

    def _extract_request_id(self, response: httpx.Response) -> str | None:
        return response.headers.get("x-request-id") or response.headers.get("request-id") or None


def _extract_error_type(response: httpx.Response) -> str | None:
    try:
        body = response.json()
    except (ValueError, json.JSONDecodeError):
        return None
    error = body.get("error")
    if not isinstance(error, dict):
        return None
    value = error.get("type")
    return str(value).strip() if value is not None else None
