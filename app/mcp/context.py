"""Environment-based context resolution for Pallium MCP server."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class PalliumContext:
    """Resolved Pallium connection and scope context."""

    base_url: str | None = None
    container_ref: str | None = None
    thread_ref: str | None = None
    actor_ref: str | None = None
    visibility: str | None = None

    @property
    def is_configured(self) -> bool:
        return self.base_url is not None


def _canonicalize_container_ref(value: str | None) -> str | None:
    if value is None:
        return None
    match = re.fullmatch(
        r"git:github\.com/([^/]+)/([^/]+?)(?:\.git)?/?",
        value,
        flags=re.IGNORECASE,
    )
    if not match:
        return value
    return f"git:github.com/{match.group(1).lower()}/{match.group(2).lower()}"

def resolve_context(
    *,
    container_ref: str | None = None,
    thread_ref: str | None = None,
    actor_ref: str | None = None,
    visibility: str | None = None,
) -> PalliumContext:
    """Merge explicit parameters with environment variable defaults.

    Resolution order: explicit parameter > environment variable > None.
    """
    return PalliumContext(
        base_url=os.environ.get("PALLIUM_BASE_URL"),
        container_ref=_canonicalize_container_ref(container_ref if container_ref is not None else os.environ.get("PALLIUM_CONTAINER_REF")),
        thread_ref=thread_ref if thread_ref is not None else os.environ.get("PALLIUM_THREAD_REF"),
        actor_ref=actor_ref if actor_ref is not None else os.environ.get("PALLIUM_ACTOR_REF"),
        visibility=visibility if visibility is not None else os.environ.get("PALLIUM_VISIBILITY"),
    )
