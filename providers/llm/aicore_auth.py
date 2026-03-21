"""SAP AI Core authentication and deployment catalog.

Handles OAuth2 client-credentials token exchange against xsuaa and
deployment-ID resolution from the AI Core /v2/lm/deployments endpoint.
"""

from __future__ import annotations

import base64
import threading
import time
from dataclasses import dataclass

import httpx


_TOKEN_BUFFER_SECONDS = 60
_DEPLOYMENT_CACHE_TTL_SECONDS = 300  # 5 minutes


class AICoreAuthError(RuntimeError):
    """Raised when AI Core token acquisition fails."""


class AICoreDeploymentError(RuntimeError):
    """Raised when a model cannot be resolved to a running deployment."""


class AICoreTokenProvider:
    """Acquires and caches OAuth2 access tokens for SAP AI Core.

    Token exchange uses the standard client-credentials grant against the
    xsuaa endpoint provided by the AI Core service key.
    """

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        auth_url: str,
        timeout_seconds: float = 30.0,
        client: httpx.Client | None = None,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._auth_url = auth_url.rstrip("/")
        self._client = client or httpx.Client(timeout=timeout_seconds)
        self._lock = threading.Lock()
        self._cached_token: str | None = None
        self._expires_at: float = 0.0

    def get_valid_token(self) -> str:
        """Return a valid access token, refreshing if needed."""
        now = time.monotonic()
        if self._cached_token and now < self._expires_at:
            return self._cached_token
        with self._lock:
            # Double-check after acquiring lock.
            now = time.monotonic()
            if self._cached_token and now < self._expires_at:
                return self._cached_token
            return self._refresh(now)

    def _refresh(self, now: float) -> str:
        credentials = base64.b64encode(
            f"{self._client_id}:{self._client_secret}".encode()
        ).decode()
        try:
            response = self._client.post(
                f"{self._auth_url}/oauth/token",
                params={"grant_type": "client_credentials"},
                headers={
                    "Authorization": f"Basic {credentials}",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise AICoreAuthError(
                f"Token request failed ({exc.response.status_code}): {exc.response.text}"
            ) from exc
        except httpx.TransportError as exc:
            raise AICoreAuthError(f"Token request failed: {exc}") from exc

        data = response.json()
        access_token = data.get("access_token")
        expires_in = data.get("expires_in")
        if not access_token or not expires_in:
            raise AICoreAuthError(
                f"Invalid token response: {data!r}"
            )

        self._cached_token = access_token
        self._expires_at = now + max(int(expires_in) - _TOKEN_BUFFER_SECONDS, 10)
        return access_token


@dataclass(frozen=True)
class _CachedDeployment:
    deployment_id: str
    model_name: str


class AICoreDeploymentCatalog:
    """Resolves model names to running AI Core deployment IDs.

    Caches the deployment list for 5 minutes to avoid hitting the
    /v2/lm/deployments endpoint on every LLM call.
    """

    def __init__(
        self,
        *,
        base_url: str,
        resource_group: str,
        token_provider: AICoreTokenProvider,
        timeout_seconds: float = 30.0,
        client: httpx.Client | None = None,
        cache_ttl_seconds: float = _DEPLOYMENT_CACHE_TTL_SECONDS,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._resource_group = resource_group
        self._token_provider = token_provider
        self._client = client or httpx.Client(timeout=timeout_seconds)
        self._cache_ttl = cache_ttl_seconds
        self._lock = threading.Lock()
        self._cached: list[_CachedDeployment] = []
        self._cached_at: float = 0.0

    def find_deployment_id(self, model_name: str) -> str:
        """Return the deployment ID for *model_name*, or raise."""
        deployments = self._get_deployments()
        for dep in deployments:
            if dep.model_name == model_name:
                return dep.deployment_id
        available = [d.model_name for d in deployments]
        raise AICoreDeploymentError(
            f"Model '{model_name}' not found in running deployments. "
            f"Available: {available}"
        )

    def _get_deployments(self) -> list[_CachedDeployment]:
        now = time.monotonic()
        if self._cached and (now - self._cached_at) < self._cache_ttl:
            return self._cached
        with self._lock:
            now = time.monotonic()
            if self._cached and (now - self._cached_at) < self._cache_ttl:
                return self._cached
            return self._fetch(now)

    def _fetch(self, now: float) -> list[_CachedDeployment]:
        token = self._token_provider.get_valid_token()
        response = self._client.get(
            f"{self._base_url}/v2/lm/deployments",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "AI-Resource-Group": self._resource_group,
            },
        )
        response.raise_for_status()
        data = response.json()
        deployments: list[_CachedDeployment] = []
        for resource in data.get("resources", []):
            if resource.get("status") != "RUNNING":
                continue
            model = (
                resource.get("details", {})
                .get("resources", {})
                .get("backendDetails", {})
                .get("model", {})
                .get("name")
            )
            dep_id = resource.get("id")
            if model and dep_id:
                deployments.append(_CachedDeployment(deployment_id=dep_id, model_name=model))
        self._cached = deployments
        self._cached_at = now
        return deployments
