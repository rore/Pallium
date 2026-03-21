"""Configuration dataclass for SAP AI Core provider."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AICoreProviderConfig:
    """AI Core-specific settings resolved from environment variables.

    Each ``*_env`` field names the environment variable that holds the
    actual credential value (e.g. ``"AICORE_CLIENT_ID"``).  The resolved
    ``*`` fields carry the runtime values after env-var lookup.
    """

    client_id: str
    client_secret: str
    auth_url: str
    base_url: str
    resource_group: str = "default"
