from __future__ import annotations

from typing import Any

import httpx


class HarnessHttpError(RuntimeError):
    def __init__(self, path: str, status_code: int, body: str) -> None:
        super().__init__(f"HTTP {status_code} from {path}")
        self.path = path
        self.status_code = status_code
        self.body = body


class HarnessHttpClient:
    def __init__(self, *, base_url: str, client: httpx.Client | None = None, timeout_seconds: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self._client = client or httpx.Client(base_url=self.base_url, timeout=timeout_seconds)

    def create_item(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post_json("/items", payload)

    def query(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post_json("/query", payload)

    def query_debug(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post_json("/query/debug", payload)

    def close(self) -> None:
        self._client.close()

    def _post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        response = self._client.post(path, json=payload)
        if response.status_code >= 400:
            raise HarnessHttpError(path, response.status_code, response.text)
        return response.json()
