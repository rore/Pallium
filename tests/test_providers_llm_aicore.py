"""Tests for the SAP AI Core Anthropic LLM provider.

Covers token exchange, deployment catalog, and the provider itself.
"""

from __future__ import annotations

import json
import time

import httpx
import pytest

from providers.llm.aicore_auth import (
    AICoreAuthError,
    AICoreDeploymentCatalog,
    AICoreDeploymentError,
    AICoreTokenProvider,
)
from providers.llm.aicore_anthropic import AICoreAnthropicLLMProvider
from providers.llm.base import LLMProviderError, LLMRetryPolicy


# ---------------------------------------------------------------------------
# Fixtures & helpers
# ---------------------------------------------------------------------------

EXPECTED_OBJECT = {
    "summary": "Use item event time reservation ordering.",
    "candidate_type": "decision",
    "decision_text": "use item event time reservation ordering",
    "rationale_text": "to avoid missed hold updates during sync delays",
}

TOKEN_RESPONSE = {"access_token": "tok-abc-123", "expires_in": 3600}

DEPLOYMENT_LIST = {
    "resources": [
        {
            "id": "d-deploy-1",
            "status": "RUNNING",
            "details": {
                "resources": {
                    "backendDetails": {
                        "model": {"name": "anthropic--claude-sonnet-latest"}
                    }
                }
            },
        },
        {
            "id": "d-deploy-2",
            "status": "RUNNING",
            "details": {
                "resources": {
                    "backendDetails": {
                        "model": {"name": "anthropic--claude-haiku-latest"}
                    }
                }
            },
        },
        {
            "id": "d-stopped",
            "status": "STOPPED",
            "details": {
                "resources": {
                    "backendDetails": {
                        "model": {"name": "anthropic--claude-opus-latest"}
                    }
                }
            },
        },
    ]
}


def _claude_success_response() -> httpx.Response:
    return httpx.Response(
        200,
        headers={"request-id": "req-aicore-success"},
        json={"content": [{"type": "text", "text": f"```json\n{json.dumps(EXPECTED_OBJECT)}\n```"}]},
    )


def _build_token_provider(
    handler, *, client_id="cid", client_secret="csec", auth_url="https://auth.test"
) -> AICoreTokenProvider:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return AICoreTokenProvider(
        client_id=client_id,
        client_secret=client_secret,
        auth_url=auth_url,
        timeout_seconds=5,
        client=client,
    )


# ---------------------------------------------------------------------------
# AICoreTokenProvider
# ---------------------------------------------------------------------------


class TestAICoreTokenProvider:
    def test_obtains_token_with_basic_auth(self) -> None:
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["auth"] = request.headers.get("authorization")
            captured["url"] = str(request.url)
            return httpx.Response(200, json=TOKEN_RESPONSE)

        provider = _build_token_provider(handler)
        token = provider.get_valid_token()

        assert token == "tok-abc-123"
        assert captured["auth"].startswith("Basic ")
        assert "grant_type=client_credentials" in captured["url"]

    def test_caches_token_across_calls(self) -> None:
        call_count = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            call_count["n"] += 1
            return httpx.Response(200, json=TOKEN_RESPONSE)

        provider = _build_token_provider(handler)
        t1 = provider.get_valid_token()
        t2 = provider.get_valid_token()

        assert t1 == t2
        assert call_count["n"] == 1

    def test_refreshes_after_expiry(self, monkeypatch) -> None:
        clock = {"now": 1000.0}
        monkeypatch.setattr(time, "monotonic", lambda: clock["now"])
        call_count = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            call_count["n"] += 1
            return httpx.Response(200, json={"access_token": f"tok-{call_count['n']}", "expires_in": 120})

        provider = _build_token_provider(handler)
        t1 = provider.get_valid_token()
        assert t1 == "tok-1"

        # Advance past expiry (120s - 60s buffer = 60s effective TTL).
        clock["now"] = 1000.0 + 61
        t2 = provider.get_valid_token()
        assert t2 == "tok-2"
        assert call_count["n"] == 2

    def test_raises_on_auth_failure(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, text="Unauthorized")

        provider = _build_token_provider(handler)
        with pytest.raises(AICoreAuthError, match="401"):
            provider.get_valid_token()

    def test_raises_on_invalid_response(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"oops": "no token"})

        provider = _build_token_provider(handler)
        with pytest.raises(AICoreAuthError, match="Invalid token response"):
            provider.get_valid_token()


# ---------------------------------------------------------------------------
# AICoreDeploymentCatalog
# ---------------------------------------------------------------------------


class TestAICoreDeploymentCatalog:
    def _build(self, handler) -> AICoreDeploymentCatalog:
        token_handler = lambda r: httpx.Response(200, json=TOKEN_RESPONSE)  # noqa: E731
        token_provider = _build_token_provider(token_handler)
        client = httpx.Client(transport=httpx.MockTransport(handler))
        return AICoreDeploymentCatalog(
            base_url="https://aicore.test",
            resource_group="default",
            token_provider=token_provider,
            timeout_seconds=5,
            client=client,
        )

    def test_resolves_running_deployment(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert "/v2/lm/deployments" in str(request.url)
            assert request.headers["ai-resource-group"] == "default"
            return httpx.Response(200, json=DEPLOYMENT_LIST)

        catalog = self._build(handler)
        dep_id = catalog.find_deployment_id("anthropic--claude-sonnet-latest")
        assert dep_id == "d-deploy-1"

    def test_ignores_stopped_deployments(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=DEPLOYMENT_LIST)

        catalog = self._build(handler)
        with pytest.raises(AICoreDeploymentError, match="not found"):
            catalog.find_deployment_id("anthropic--claude-opus-latest")

    def test_raises_for_unknown_model(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=DEPLOYMENT_LIST)

        catalog = self._build(handler)
        with pytest.raises(AICoreDeploymentError, match="not-a-model"):
            catalog.find_deployment_id("not-a-model")

    def test_caches_deployments(self) -> None:
        call_count = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            call_count["n"] += 1
            return httpx.Response(200, json=DEPLOYMENT_LIST)

        catalog = self._build(handler)
        catalog.find_deployment_id("anthropic--claude-sonnet-latest")
        catalog.find_deployment_id("anthropic--claude-haiku-latest")

        assert call_count["n"] == 1  # only one HTTP call for both lookups


# ---------------------------------------------------------------------------
# AICoreAnthropicLLMProvider
# ---------------------------------------------------------------------------


class TestAICoreAnthropicLLMProvider:
    def _build(self, inference_handler) -> AICoreAnthropicLLMProvider:
        token_handler = lambda r: httpx.Response(200, json=TOKEN_RESPONSE)  # noqa: E731
        deploy_handler = lambda r: httpx.Response(200, json=DEPLOYMENT_LIST)  # noqa: E731

        token_provider = _build_token_provider(token_handler)
        deploy_client = httpx.Client(transport=httpx.MockTransport(deploy_handler))
        catalog = AICoreDeploymentCatalog(
            base_url="https://aicore.test",
            resource_group="default",
            token_provider=token_provider,
            timeout_seconds=5,
            client=deploy_client,
        )
        inference_client = httpx.Client(transport=httpx.MockTransport(inference_handler))
        return AICoreAnthropicLLMProvider(
            provider_name="aicore",
            model="anthropic--claude-sonnet-latest",
            base_url="https://aicore.test",
            resource_group="default",
            token_provider=token_provider,
            deployment_catalog=catalog,
            timeout_seconds=5,
            client=inference_client,
            max_tokens=1024,
        )

    def test_sends_correct_request(self) -> None:
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["headers"] = dict(request.headers)
            captured["body"] = json.loads(request.content.decode())
            return _claude_success_response()

        provider = self._build(handler)
        response = provider.generate_json(
            system_prompt="system", user_prompt="user", schema_description="schema"
        )

        # Correct deployment URL.
        assert "/v2/inference/deployments/d-deploy-1/invoke" in captured["url"]
        # Bearer auth from token provider.
        assert captured["headers"]["authorization"] == "Bearer tok-abc-123"
        # AI Core resource group header.
        assert captured["headers"]["ai-resource-group"] == "default"
        # Anthropic message format.
        assert captured["body"]["system"] == "system"
        assert captured["body"]["messages"][0]["role"] == "user"
        assert captured["body"]["max_tokens"] == 1024
        assert captured["body"]["temperature"] == 0

        # Response parsed correctly.
        assert response.parsed_json == EXPECTED_OBJECT
        assert response.metadata.request_id == "req-aicore-success"

    def test_retries_transient_errors(self) -> None:
        attempts = {"count": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            attempts["count"] += 1
            if attempts["count"] == 1:
                return httpx.Response(503, text="Service Unavailable")
            return _claude_success_response()

        provider = self._build(handler)
        response = provider.generate_json(
            system_prompt="s", user_prompt="u", schema_description="d"
        )

        assert attempts["count"] == 2
        assert response.metadata.retry_count == 1
        assert response.parsed_json == EXPECTED_OBJECT

    def test_does_not_retry_auth_errors(self) -> None:
        attempts = {"count": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            attempts["count"] += 1
            return httpx.Response(401, text="Unauthorized")

        provider = self._build(handler)
        with pytest.raises(LLMProviderError):
            provider.generate_json(
                system_prompt="s", user_prompt="u", schema_description="d"
            )

        assert attempts["count"] == 1
