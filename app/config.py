from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


DEFAULT_ENV_FILE = ".env.local"


@dataclass(frozen=True)
class AppConfig:
    storage_backend: str = "sqlite"
    sqlite_url: str = "sqlite:///./pallium.db"
    default_use_case: str = "demo_agent_memory"
    llm_provider: str | None = None
    llm_model: str | None = None
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    llm_prompt_variant: str = "strict_decision_v2_source_aware"
    llm_timeout_seconds: float = 30.0

    @classmethod
    def from_env(cls) -> "AppConfig":
        file_values = _load_env_file(_resolve_env_file_path())
        timeout_value = _resolve_value("PALLIUM_LLM_TIMEOUT_SECONDS", file_values, "30")
        return cls(
            storage_backend=_resolve_value("PALLIUM_STORAGE_BACKEND", file_values, "sqlite"),
            sqlite_url=_resolve_value("PALLIUM_SQLITE_URL", file_values, "sqlite:///./pallium.db"),
            default_use_case=_resolve_value("PALLIUM_DEFAULT_USE_CASE", file_values, "demo_agent_memory"),
            llm_provider=_resolve_value("PALLIUM_LLM_PROVIDER", file_values),
            llm_model=_resolve_value("PALLIUM_LLM_MODEL", file_values),
            llm_base_url=_resolve_value("PALLIUM_LLM_BASE_URL", file_values),
            llm_api_key=_resolve_value("PALLIUM_LLM_API_KEY", file_values),
            llm_prompt_variant=_resolve_value("PALLIUM_LLM_PROMPT_VARIANT", file_values, "strict_decision_v2_source_aware") or "strict_decision_v2_source_aware",
            llm_timeout_seconds=float(timeout_value),
        )


def _resolve_env_file_path() -> Path:
    configured_path = os.getenv("PALLIUM_ENV_FILE")
    if configured_path:
        return Path(configured_path)
    return Path(DEFAULT_ENV_FILE)


def _resolve_value(name: str, file_values: dict[str, str], default: str | None = None) -> str | None:
    if name in os.environ:
        return os.environ[name]
    if name in file_values:
        return file_values[name]
    return default


def _load_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}

    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        values[key] = _strip_wrapping_quotes(value)
    return values


def _strip_wrapping_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value
