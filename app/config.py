from __future__ import annotations

import copy
import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from capabilities.consolidation import ConsolidationPolicy, DEFAULT_CONSOLIDATION_STRATEGIES


DEFAULT_ENV_FILE = ".env.local"
DEFAULT_CONFIG_FILE = "pallium.local.toml"
LEGACY_PROVIDER_KEY = "legacy_default"


DEFAULT_AGENT_CONVERSATION_CONSOLIDATION = ConsolidationPolicy(
    enabled_strategies=DEFAULT_CONSOLIDATION_STRATEGIES,
    default_strategy="thread_summary_anchored",
    max_candidates_per_run=24,
    max_group_size=4,
    same_container_required=True,
    time_window_hours=168,
    lexical_overlap_threshold=2,
)


@dataclass(frozen=True)
class LLMProviderConfig:
    name: str
    kind: str
    base_url: str
    api_key: str | None = None
    api_key_env: str | None = None
    timeout_seconds: float = 30.0


@dataclass(frozen=True)
class SemanticPackageConfig:
    name: str
    implementation: str
    llm_provider: str | None = None
    model: str | None = None
    prompt_variant: str | None = None
    consolidation: ConsolidationPolicy | None = None


def _default_semantic_packages() -> dict[str, SemanticPackageConfig]:
    return {
        "demo_agent_memory": SemanticPackageConfig(name="demo_agent_memory", implementation="demo_agent_memory"),
        "llm_agent_memory": SemanticPackageConfig(
            name="llm_agent_memory",
            implementation="llm_agent_memory",
            prompt_variant="strict_typed_memory_v4_evidence_guarded",
        ),
        "agent_conversation_memory": SemanticPackageConfig(
            name="agent_conversation_memory",
            implementation="agent_conversation_memory",
            prompt_variant="strict_typed_memory_v4_evidence_guarded",
            consolidation=DEFAULT_AGENT_CONVERSATION_CONSOLIDATION,
        ),
    }


@dataclass(frozen=True)
class AppConfig:
    storage_backend: str = "sqlite"
    sqlite_url: str = "sqlite:///./pallium.db"
    default_use_case: str = "demo_agent_memory"
    llm_providers: dict[str, LLMProviderConfig] = field(default_factory=dict)
    semantic_packages: dict[str, SemanticPackageConfig] = field(default_factory=_default_semantic_packages)

    # Legacy compatibility inputs. New code should prefer llm_providers and semantic_packages.
    llm_provider: str | None = None
    llm_model: str | None = None
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    llm_prompt_variant: str | None = None
    llm_timeout_seconds: float | None = None

    def __post_init__(self) -> None:
        packages = _default_semantic_packages()
        packages.update(copy.deepcopy(self.semantic_packages))
        providers = copy.deepcopy(self.llm_providers)

        if self.llm_provider and self.llm_base_url:
            timeout_seconds = self.llm_timeout_seconds if self.llm_timeout_seconds is not None else 30.0
            providers[LEGACY_PROVIDER_KEY] = LLMProviderConfig(
                name=LEGACY_PROVIDER_KEY,
                kind=self.llm_provider,
                base_url=self.llm_base_url,
                api_key=self.llm_api_key,
                timeout_seconds=timeout_seconds,
            )
            for package_name in ("llm_agent_memory", "agent_conversation_memory"):
                current = packages.get(package_name, SemanticPackageConfig(name=package_name, implementation=package_name))
                packages[package_name] = SemanticPackageConfig(
                    name=current.name,
                    implementation=current.implementation,
                    llm_provider=LEGACY_PROVIDER_KEY,
                    model=self.llm_model or current.model,
                    prompt_variant=self.llm_prompt_variant or current.prompt_variant,
                    consolidation=current.consolidation,
                )

        object.__setattr__(self, "llm_providers", providers)
        object.__setattr__(self, "semantic_packages", packages)

    @classmethod
    def from_env(cls) -> "AppConfig":
        env_file_values = _load_env_file(_resolve_env_file_path())
        env_values = _merge_env_values(env_file_values)
        config_data = _load_config_file(_resolve_config_file_path(env_values))

        return cls(
            storage_backend=_resolve_global_value(
                "PALLIUM_STORAGE_BACKEND",
                env_values,
                _read_nested(config_data, "storage", "backend") or "sqlite",
            ) or "sqlite",
            sqlite_url=_resolve_global_value(
                "PALLIUM_SQLITE_URL",
                env_values,
                _read_nested(config_data, "storage", "sqlite_url") or "sqlite:///./pallium.db",
            ) or "sqlite:///./pallium.db",
            default_use_case=_resolve_global_value(
                "PALLIUM_DEFAULT_USE_CASE",
                env_values,
                config_data.get("default_use_case") or "demo_agent_memory",
            ) or "demo_agent_memory",
            llm_providers=_build_provider_configs(config_data, env_values),
            semantic_packages=_build_package_configs(config_data, env_values),
            llm_provider=_resolve_legacy_value("PALLIUM_LLM_PROVIDER", env_values),
            llm_model=_resolve_legacy_value("PALLIUM_LLM_MODEL", env_values),
            llm_base_url=_resolve_legacy_value("PALLIUM_LLM_BASE_URL", env_values),
            llm_api_key=_resolve_legacy_value("PALLIUM_LLM_API_KEY", env_values),
            llm_prompt_variant=_resolve_legacy_value("PALLIUM_LLM_PROMPT_VARIANT", env_values),
            llm_timeout_seconds=_resolve_float_value("PALLIUM_LLM_TIMEOUT_SECONDS", env_values),
        )

    def package_config(self, package_name: str) -> SemanticPackageConfig:
        if package_name not in self.semantic_packages:
            raise KeyError(f"Unknown semantic package: {package_name}")
        return self.semantic_packages[package_name]

    def provider_config(self, provider_name: str) -> LLMProviderConfig:
        if provider_name not in self.llm_providers:
            raise KeyError(f"Unknown LLM provider config: {provider_name}")
        return self.llm_providers[provider_name]

    def resolved_llm_settings_for(self, package_name: str) -> tuple[SemanticPackageConfig | None, LLMProviderConfig | None]:
        package = self.semantic_packages.get(package_name)
        if package is None or package.llm_provider is None:
            return package, None
        return package, self.llm_providers.get(package.llm_provider)

    @property
    def llm_model_for_default_use_case(self) -> str | None:
        package, _ = self.resolved_llm_settings_for(self.default_use_case)
        return package.model if package else None

    @property
    def llm_prompt_variant_for_default_use_case(self) -> str | None:
        package, _ = self.resolved_llm_settings_for(self.default_use_case)
        return package.prompt_variant if package else None

    @property
    def llm_provider_for_default_use_case(self) -> str | None:
        _, provider = self.resolved_llm_settings_for(self.default_use_case)
        return provider.kind if provider else None

    @property
    def llm_base_url_for_default_use_case(self) -> str | None:
        _, provider = self.resolved_llm_settings_for(self.default_use_case)
        return provider.base_url if provider else None

    @property
    def llm_timeout_seconds_for_default_use_case(self) -> float | None:
        _, provider = self.resolved_llm_settings_for(self.default_use_case)
        return provider.timeout_seconds if provider else None


def _resolve_env_file_path() -> Path:
    configured_path = os.getenv("PALLIUM_ENV_FILE")
    return Path(configured_path) if configured_path else Path(DEFAULT_ENV_FILE)


def _resolve_config_file_path(env_values: dict[str, str]) -> Path:
    configured_path = env_values.get("PALLIUM_CONFIG_FILE") or os.getenv("PALLIUM_CONFIG_FILE")
    return Path(configured_path) if configured_path else Path(DEFAULT_CONFIG_FILE)


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


def _load_config_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("rb") as handle:
        data = tomllib.load(handle)
    return data if isinstance(data, dict) else {}


def _strip_wrapping_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def _merge_env_values(file_values: dict[str, str]) -> dict[str, str]:
    merged = dict(file_values)
    merged.update(os.environ)
    return merged


def _resolve_global_value(name: str, env_values: dict[str, str], default: str | None = None) -> str | None:
    return env_values.get(name, default)


def _resolve_legacy_value(name: str, env_values: dict[str, str]) -> str | None:
    return env_values.get(name)


def _resolve_float_value(name: str, env_values: dict[str, str]) -> float | None:
    value = env_values.get(name)
    if value is None or value == "":
        return None
    return float(value)


def _read_nested(data: dict[str, Any], *keys: str) -> Any:
    current: Any = data
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    return current


def _build_provider_configs(config_data: dict[str, Any], env_values: dict[str, str]) -> dict[str, LLMProviderConfig]:
    providers: dict[str, LLMProviderConfig] = {}
    raw_providers = config_data.get("llm_providers", {})
    if isinstance(raw_providers, dict):
        for name, raw_value in raw_providers.items():
            if not isinstance(raw_value, dict):
                continue
            provider_name = str(name).strip().lower()
            providers[provider_name] = _provider_from_raw(provider_name, raw_value, env_values)

    prefix = "PALLIUM_PROVIDER__"
    for env_key, env_value in env_values.items():
        if not env_key.startswith(prefix):
            continue
        remainder = env_key[len(prefix) :]
        parts = remainder.split("__", 1)
        if len(parts) != 2:
            continue
        provider_name = parts[0].strip().lower()
        field_name = parts[1].strip().lower()
        current = providers.get(provider_name, LLMProviderConfig(name=provider_name, kind="", base_url=""))
        updated = {
            "name": current.name,
            "kind": current.kind,
            "base_url": current.base_url,
            "api_key": current.api_key,
            "api_key_env": current.api_key_env,
            "timeout_seconds": current.timeout_seconds,
        }
        if field_name == "kind":
            updated["kind"] = env_value
        elif field_name == "base_url":
            updated["base_url"] = env_value
        elif field_name == "api_key":
            updated["api_key"] = env_value
        elif field_name == "api_key_env":
            updated["api_key_env"] = env_value
            updated["api_key"] = env_values.get(env_value, updated["api_key"])
        elif field_name == "timeout_seconds":
            updated["timeout_seconds"] = float(env_value)
        providers[provider_name] = LLMProviderConfig(**updated)

    return providers


def _provider_from_raw(name: str, raw_value: dict[str, Any], env_values: dict[str, str]) -> LLMProviderConfig:
    api_key_env = _as_optional_string(raw_value.get("api_key_env"))
    api_key = _as_optional_string(raw_value.get("api_key"))
    if api_key_env and api_key_env in env_values:
        api_key = env_values[api_key_env]
    return LLMProviderConfig(
        name=name,
        kind=_as_string(raw_value.get("kind")),
        base_url=_as_string(raw_value.get("base_url")),
        api_key=api_key,
        api_key_env=api_key_env,
        timeout_seconds=float(raw_value.get("timeout_seconds", 30.0)),
    )


def _build_package_configs(config_data: dict[str, Any], env_values: dict[str, str]) -> dict[str, SemanticPackageConfig]:
    packages = _default_semantic_packages()
    raw_packages = config_data.get("semantic_packages", {})
    if isinstance(raw_packages, dict):
        for name, raw_value in raw_packages.items():
            if not isinstance(raw_value, dict):
                continue
            package_name = str(name).strip().lower()
            current = packages.get(package_name, SemanticPackageConfig(name=package_name, implementation=package_name))
            consolidation = _build_consolidation_policy(raw_value.get("consolidation"), current.consolidation)
            packages[package_name] = SemanticPackageConfig(
                name=package_name,
                implementation=_as_string(raw_value.get("implementation", current.implementation)),
                llm_provider=_as_optional_string(raw_value.get("llm_provider", current.llm_provider)),
                model=_as_optional_string(raw_value.get("model", current.model)),
                prompt_variant=_as_optional_string(raw_value.get("prompt_variant", current.prompt_variant)),
                consolidation=consolidation,
            )

    prefix = "PALLIUM_PACKAGE__"
    for env_key, env_value in env_values.items():
        if not env_key.startswith(prefix):
            continue
        remainder = env_key[len(prefix) :]
        parts = remainder.split("__", 1)
        if len(parts) != 2:
            continue
        package_name = parts[0].strip().lower()
        field_name = parts[1].strip().lower()
        current = packages.get(package_name, SemanticPackageConfig(name=package_name, implementation=package_name))
        updated = {
            "name": current.name,
            "implementation": current.implementation,
            "llm_provider": current.llm_provider,
            "model": current.model,
            "prompt_variant": current.prompt_variant,
            "consolidation": current.consolidation,
        }
        if field_name == "implementation":
            updated["implementation"] = env_value
        elif field_name == "llm_provider":
            updated["llm_provider"] = env_value
        elif field_name == "model":
            updated["model"] = env_value
        elif field_name == "prompt_variant":
            updated["prompt_variant"] = env_value
        packages[package_name] = SemanticPackageConfig(**updated)

    return packages


def _build_consolidation_policy(raw_value: Any, current: ConsolidationPolicy | None) -> ConsolidationPolicy | None:
    if raw_value is None:
        return current
    if not isinstance(raw_value, dict):
        return current
    base = current or ConsolidationPolicy()
    enabled = raw_value.get("enabled_strategies", base.enabled_strategies)
    if isinstance(enabled, list):
        enabled_strategies = tuple(str(item).strip() for item in enabled if str(item).strip()) or base.enabled_strategies
    else:
        enabled_strategies = base.enabled_strategies
    return ConsolidationPolicy(
        enabled_strategies=enabled_strategies,
        default_strategy=_as_string(raw_value.get("default_strategy", base.default_strategy)) or base.default_strategy,
        max_candidates_per_run=int(raw_value.get("max_candidates_per_run", base.max_candidates_per_run)),
        max_group_size=int(raw_value.get("max_group_size", base.max_group_size)),
        same_container_required=bool(raw_value.get("same_container_required", base.same_container_required)),
        time_window_hours=int(raw_value.get("time_window_hours", base.time_window_hours)),
        lexical_overlap_threshold=int(raw_value.get("lexical_overlap_threshold", base.lexical_overlap_threshold)),
    )


def _as_string(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _as_optional_string(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None
