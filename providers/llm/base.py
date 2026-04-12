from __future__ import annotations

import json
import random
import re
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

import httpx


FENCED_JSON_PATTERN = re.compile(r"^```(?:json)?\s*(?P<body>.*?)\s*```$", re.IGNORECASE | re.DOTALL)
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504, 529}
NON_RETRYABLE_STATUS_CODES = {400, 401, 403, 404, 422}


class LLMErrorKind(StrEnum):
    RATE_LIMITED = "rate_limited"
    TRANSIENT_PROVIDER_ERROR = "transient_provider_error"
    TIMEOUT = "timeout"
    CONNECTION_ERROR = "connection_error"
    AUTH_ERROR = "auth_error"
    BAD_REQUEST = "bad_request"
    INVALID_RESPONSE = "invalid_response"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class LLMRetryPolicy:
    max_attempts: int = 3
    base_backoff_ms: int = 250
    max_backoff_ms: int = 3000
    jitter_ratio: float = 0.2
    max_concurrency: int = 4


@dataclass(frozen=True)
class LLMRetryDecision:
    should_retry: bool
    delay_seconds: float = 0.0
    reason: str | None = None


@dataclass(frozen=True)
class LLMCallMetadata:
    provider_name: str
    provider_kind: str
    model: str
    attempt_count: int = 1
    retry_count: int = 0
    final_status_code: int | None = None
    request_id: str | None = None
    error_kind: LLMErrorKind | None = None
    retry_after_seconds: float | None = None
    retry_after_honored: bool = False


class LLMProviderError(RuntimeError):
    def __init__(self, message: str, *, metadata: LLMCallMetadata | None = None, response_text: str | None = None) -> None:
        super().__init__(message)
        self.metadata = metadata or LLMCallMetadata(
            provider_name="unknown",
            provider_kind="unknown",
            model="unknown",
            error_kind=LLMErrorKind.UNKNOWN,
        )
        self.response_text = response_text


@dataclass(frozen=True)
class LLMJsonResponse:
    raw_text: str
    parsed_json: dict[str, Any]
    metadata: LLMCallMetadata | None = None


class LLMProvider(ABC):
    @abstractmethod
    def generate_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        schema_description: str,
    ) -> LLMJsonResponse:
        raise NotImplementedError


class ResilientLLMProvider(LLMProvider, ABC):
    def __init__(
        self,
        *,
        provider_name: str,
        provider_kind: str,
        model: str,
        retry_policy: LLMRetryPolicy,
    ) -> None:
        self._provider_name = provider_name
        self._provider_kind = provider_kind
        self._model = model
        self._retry_policy = retry_policy
        self._semaphore = threading.BoundedSemaphore(value=max(1, retry_policy.max_concurrency))

    def generate_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        schema_description: str,
    ) -> LLMJsonResponse:
        with self._semaphore:
            last_error: LLMProviderError | None = None
            for attempt in range(1, self._retry_policy.max_attempts + 1):
                try:
                    response = self._perform_request(
                        system_prompt=system_prompt,
                        user_prompt=user_prompt,
                        schema_description=schema_description,
                    )
                    if response.status_code >= 400:
                        error = self._build_http_error(response=response, attempt=attempt)
                        decision = self._decide_retry(error.metadata, response=response)
                        if decision.should_retry and attempt < self._retry_policy.max_attempts:
                            self._sleep(decision.delay_seconds)
                            last_error = error
                            continue
                        raise error

                    raw_text = self._extract_text(response.json())
                    parsed = parse_json_object(raw_text)
                    metadata = LLMCallMetadata(
                        provider_name=self._provider_name,
                        provider_kind=self._provider_kind,
                        model=self._model,
                        attempt_count=attempt,
                        retry_count=attempt - 1,
                        final_status_code=response.status_code,
                        request_id=self._extract_request_id(response),
                    )
                    return LLMJsonResponse(raw_text=raw_text, parsed_json=parsed, metadata=metadata)
                except LLMProviderError as exc:
                    last_error = exc
                    raise
                except (ValueError, KeyError, IndexError, TypeError) as exc:
                    metadata = LLMCallMetadata(
                        provider_name=self._provider_name,
                        provider_kind=self._provider_kind,
                        model=self._model,
                        attempt_count=attempt,
                        retry_count=attempt - 1,
                        error_kind=LLMErrorKind.INVALID_RESPONSE,
                    )
                    raise LLMProviderError(
                        f"{self._provider_kind} LLM returned an invalid response",
                        metadata=metadata,
                    ) from exc
                except httpx.TimeoutException as exc:
                    error = self._build_transport_error(exc=exc, attempt=attempt, error_kind=LLMErrorKind.TIMEOUT)
                    decision = self._decide_retry(error.metadata)
                    if decision.should_retry and attempt < self._retry_policy.max_attempts:
                        self._sleep(decision.delay_seconds)
                        last_error = error
                        continue
                    raise error from exc
                except httpx.TransportError as exc:
                    error = self._build_transport_error(exc=exc, attempt=attempt, error_kind=LLMErrorKind.CONNECTION_ERROR)
                    decision = self._decide_retry(error.metadata)
                    if decision.should_retry and attempt < self._retry_policy.max_attempts:
                        self._sleep(decision.delay_seconds)
                        last_error = error
                        continue
                    raise error from exc

            if last_error is not None:
                raise last_error
            raise RuntimeError("LLM provider retry loop exited unexpectedly")

    @abstractmethod
    def _perform_request(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        schema_description: str,
    ) -> httpx.Response:
        raise NotImplementedError

    @abstractmethod
    def _extract_text(self, body: dict[str, Any]) -> str:
        raise NotImplementedError

    def _extract_request_id(self, response: httpx.Response) -> str | None:
        return response.headers.get("x-request-id") or None

    def _classify_http_error(self, response: httpx.Response) -> LLMErrorKind:
        status_code = response.status_code
        if status_code == 429:
            return LLMErrorKind.RATE_LIMITED
        if status_code in {401, 403}:
            return LLMErrorKind.AUTH_ERROR
        if status_code in NON_RETRYABLE_STATUS_CODES:
            return LLMErrorKind.BAD_REQUEST
        if status_code in RETRYABLE_STATUS_CODES:
            return LLMErrorKind.TRANSIENT_PROVIDER_ERROR
        return LLMErrorKind.UNKNOWN

    def _build_http_error(self, *, response: httpx.Response, attempt: int) -> LLMProviderError:
        error_kind = self._classify_http_error(response)
        retry_after_seconds = _parse_retry_after_seconds(response)
        metadata = LLMCallMetadata(
            provider_name=self._provider_name,
            provider_kind=self._provider_kind,
            model=self._model,
            attempt_count=attempt,
            retry_count=attempt - 1,
            final_status_code=response.status_code,
            request_id=self._extract_request_id(response),
            error_kind=error_kind,
            retry_after_seconds=retry_after_seconds,
            retry_after_honored=retry_after_seconds is not None and error_kind in {LLMErrorKind.RATE_LIMITED, LLMErrorKind.TRANSIENT_PROVIDER_ERROR},
        )
        return LLMProviderError(
            f"{self._provider_kind} LLM request failed with HTTP {response.status_code}",
            metadata=metadata,
            response_text=response.text,
        )

    def _build_transport_error(
        self,
        *,
        exc: Exception,
        attempt: int,
        error_kind: LLMErrorKind,
    ) -> LLMProviderError:
        metadata = LLMCallMetadata(
            provider_name=self._provider_name,
            provider_kind=self._provider_kind,
            model=self._model,
            attempt_count=attempt,
            retry_count=attempt - 1,
            error_kind=error_kind,
        )
        return LLMProviderError(
            f"{self._provider_kind} LLM request failed due to {error_kind.value}",
            metadata=metadata,
            response_text=str(exc),
        )

    def _decide_retry(self, metadata: LLMCallMetadata, *, response: httpx.Response | None = None) -> LLMRetryDecision:
        if metadata.error_kind not in {
            LLMErrorKind.RATE_LIMITED,
            LLMErrorKind.TRANSIENT_PROVIDER_ERROR,
            LLMErrorKind.TIMEOUT,
            LLMErrorKind.CONNECTION_ERROR,
        }:
            return LLMRetryDecision(should_retry=False, reason="non_retryable")

        if metadata.retry_after_seconds is not None:
            return LLMRetryDecision(
                should_retry=True,
                delay_seconds=metadata.retry_after_seconds,
                reason="retry_after",
            )

        delay_seconds = compute_backoff_seconds(
            attempt=metadata.attempt_count,
            policy=self._retry_policy,
        )
        return LLMRetryDecision(should_retry=True, delay_seconds=delay_seconds, reason="backoff")

    def _sleep(self, delay_seconds: float) -> None:
        time.sleep(delay_seconds)



def parse_json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if not cleaned:
        raise ValueError("LLM response was empty")

    fenced_match = FENCED_JSON_PATTERN.match(cleaned)
    if fenced_match:
        cleaned = fenced_match.group("body").strip()

    for candidate in (cleaned, _extract_braced_payload(cleaned)):
        if not candidate:
            continue
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if not isinstance(parsed, dict):
            raise ValueError("LLM response JSON must be an object")
        return parsed

    raise ValueError("Could not parse a JSON object from LLM response")


def compute_backoff_seconds(*, attempt: int, policy: LLMRetryPolicy) -> float:
    base_seconds = policy.base_backoff_ms / 1000.0
    max_seconds = policy.max_backoff_ms / 1000.0
    exponential = min(max_seconds, base_seconds * (2 ** max(0, attempt - 1)))
    jitter = exponential * policy.jitter_ratio * random.random()
    return min(max_seconds, exponential + jitter)


MAX_RETRY_AFTER_SECONDS = 60.0


def _parse_retry_after_seconds(response: httpx.Response) -> float | None:
    retry_after = response.headers.get("retry-after")
    if not retry_after:
        return None
    try:
        return min(MAX_RETRY_AFTER_SECONDS, max(0.0, float(retry_after)))
    except ValueError:
        return None


def _extract_braced_payload(text: str) -> str | None:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    return text[start : end + 1]
