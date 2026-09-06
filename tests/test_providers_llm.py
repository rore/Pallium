from __future__ import annotations

import json
import threading
import time

import httpx
import pytest

from providers.llm.anthropic_claude import AnthropicClaudeLLMProvider
from providers.llm.base import LLMErrorKind, LLMProviderError, LLMRetryPolicy
from providers.llm.openai_compatible import OpenAICompatibleLLMProvider


EXPECTED_OBJECT = {
    "summary": "Use item event time reservation ordering.",
    "candidate_type": "decision",
    "decision_text": "use item event time reservation ordering",
    "rationale_text": "to avoid missed hold updates during sync delays",
}


def _openai_success_response() -> httpx.Response:
    return httpx.Response(
        200,
        headers={"x-request-id": "req-openai-success"},
        json={"choices": [{"message": {"content": json.dumps(EXPECTED_OBJECT)}}]},
    )


def _claude_success_response() -> httpx.Response:
    return httpx.Response(
        200,
        headers={"request-id": "req-claude-success"},
        json={"content": [{"type": "text", "text": f"```json\n{json.dumps(EXPECTED_OBJECT)}\n```"}]},
    )


def test_openai_compatible_provider_parses_json_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path.endswith("/chat/completions")
        payload = json.loads(request.content.decode("utf-8"))
        assert payload["model"] == "gpt-test"
        assert payload["messages"][0]["role"] == "system"
        return _openai_success_response()

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = OpenAICompatibleLLMProvider(
        provider_name="openai",
        model="gpt-test",
        base_url="https://example.test/v1",
        api_key="secret",
        timeout_seconds=5,
        client=client,
    )

    response = provider.generate_json(system_prompt="system", user_prompt="user", schema_description="schema")

    assert response.parsed_json == EXPECTED_OBJECT
    assert json.loads(response.raw_text) == EXPECTED_OBJECT
    assert response.metadata is not None
    assert response.metadata.request_id == "req-openai-success"
    assert response.metadata.retry_count == 0


def test_anthropic_claude_provider_parses_json_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path.endswith("/messages")
        payload = json.loads(request.content.decode("utf-8"))
        assert payload["model"] == "claude-test"
        assert payload["system"] == "system"
        assert request.headers["anthropic-version"] == "2023-06-01"
        return _claude_success_response()

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = AnthropicClaudeLLMProvider(
        provider_name="anthropic",
        model="claude-test",
        base_url="https://example.test/v1",
        api_key="secret",
        timeout_seconds=5,
        client=client,
    )

    response = provider.generate_json(system_prompt="system", user_prompt="user", schema_description="schema")

    assert response.parsed_json == EXPECTED_OBJECT
    assert EXPECTED_OBJECT["decision_text"] in response.raw_text
    assert response.metadata is not None
    assert response.metadata.request_id == "req-claude-success"


@pytest.mark.parametrize(
    ("provider_factory", "status_code"),
    [
        ("openai", 429),
        ("openai", 503),
        ("anthropic", 429),
        ("anthropic", 503),
    ],
)
def test_provider_retries_transient_http_failures(provider_factory: str, status_code: int) -> None:
    attempts = {"count": 0}

    def handler(_: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        if attempts["count"] == 1:
            headers = {"retry-after": "0", "x-request-id": "req-first", "request-id": "req-first"}
            return httpx.Response(status_code, headers=headers, json={"error": {"type": "server_error"}})
        return _openai_success_response() if provider_factory == "openai" else _claude_success_response()

    client = httpx.Client(transport=httpx.MockTransport(handler))
    policy = LLMRetryPolicy(max_attempts=3, base_backoff_ms=1, max_backoff_ms=1, jitter_ratio=0.0, max_concurrency=2)
    provider = _build_provider(provider_factory, client=client, retry_policy=policy)

    response = provider.generate_json(system_prompt="system", user_prompt="user", schema_description="schema")

    assert attempts["count"] == 2
    assert response.metadata is not None
    assert response.metadata.attempt_count == 2
    assert response.metadata.retry_count == 1


@pytest.mark.parametrize("provider_factory", ["openai", "anthropic"])
def test_provider_retries_timeout_then_succeeds(provider_factory: str) -> None:
    attempts = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise httpx.ReadTimeout("timed out", request=request)
        return _openai_success_response() if provider_factory == "openai" else _claude_success_response()

    client = httpx.Client(transport=httpx.MockTransport(handler))
    policy = LLMRetryPolicy(max_attempts=3, base_backoff_ms=1, max_backoff_ms=1, jitter_ratio=0.0, max_concurrency=2)
    provider = _build_provider(provider_factory, client=client, retry_policy=policy)

    response = provider.generate_json(system_prompt="system", user_prompt="user", schema_description="schema")

    assert attempts["count"] == 2
    assert response.metadata is not None
    assert response.metadata.retry_count == 1


@pytest.mark.parametrize("provider_factory", ["openai", "anthropic"])
def test_provider_retries_connection_error_then_succeeds(provider_factory: str) -> None:
    attempts = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise httpx.ConnectError("connect failed", request=request)
        return _openai_success_response() if provider_factory == "openai" else _claude_success_response()

    client = httpx.Client(transport=httpx.MockTransport(handler))
    policy = LLMRetryPolicy(max_attempts=3, base_backoff_ms=1, max_backoff_ms=1, jitter_ratio=0.0, max_concurrency=2)
    provider = _build_provider(provider_factory, client=client, retry_policy=policy)

    response = provider.generate_json(system_prompt="system", user_prompt="user", schema_description="schema")

    assert attempts["count"] == 2
    assert response.metadata is not None
    assert response.metadata.retry_count == 1


@pytest.mark.parametrize("provider_factory", ["openai", "anthropic"])
def test_provider_honors_retry_after(monkeypatch: pytest.MonkeyPatch, provider_factory: str) -> None:
    attempts = {"count": 0}
    delays: list[float] = []

    def handler(_: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        if attempts["count"] == 1:
            headers = {"retry-after": "0.25", "x-request-id": "req-first", "request-id": "req-first"}
            return httpx.Response(429, headers=headers, json={"error": {"type": "rate_limit_exceeded"}})
        return _openai_success_response() if provider_factory == "openai" else _claude_success_response()

    monkeypatch.setattr("providers.llm.base.time.sleep", lambda delay: delays.append(delay))
    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = _build_provider(provider_factory, client=client)

    response = provider.generate_json(system_prompt="system", user_prompt="user", schema_description="schema")

    assert attempts["count"] == 2
    assert delays == [0.25]
    assert response.metadata is not None
    assert response.metadata.retry_count == 1


@pytest.mark.parametrize("provider_factory", ["openai", "anthropic"])
def test_provider_does_not_retry_non_retryable_http_errors(provider_factory: str) -> None:
    attempts = {"count": 0}

    def handler(_: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        return httpx.Response(401, headers={"x-request-id": "req-auth", "request-id": "req-auth"}, json={"error": {"type": "auth_error"}})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = _build_provider(provider_factory, client=client)

    with pytest.raises(LLMProviderError) as exc_info:
        provider.generate_json(system_prompt="system", user_prompt="user", schema_description="schema")

    assert attempts["count"] == 1
    assert exc_info.value.metadata.error_kind == LLMErrorKind.AUTH_ERROR
    assert exc_info.value.metadata.retry_count == 0


@pytest.mark.parametrize("provider_factory", ["openai", "anthropic"])
def test_provider_does_not_retry_invalid_success_response(provider_factory: str) -> None:
    attempts = {"count": 0}

    def handler(_: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        if provider_factory == "openai":
            return httpx.Response(200, json={"choices": [{"message": {"content": "not-json"}}]})
        return httpx.Response(200, json={"content": [{"type": "text", "text": "not-json"}]})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = _build_provider(provider_factory, client=client)

    with pytest.raises(LLMProviderError) as exc_info:
        provider.generate_json(system_prompt="system", user_prompt="user", schema_description="schema")

    assert attempts["count"] == 1
    assert exc_info.value.metadata.error_kind == LLMErrorKind.INVALID_RESPONSE


def test_provider_concurrency_limiter_bounds_parallel_calls() -> None:
    state = {"active": 0, "max_active": 0}
    lock = threading.Lock()

    def handler(_: httpx.Request) -> httpx.Response:
        with lock:
            state["active"] += 1
            state["max_active"] = max(state["max_active"], state["active"])
        time.sleep(0.05)
        with lock:
            state["active"] -= 1
        return _openai_success_response()

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = OpenAICompatibleLLMProvider(
        provider_name="openai",
        model="gpt-test",
        base_url="https://example.test/v1",
        api_key="secret",
        timeout_seconds=5,
        retry_policy=LLMRetryPolicy(max_attempts=3, base_backoff_ms=1, max_backoff_ms=1, jitter_ratio=0.0, max_concurrency=2),
        client=client,
    )

    errors: list[Exception] = []

    def worker() -> None:
        try:
            provider.generate_json(system_prompt="system", user_prompt="user", schema_description="schema")
        except Exception as exc:  # pragma: no cover - defensive
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors
    assert state["max_active"] <= 2


def _build_provider(provider_kind: str, *, client: httpx.Client, retry_policy: LLMRetryPolicy | None = None):
    policy = retry_policy or LLMRetryPolicy(max_attempts=3, base_backoff_ms=1, max_backoff_ms=1, jitter_ratio=0.0, max_concurrency=2)
    if provider_kind == "openai":
        return OpenAICompatibleLLMProvider(
            provider_name="openai",
            model="gpt-test",
            base_url="https://example.test/v1",
            api_key="secret",
            timeout_seconds=5,
            retry_policy=policy,
            client=client,
        )
    return AnthropicClaudeLLMProvider(
        provider_name="anthropic",
        model="claude-test",
        base_url="https://example.test/v1",
        api_key="secret",
        timeout_seconds=5,
        retry_policy=policy,
        client=client,
    )


def test_anthropic_native_auth_sends_xapikey_header() -> None:
    captured_headers: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured_headers.update(dict(request.headers))
        return _claude_success_response()

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = AnthropicClaudeLLMProvider(
        model="claude-test",
        base_url="https://example.test/v1",
        api_key="my-secret-key",
        timeout_seconds=5,
        client=client,
        auth_style="native",
    )

    provider.generate_json(system_prompt="system", user_prompt="user", schema_description="schema")

    assert captured_headers.get("x-api-key") == "my-secret-key"
    assert "authorization" not in captured_headers


def test_anthropic_bearer_auth_sends_authorization_header() -> None:
    captured_headers: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured_headers.update(dict(request.headers))
        return _claude_success_response()

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = AnthropicClaudeLLMProvider(
        model="claude-test",
        base_url="https://example.test/v1",
        api_key="my-secret-key",
        timeout_seconds=5,
        client=client,
        auth_style="bearer",
    )

    provider.generate_json(system_prompt="system", user_prompt="user", schema_description="schema")

    assert captured_headers.get("authorization") == "Bearer my-secret-key"
    assert "x-api-key" not in captured_headers


def test_anthropic_default_auth_style_is_native() -> None:
    captured_headers: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured_headers.update(dict(request.headers))
        return _claude_success_response()

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = AnthropicClaudeLLMProvider(
        model="claude-test",
        base_url="https://example.test/v1",
        api_key="my-key",
        timeout_seconds=5,
        client=client,
    )

    provider.generate_json(system_prompt="system", user_prompt="user", schema_description="schema")

    assert captured_headers.get("x-api-key") == "my-key"
    assert "authorization" not in captured_headers


def test_retry_checks_model_call_guard_before_next_request() -> None:
    from providers.llm.base import ModelCallCancelledError, model_call_guard

    calls = 0
    allowed = True

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls, allowed
        calls += 1
        allowed = False
        return httpx.Response(500, json={"error": "retryable"})

    provider = OpenAICompatibleLLMProvider(
        provider_name="openai", model="gpt-test", base_url="https://example.test/v1",
        api_key="secret", timeout_seconds=5,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        retry_policy=LLMRetryPolicy(max_attempts=2, base_backoff_ms=0, max_backoff_ms=0, jitter_ratio=0),
    )

    with model_call_guard(lambda: allowed):
        with pytest.raises(ModelCallCancelledError):
            provider.generate_json(system_prompt="s", user_prompt="u", schema_description="d")
    assert calls == 1
