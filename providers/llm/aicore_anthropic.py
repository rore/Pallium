"""SAP AI Core Anthropic LLM provider.

Calls Claude models through SAP AI Core's Bedrock-compatible inference
endpoint, using OAuth2 client-credentials for authentication and
deployment-catalog lookup for model→deployment resolution.
"""

from __future__ import annotations

from typing import Any

import httpx

from providers.llm.aicore_auth import AICoreDeploymentCatalog, AICoreTokenProvider
from providers.llm.base import LLMRetryPolicy, ResilientLLMProvider


class AICoreAnthropicLLMProvider(ResilientLLMProvider):
    """Anthropic Claude via SAP AI Core (Bedrock invoke endpoint)."""

    def __init__(
        self,
        *,
        provider_name: str = "aicore_anthropic",
        model: str,
        base_url: str,
        resource_group: str,
        token_provider: AICoreTokenProvider,
        deployment_catalog: AICoreDeploymentCatalog,
        timeout_seconds: float = 60.0,
        retry_policy: LLMRetryPolicy | None = None,
        client: httpx.Client | None = None,
        max_tokens: int = 1024,
    ) -> None:
        super().__init__(
            provider_name=provider_name,
            provider_kind="aicore_anthropic",
            model=model,
            retry_policy=retry_policy or LLMRetryPolicy(),
        )
        self._base_url = base_url.rstrip("/")
        self._resource_group = resource_group
        self._token_provider = token_provider
        self._deployment_catalog = deployment_catalog
        self._max_tokens = max_tokens
        self._client = client or httpx.Client(timeout=timeout_seconds)

    def _perform_request(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        schema_description: str,
    ) -> httpx.Response:
        token = self._token_provider.get_valid_token()
        deployment_id = self._deployment_catalog.find_deployment_id(self._model)

        payload = {
            "anthropic_version": "bedrock-2023-05-31",
            "model": self._model,
            "system": system_prompt,
            "messages": [
                {
                    "role": "user",
                    "content": f"{user_prompt}\n\nReturn exactly one JSON object matching this schema:\n{schema_description}",
                }
            ],
            "max_tokens": self._max_tokens,
            "temperature": 0,
        }
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "AI-Resource-Group": self._resource_group,
        }
        url = f"{self._base_url}/v2/inference/deployments/{deployment_id}/invoke"
        return self._client.post(url, json=payload, headers=headers)

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
        # Anthropic overload → treat as transient.
        if response.status_code == 529:
            return super()._classify_http_error(
                httpx.Response(503, headers=response.headers, request=response.request)
            )
        return super()._classify_http_error(response)
