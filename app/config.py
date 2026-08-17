from __future__ import annotations

import copy
import logging
import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from capabilities.consolidation import ConsolidationPolicy, DEFAULT_CONSOLIDATION_STRATEGIES
from providers.llm.aicore_config import AICoreProviderConfig
from providers.llm.base import LLMRetryPolicy
from storage.vector_index import VectorIndexConfig

logger = logging.getLogger(__name__)


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
    api_key_file: str | None = None
    timeout_seconds: float = 30.0
    retry_policy: LLMRetryPolicy = field(default_factory=LLMRetryPolicy)
    auth_style: str = "native"  # "native" (provider default) or "bearer" (Authorization: Bearer)
    max_tokens: int = 2048
    aicore: AICoreProviderConfig | None = None


@dataclass(frozen=True)
class EmbeddingProviderConfig:
    name: str
    kind: str                     # "fastembed" | "onnx"
    model: str = ""               # empty = use provider's built-in default
    dimensions: int | None = None
    cache_dir: str | None = None  # model cache directory (default: HuggingFace global cache)
    query_prefix: str = ""
    passage_prefix: str = ""
    max_tokens: int = 512         # max token sequence length (ONNX provider only)


@dataclass(frozen=True)
class SemanticPackageConfig:
    name: str
    implementation: str
    enabled: bool = True
    llm_provider: str | None = None
    model: str | None = None
    prompt_variant: str | None = None
    prompt_variants: dict[str, str] | None = None
    model_roles: dict[str, str] | None = None
    consolidation: ConsolidationPolicy | None = None
    resolver_enabled: bool = True
    resolver_timeout_ms: int = 800


@dataclass(frozen=True)
class ObservabilityConfig:
    integration_debug: bool = False
    query_audit_log: bool = False
    metrics_retention_days: int = 0
    # Shadow-only sub-task selector experiment (REPORT6 validation).
    # Default False = bit-exact no-op vs prior behaviour. When True, a
    # frozen B/C selector observes work_resumption==strongly_eligible
    # multi-candidate queries off the hot path and records its picks to
    # the subtask_selector_shadow table. It NEVER affects should_inject,
    # injectable_blocks, or anything the agent sees. Removable: delete
    # the runner + table + this flag with no other behaviour change.
    shadow_subtask_selector_enabled: bool = False
    shadow_subtask_selector_timeout_ms: int = 10000
    # Historical-lookup reuse funnel. Persistence of lookup/expansion events is
    # UNCONDITIONAL (see HistoricalLookupReuseEventRecord) so the Phase-1 reuse
    # KPI is measurable on a fresh install; this flag is the declared "armed"
    # signal that `pallium service status` and `pallium setup claude-code`
    # report. Default True = armed out of the box. Set False to advertise the
    # funnel as intentionally disabled (does NOT stop the write-only telemetry).
    historical_lookup_funnel: bool = True


@dataclass(frozen=True)
class RetentionConfig:
    enabled: bool = False
    run_interval_seconds: int = 300
    lease_seconds: int = 300
    batch_size: int = 200


@dataclass(frozen=True)
class SnapshotConfig:
    enabled: bool = False
    snapshot_path: str | None = None
    interval_seconds: int = 60
    max_snapshots: int = 5


# ── Phase 3a: injection-policy abstention (per type, per container) ─────
#
# See docs/specs/2026-06-27-injection-policy-abstention.md.
#
# Default is empty — absent `[injection.policy]` means "no policy, behave
# as before." Phase 3b will populate the types dict via TOML edits.
#
# Container override matching is exact string equality against
# `container_ref`. TOML keys are opaque — case, slashes, and colons are
# all significant.

_INJECTION_POLICY_VALID_MODES: frozenset[str] = frozenset({
    "proactive",       # gate on score >= min_score
    "event",           # drop from proactive; Phase 4 event triggers replace
    "on_demand",       # drop from proactive; explicit pallium_query only
    "suspended",       # drop from proactive; pipeline known broken
})


@dataclass(frozen=True)
class InjectionTypePolicy:
    """Per-type proactive injection policy.

    `min_score` is required when mode == "proactive"; it is the result-score
    threshold (QueryResultItem.score) the candidate must meet. The other
    modes drop the type from proactive injection entirely.
    """
    mode: str = "proactive"
    min_score: float | None = None


@dataclass(frozen=True)
class InjectionPolicyConfig:
    """Global + per-container injection policies.

    Empty dicts mean "no policy, no-op." A query's effective per-type
    policy is the per-container override (matched by query's
    `container_ref`) if present, else the global `types[type]`, else
    no policy (pass-through).
    """
    types: dict[str, InjectionTypePolicy] = field(default_factory=dict)
    # container_ref -> {memory_type: InjectionTypePolicy}
    containers: dict[str, dict[str, InjectionTypePolicy]] = field(default_factory=dict)

    def is_empty(self) -> bool:
        return not self.types and not self.containers

    def effective(self, memory_type: str, container_ref: str | None) -> InjectionTypePolicy | None:
        """Return the effective policy for (memory_type, container_ref) or None."""
        if container_ref and container_ref in self.containers:
            override = self.containers[container_ref].get(memory_type)
            if override is not None:
                return override
        return self.types.get(memory_type)


@dataclass(frozen=True)
class InjectionConfig:
    policy: InjectionPolicyConfig = field(default_factory=InjectionPolicyConfig)


@dataclass(frozen=True)
class FeaturesConfig:
    """Feature flags for progressively-rolling-out capabilities.

    Every field must have a safe-off default. See individual field
    docstrings for what each flag gates.
    """

    # W4 PR 3: derivation of operational_fact memories from the
    # agent_work_trace_turn corpus. When False, task_trace is written as
    # before and zero operational_fact rows are produced by the plugin.
    # Default off so a mid-milestone git pull does NOT silently enable
    # derivation on a developer's machine.
    operational_fact_derivation: bool = False

    # W5 PR 1: shadow-extractor pipeline. When True, every source item
    # processed by the live extractor is ALSO fed through a single-call
    # strict-JSON extractor whose output lands in ``memory_objects_shadow``.
    # Shadow writes are guaranteed disjoint from the live path — see
    # docs/specs/2026-07-01-milestone-shaped-memory-contract.md §W5.
    # Default off. Enable only in the measurement window; the shadow
    # extractor costs an extra LLM call per source item.
    typed_extraction_shadow: bool = False


def _default_semantic_packages() -> dict[str, SemanticPackageConfig]:
    return {
        "agent_conversation_memory": SemanticPackageConfig(
            name="agent_conversation_memory",
            implementation="agent_conversation_memory",
            prompt_variant="strict_typed_memory_v8b_work_refs_separate",
            consolidation=DEFAULT_AGENT_CONVERSATION_CONSOLIDATION,
        ),
        "conversational_knowledge": SemanticPackageConfig(
            name="conversational_knowledge",
            implementation="conversational_knowledge",
        ),
    }


@dataclass(frozen=True)
class AppConfig:
    storage_backend: str = "sqlite"
    sqlite_url: str = "sqlite:///./pallium.db"
    default_use_case: str = "agent_conversation_memory"
    # Trusted single-user compatibility mode. This is NOT "auth optional":
    # container-scoped authorization on raw-turn forgetting is ALWAYS enforced
    # when the caller supplies a scope (a supplied-but-mismatched scope is
    # always denied). This flag relaxes ONLY the *missing caller scope* case —
    # the single-user local install where the invocation context has no
    # container. True (default) = allow forget when caller scope is absent
    # (matches the historical single-user behaviour). False = strict
    # multi-user: a scoped caller identity is required or the forget is denied.
    # Enabling True while binding beyond loopback is guarded at serve startup.
    single_user_trusted_mode: bool = True
    llm_providers: dict[str, LLMProviderConfig] = field(default_factory=dict)
    embedding_providers: dict[str, EmbeddingProviderConfig] = field(default_factory=dict)
    semantic_packages: dict[str, SemanticPackageConfig] = field(default_factory=_default_semantic_packages)
    observability: ObservabilityConfig = field(default_factory=ObservabilityConfig)
    retention: RetentionConfig = field(default_factory=RetentionConfig)
    vector_index: VectorIndexConfig = field(default_factory=VectorIndexConfig)
    snapshot: SnapshotConfig = field(default_factory=SnapshotConfig)
    injection: InjectionConfig = field(default_factory=InjectionConfig)
    features: FeaturesConfig = field(default_factory=FeaturesConfig)

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

        # Auto-create default ONNX embedding provider when none is configured
        embedding = copy.deepcopy(self.embedding_providers)
        if not embedding:
            embedding["onnx"] = EmbeddingProviderConfig(
                name="onnx",
                kind="onnx",
            )

        if self.llm_provider and self.llm_base_url:
            existing_legacy = providers.get(LEGACY_PROVIDER_KEY)
            timeout_seconds = self.llm_timeout_seconds if self.llm_timeout_seconds is not None else (existing_legacy.timeout_seconds if existing_legacy else 30.0)
            providers[LEGACY_PROVIDER_KEY] = LLMProviderConfig(
                name=LEGACY_PROVIDER_KEY,
                kind=self.llm_provider,
                base_url=self.llm_base_url,
                api_key=self.llm_api_key,
                timeout_seconds=timeout_seconds,
                retry_policy=existing_legacy.retry_policy if existing_legacy else LLMRetryPolicy(),
            )
            for package_name in ("llm_agent_memory", "agent_conversation_memory", "conversational_knowledge"):
                current = packages.get(package_name, SemanticPackageConfig(name=package_name, implementation=package_name))
                packages[package_name] = SemanticPackageConfig(
                    name=current.name,
                    implementation=current.implementation,
                    llm_provider=LEGACY_PROVIDER_KEY,
                    model=self.llm_model or current.model,
                    prompt_variant=self.llm_prompt_variant or current.prompt_variant,
                    prompt_variants=current.prompt_variants,
                    model_roles=current.model_roles,
                    consolidation=current.consolidation,
                    resolver_enabled=current.resolver_enabled,
                    resolver_timeout_ms=current.resolver_timeout_ms,
                )

        object.__setattr__(self, "llm_providers", providers)
        object.__setattr__(self, "embedding_providers", embedding)
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
                config_data.get("default_use_case") or "agent_conversation_memory",
            ) or "agent_conversation_memory",
            single_user_trusted_mode=_resolve_bool_value(
                "PALLIUM_SINGLE_USER_TRUSTED_MODE",
                env_values,
                config_data.get("single_user_trusted_mode"),
                True,
            ),
            observability=ObservabilityConfig(
                integration_debug=_resolve_bool_value(
                    "PALLIUM_OBSERVABILITY_INTEGRATION_DEBUG",
                    env_values,
                    _read_nested(config_data, "observability", "integration_debug"),
                    False,
                ),
                query_audit_log=_resolve_bool_value(
                    "PALLIUM_OBSERVABILITY_QUERY_AUDIT_LOG",
                    env_values,
                    _read_nested(config_data, "observability", "query_audit_log"),
                    False,
                ),
                metrics_retention_days=_resolve_int_setting(
                    "PALLIUM_OBSERVABILITY_METRICS_RETENTION_DAYS",
                    env_values,
                    _read_nested(config_data, "observability", "metrics_retention_days"),
                    0,
                ),
                shadow_subtask_selector_enabled=_resolve_bool_value(
                    "PALLIUM_OBSERVABILITY_SHADOW_SUBTASK_SELECTOR_ENABLED",
                    env_values,
                    _read_nested(config_data, "observability", "shadow_subtask_selector_enabled"),
                    False,
                ),
                shadow_subtask_selector_timeout_ms=_resolve_int_setting(
                    "PALLIUM_OBSERVABILITY_SHADOW_SUBTASK_SELECTOR_TIMEOUT_MS",
                    env_values,
                    _read_nested(config_data, "observability", "shadow_subtask_selector_timeout_ms"),
                    10000,
                ),
                historical_lookup_funnel=_resolve_bool_value(
                    "PALLIUM_OBSERVABILITY_HISTORICAL_LOOKUP_FUNNEL",
                    env_values,
                    _read_nested(config_data, "observability", "historical_lookup_funnel"),
                    True,
                ),
            ),
            retention=RetentionConfig(
                enabled=_resolve_bool_value(
                    "PALLIUM_RETENTION_ENABLED",
                    env_values,
                    _read_nested(config_data, "retention", "enabled"),
                    False,
                ),
                run_interval_seconds=_resolve_int_setting(
                    "PALLIUM_RETENTION_RUN_INTERVAL_SECONDS",
                    env_values,
                    _read_nested(config_data, "retention", "run_interval_seconds"),
                    300,
                ),
                lease_seconds=_resolve_int_setting(
                    "PALLIUM_RETENTION_LEASE_SECONDS",
                    env_values,
                    _read_nested(config_data, "retention", "lease_seconds"),
                    300,
                ),
                batch_size=_resolve_int_setting(
                    "PALLIUM_RETENTION_BATCH_SIZE",
                    env_values,
                    _read_nested(config_data, "retention", "batch_size"),
                    200,
                ),
            ),
            snapshot=SnapshotConfig(
                enabled=_resolve_bool_value(
                    "PALLIUM_SNAPSHOT_ENABLED",
                    env_values,
                    _read_nested(config_data, "snapshot", "enabled"),
                    False,
                ),
                snapshot_path=_resolve_global_value(
                    "PALLIUM_SNAPSHOT_PATH",
                    env_values,
                    _as_optional_string(_read_nested(config_data, "snapshot", "snapshot_path")),
                ),
                interval_seconds=_resolve_int_setting(
                    "PALLIUM_SNAPSHOT_INTERVAL_SECONDS",
                    env_values,
                    _read_nested(config_data, "snapshot", "interval_seconds"),
                    60,
                ),
                max_snapshots=_resolve_int_setting(
                    "PALLIUM_SNAPSHOT_MAX_SNAPSHOTS",
                    env_values,
                    _read_nested(config_data, "snapshot", "max_snapshots"),
                    5,
                ),
            ),
            llm_providers=_build_provider_configs(config_data, env_values),
            embedding_providers=_build_embedding_provider_configs(config_data),
            semantic_packages=_build_package_configs(config_data, env_values),
            vector_index=_build_vector_index_config(config_data, env_values),
            injection=_build_injection_config(config_data),
            features=_build_features_config(config_data, env_values),
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

    def embedding_provider_config(self, provider_name: str) -> EmbeddingProviderConfig:
        if provider_name not in self.embedding_providers:
            raise KeyError(f"Unknown embedding provider config: {provider_name}")
        return self.embedding_providers[provider_name]

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


def _resolve_optional_float(env_value: str | None, config_value: Any) -> float | None:
    """Resolve a float that may be None (unset in both env and config)."""
    if env_value is not None and env_value != "":
        return float(env_value)
    if config_value is not None:
        return float(config_value)
    return None


def _resolve_int_setting(name: str, env_values: dict[str, str], raw_value: Any, default: int) -> int:
    if name in env_values:
        return int(env_values[name])
    if raw_value is None or raw_value == "":
        return default
    return int(raw_value)


def _resolve_bool_value(
    name: str,
    env_values: dict[str, str],
    raw_value: Any,
    default: bool,
) -> bool:
    if name in env_values:
        return _parse_bool(env_values[name], default)
    return _parse_bool(raw_value, default)


def _read_nested(data: dict[str, Any], *keys: str) -> Any:
    current: Any = data
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    return current


def _parse_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


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
            "api_key_file": current.api_key_file,
            "timeout_seconds": current.timeout_seconds,
            "retry_policy": current.retry_policy,
            "auth_style": current.auth_style,
            "max_tokens": current.max_tokens,
            "aicore": current.aicore,
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
        elif field_name == "api_key_file":
            updated["api_key_file"] = env_value
            updated["api_key"] = _load_secret_file(env_value) or updated["api_key"]
        elif field_name == "timeout_seconds":
            updated["timeout_seconds"] = float(env_value)
        elif field_name == "auth_style":
            updated["auth_style"] = env_value
        elif field_name == "max_attempts":
            updated["retry_policy"] = _update_retry_policy(updated["retry_policy"], max_attempts=int(env_value))
        elif field_name == "base_backoff_ms":
            updated["retry_policy"] = _update_retry_policy(updated["retry_policy"], base_backoff_ms=int(env_value))
        elif field_name == "max_backoff_ms":
            updated["retry_policy"] = _update_retry_policy(updated["retry_policy"], max_backoff_ms=int(env_value))
        elif field_name == "jitter_ratio":
            updated["retry_policy"] = _update_retry_policy(updated["retry_policy"], jitter_ratio=float(env_value))
        elif field_name == "max_concurrency":
            updated["retry_policy"] = _update_retry_policy(updated["retry_policy"], max_concurrency=int(env_value))
        providers[provider_name] = LLMProviderConfig(**updated)

    return providers


def _provider_from_raw(name: str, raw_value: dict[str, Any], env_values: dict[str, str]) -> LLMProviderConfig:
    api_key_env = _as_optional_string(raw_value.get("api_key_env"))
    api_key_file = _as_optional_string(raw_value.get("api_key_file"))
    api_key = _as_optional_string(raw_value.get("api_key"))
    if api_key_env and api_key_env in env_values:
        api_key = env_values[api_key_env]
    elif api_key_file:
        api_key = _load_secret_file(api_key_file) or api_key

    kind = _as_string(raw_value.get("kind"))

    # Parse AI Core sub-table when provider kind is aicore_anthropic.
    aicore: AICoreProviderConfig | None = None
    if kind == "aicore_anthropic":
        aicore_raw = raw_value.get("aicore", {})
        if not isinstance(aicore_raw, dict):
            raise ValueError(f"Provider '{name}': 'aicore' must be a table")

        def _resolve_env(env_key: str, field_label: str) -> str:
            env_name = _as_string(aicore_raw.get(env_key))
            if not env_name:
                raise ValueError(f"Provider '{name}': aicore.{env_key} is required")
            value = env_values.get(env_name) or os.environ.get(env_name)
            if not value:
                raise ValueError(
                    f"Provider '{name}': env var '{env_name}' "
                    f"(for aicore.{env_key}) is not set"
                )
            return value

        aicore = AICoreProviderConfig(
            client_id=_resolve_env("client_id_env", "client_id"),
            client_secret=_resolve_env("client_secret_env", "client_secret"),
            auth_url=_resolve_env("auth_url_env", "auth_url"),
            base_url=_resolve_env("base_url_env", "base_url"),
            resource_group=_as_string(aicore_raw.get("resource_group", "default")) or "default",
        )

    base_url = _as_optional_string(raw_value.get("base_url")) or ""
    # For aicore_anthropic the base_url comes from the aicore sub-table.
    if kind == "aicore_anthropic" and aicore:
        base_url = aicore.base_url

    return LLMProviderConfig(
        name=name,
        kind=kind,
        base_url=base_url,
        api_key=api_key,
        api_key_env=api_key_env,
        api_key_file=api_key_file,
        timeout_seconds=float(raw_value.get("timeout_seconds", 30.0)),
        retry_policy=LLMRetryPolicy(
            max_attempts=int(raw_value.get("max_attempts", 3)),
            base_backoff_ms=int(raw_value.get("base_backoff_ms", 250)),
            max_backoff_ms=int(raw_value.get("max_backoff_ms", 3000)),
            jitter_ratio=float(raw_value.get("jitter_ratio", 0.2)),
            max_concurrency=int(raw_value.get("max_concurrency", 4)),
        ),
        auth_style=_as_string(raw_value.get("auth_style", "native")) or "native",
        max_tokens=int(raw_value.get("max_tokens", 2048)),
        aicore=aicore,
    )


def _build_embedding_provider_configs(config_data: dict[str, Any]) -> dict[str, EmbeddingProviderConfig]:
    providers: dict[str, EmbeddingProviderConfig] = {}
    raw_providers = config_data.get("embedding_providers", {})
    if isinstance(raw_providers, dict):
        for name, raw_value in raw_providers.items():
            if not isinstance(raw_value, dict):
                continue
            provider_name = str(name).strip().lower()
            raw_dims = raw_value.get("dimensions")
            dimensions = int(raw_dims) if raw_dims is not None else None
            providers[provider_name] = EmbeddingProviderConfig(
                name=provider_name,
                kind=_as_string(raw_value.get("kind")),
                model=_as_string(raw_value.get("model")),  # empty = use provider default
                dimensions=dimensions,
                cache_dir=_as_string(raw_value.get("cache_dir")) if raw_value.get("cache_dir") else None,
                query_prefix=_as_string(raw_value.get("query_prefix")),
                passage_prefix=_as_string(raw_value.get("passage_prefix")),
            )
    return providers


def _build_vector_index_config(config_data: dict[str, Any], env_values: dict[str, str]) -> VectorIndexConfig:
    defaults = VectorIndexConfig()
    raw = config_data.get("vector_index", {})
    if not isinstance(raw, dict):
        raw = {}
    return VectorIndexConfig(
        enabled=_resolve_bool_value(
            "PALLIUM_VECTOR_INDEX_ENABLED",
            env_values,
            raw.get("enabled"),
            defaults.enabled,
        ),
        index_path=_resolve_global_value(
            "PALLIUM_VECTOR_INDEX_PATH",
            env_values,
            _as_string(raw.get("index_path")) or defaults.index_path,
        ) or defaults.index_path,
        embedding_provider=_as_optional_string(
            env_values.get("PALLIUM_VECTOR_INDEX_EMBEDDING_PROVIDER")
            or raw.get("embedding_provider")
        ) or defaults.embedding_provider,
        min_similarity=_resolve_optional_float(
            env_values.get("PALLIUM_VECTOR_INDEX_MIN_SIMILARITY"),
            raw.get("min_similarity"),
        ),
    )


def _build_injection_type_policy(raw: Any) -> InjectionTypePolicy:
    if not isinstance(raw, dict):
        raise ValueError(
            "Each [injection.policy.types.<type>] block must be a table; "
            f"got {type(raw).__name__}"
        )
    mode = _as_string(raw.get("mode", "proactive"))
    if mode not in _INJECTION_POLICY_VALID_MODES:
        raise ValueError(
            f"Invalid injection policy mode {mode!r}; "
            f"valid values: {sorted(_INJECTION_POLICY_VALID_MODES)}"
        )
    raw_min = raw.get("min_score")
    min_score: float | None = None
    if raw_min is not None:
        try:
            min_score = float(raw_min)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"min_score must be numeric; got {raw_min!r}"
            ) from exc
    if mode == "proactive" and min_score is None:
        raise ValueError(
            "Injection policy mode 'proactive' requires a numeric min_score"
        )
    return InjectionTypePolicy(mode=mode, min_score=min_score)


def _build_injection_types_block(raw_types: Any) -> dict[str, InjectionTypePolicy]:
    if raw_types is None:
        return {}
    if not isinstance(raw_types, dict):
        raise ValueError(
            "[injection.policy.types] must be a table; "
            f"got {type(raw_types).__name__}"
        )
    out: dict[str, InjectionTypePolicy] = {}
    for type_name, raw_value in raw_types.items():
        out[str(type_name)] = _build_injection_type_policy(raw_value)
    return out


def _build_features_config(
    config_data: dict[str, Any],
    env_values: dict[str, str],
) -> FeaturesConfig:
    """Read the [features] section into a FeaturesConfig.

    Missing section returns defaults (all flags off). Env-var overrides
    win via the standard PALLIUM_FEATURES_<FLAG_UPPER> pattern.
    """
    raw = config_data.get("features")
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ValueError(
            "[features] must be a table; "
            f"got {type(raw).__name__}"
        )
    return FeaturesConfig(
        operational_fact_derivation=_resolve_bool_value(
            "PALLIUM_FEATURES_OPERATIONAL_FACT_DERIVATION",
            env_values,
            raw.get("operational_fact_derivation"),
            False,
        ),
        typed_extraction_shadow=_resolve_bool_value(
            "PALLIUM_FEATURES_TYPED_EXTRACTION_SHADOW",
            env_values,
            raw.get("typed_extraction_shadow"),
            False,
        ),
    )


def _build_injection_config(config_data: dict[str, Any]) -> InjectionConfig:
    raw_injection = config_data.get("injection")
    if raw_injection is None:
        return InjectionConfig()
    if not isinstance(raw_injection, dict):
        raise ValueError(
            "[injection] must be a table; "
            f"got {type(raw_injection).__name__}"
        )
    raw_policy = raw_injection.get("policy")
    if raw_policy is None:
        return InjectionConfig()
    if not isinstance(raw_policy, dict):
        raise ValueError(
            "[injection.policy] must be a table; "
            f"got {type(raw_policy).__name__}"
        )

    types = _build_injection_types_block(raw_policy.get("types"))

    containers: dict[str, dict[str, InjectionTypePolicy]] = {}
    raw_containers = raw_policy.get("containers")
    if raw_containers is not None:
        if not isinstance(raw_containers, list):
            raise ValueError(
                "[[injection.policy.containers]] must be an array of tables; "
                f"got {type(raw_containers).__name__}"
            )
        for entry in raw_containers:
            if not isinstance(entry, dict):
                raise ValueError(
                    "Each [[injection.policy.containers]] entry must be a table"
                )
            container_ref = _as_optional_string(entry.get("container_ref"))
            if not container_ref:
                raise ValueError(
                    "Each [[injection.policy.containers]] entry must set "
                    "container_ref (non-empty string)"
                )
            if container_ref in containers:
                raise ValueError(
                    f"Duplicate container_ref in [[injection.policy.containers]]: "
                    f"{container_ref!r}"
                )
            containers[container_ref] = _build_injection_types_block(
                entry.get("types")
            )

    return InjectionConfig(
        policy=InjectionPolicyConfig(types=types, containers=containers)
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
            prompt_variants = _merge_normalized_dict(raw_value.get("prompt_variants"), current.prompt_variants)
            model_roles = _merge_normalized_dict(raw_value.get("model_roles"), current.model_roles)
            packages[package_name] = SemanticPackageConfig(
                name=package_name,
                implementation=_as_string(raw_value.get("implementation", current.implementation)),
                enabled=_parse_bool(raw_value.get("enabled"), current.enabled),
                llm_provider=_as_optional_string(raw_value.get("llm_provider", current.llm_provider)),
                model=_as_optional_string(raw_value.get("model", current.model)),
                prompt_variant=_as_optional_string(raw_value.get("prompt_variant", current.prompt_variant)),
                prompt_variants=prompt_variants,
                model_roles=model_roles,
                consolidation=consolidation,
                resolver_enabled=_parse_bool(raw_value.get("resolver_enabled"), current.resolver_enabled),
                resolver_timeout_ms=int(raw_value.get("resolver_timeout_ms", current.resolver_timeout_ms)),
            )

    prefix = "PALLIUM_PACKAGE__"
    prompt_variants_prefix = "PROMPT_VARIANTS__"
    model_roles_prefix = "MODEL_ROLES__"
    for env_key, env_value in env_values.items():
        if not env_key.startswith(prefix):
            continue
        remainder = env_key[len(prefix) :]
        parts = remainder.split("__", 1)
        if len(parts) != 2:
            continue
        package_name = parts[0].strip().lower()
        field_name = parts[1].strip().lower()

        if field_name.startswith(prompt_variants_prefix.lower()):
            role = field_name[len(prompt_variants_prefix):].strip().lower()
            if not role:
                continue
            current = packages.get(package_name, SemanticPackageConfig(name=package_name, implementation=package_name))
            existing = dict(current.prompt_variants) if current.prompt_variants else {}
            existing[role] = env_value
            updated = {
                "name": current.name,
                "implementation": current.implementation,
                "llm_provider": current.llm_provider,
                "model": current.model,
                "prompt_variant": current.prompt_variant,
                "prompt_variants": existing,
                "model_roles": current.model_roles,
                "consolidation": current.consolidation,
                "resolver_enabled": current.resolver_enabled,
                "resolver_timeout_ms": current.resolver_timeout_ms,
            }
            packages[package_name] = SemanticPackageConfig(**updated)
            continue

        if field_name.startswith(model_roles_prefix.lower()):
            role = field_name[len(model_roles_prefix):].strip().lower()
            if not role:
                continue
            current = packages.get(package_name, SemanticPackageConfig(name=package_name, implementation=package_name))
            existing = dict(current.model_roles) if current.model_roles else {}
            existing[role] = env_value
            updated = {
                "name": current.name,
                "implementation": current.implementation,
                "llm_provider": current.llm_provider,
                "model": current.model,
                "prompt_variant": current.prompt_variant,
                "prompt_variants": current.prompt_variants,
                "model_roles": existing,
                "consolidation": current.consolidation,
                "resolver_enabled": current.resolver_enabled,
                "resolver_timeout_ms": current.resolver_timeout_ms,
            }
            packages[package_name] = SemanticPackageConfig(**updated)
            continue

        current = packages.get(package_name, SemanticPackageConfig(name=package_name, implementation=package_name))
        updated = {
            "name": current.name,
            "implementation": current.implementation,
            "llm_provider": current.llm_provider,
            "model": current.model,
            "prompt_variant": current.prompt_variant,
            "prompt_variants": current.prompt_variants,
            "model_roles": current.model_roles,
            "consolidation": current.consolidation,
            "resolver_enabled": current.resolver_enabled,
            "resolver_timeout_ms": current.resolver_timeout_ms,
        }
        if field_name == "implementation":
            updated["implementation"] = env_value
        elif field_name == "llm_provider":
            updated["llm_provider"] = env_value
        elif field_name == "model":
            updated["model"] = env_value
        elif field_name == "prompt_variant":
            updated["prompt_variant"] = env_value
        elif field_name == "resolver_enabled":
            updated["resolver_enabled"] = _parse_bool(env_value, current.resolver_enabled)
        elif field_name == "resolver_timeout_ms":
            updated["resolver_timeout_ms"] = int(env_value)
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


def _merge_normalized_dict(raw_value: Any, current: dict[str, str] | None) -> dict[str, str] | None:
    """Merge a raw dict into an existing normalized string dict."""
    if raw_value is None:
        return current
    if not isinstance(raw_value, dict):
        return current
    merged = dict(current) if current else {}
    for key, val in raw_value.items():
        normalized_key = str(key).strip().lower()
        normalized_val = str(val).strip()
        if normalized_key and normalized_val:
            merged[normalized_key] = normalized_val
    return merged or None


def _as_string(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _as_optional_string(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _load_secret_file(path_value: str) -> str | None:
    try:
        return Path(path_value).expanduser().read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def _update_retry_policy(policy: LLMRetryPolicy, **updates: Any) -> LLMRetryPolicy:
    return LLMRetryPolicy(
        max_attempts=int(updates.get("max_attempts", policy.max_attempts)),
        base_backoff_ms=int(updates.get("base_backoff_ms", policy.base_backoff_ms)),
        max_backoff_ms=int(updates.get("max_backoff_ms", policy.max_backoff_ms)),
        jitter_ratio=float(updates.get("jitter_ratio", policy.jitter_ratio)),
        max_concurrency=int(updates.get("max_concurrency", policy.max_concurrency)),
    )
