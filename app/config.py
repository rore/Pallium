from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class AppConfig:
    storage_backend: str = "sqlite"
    sqlite_url: str = "sqlite:///./pallium.db"
    default_use_case: str = "demo_agent_memory"

    @classmethod
    def from_env(cls) -> "AppConfig":
        return cls(
            storage_backend=os.getenv("PALLIUM_STORAGE_BACKEND", "sqlite"),
            sqlite_url=os.getenv("PALLIUM_SQLITE_URL", "sqlite:///./pallium.db"),
            default_use_case=os.getenv("PALLIUM_DEFAULT_USE_CASE", "demo_agent_memory"),
        )
