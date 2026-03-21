from __future__ import annotations

from typing import Any

import httpx

from providers.llm.base import LLMRetryPolicy, ResilientLLMProvider


ANTHROPIC_VERSION = "2023-06-01"


class AnthropicClaudeLLMProvider(ResilientLLMProvider):
    def __init__(
        self,
        *,
        provider_name: str = "anthropic",
        model: str,
        base_url: str,
        api_key: str | None,
        timeout_seconds: float,
        retry_policy: LLMRetryPolicy | None = None,
        client: httpx.Client | None = None,
        auth_style: str = "native",
    ) -> None:
        super().__init__(
            provider_name=provider_name,
            provider_kind="anthropic_claude",
            model=model,
            retry_policy=retry_policy or LLMRetryPolicy(),
        )
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._auth_style = auth_style
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
            if self._auth_style == "bearer":
                headers["Authorization"] = f"Bearer {self._api_key}"
            else:
                headers["x-api-key"] = self._api_key
        return self._client.post(f"{self._base_url}/messages", json=payload, headers=headers)

    def _extract_text(self, body: dict[str, Any]) -> str:
        content_blocks = body["content"]
        if not isinstance(content_blocks, list):
            raise ValueError("Unsupported Claude content format")
        parts = [block.get("text", "") for block in content_blocks if isinstance(block, dict)]
        combined = "\n".join(part for part in parts if part).strip()
        if not combined:
            raise ValueError("Claude content blocks did not include text")
        return combined

    def _extract_request_id(self, response: httpx.Response) -> str | None:
        return response.headers.get("request-id") or response.headers.get("x-request-id") or None

    def _classify_http_error(self, response: httpx.Response):
        if response.status_code == 529:
            return super()._classify_http_error(httpx.Response(503, headers=response.headers, request=response.request))
        return super()._classify_http_error(response)
