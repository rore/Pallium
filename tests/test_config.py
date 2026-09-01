from __future__ import annotations

from pathlib import Path

import pytest

from app.config import AppConfig
from tests.config_helpers import DEFAULT_PROMPT_VARIANT, build_llm_test_config
from app.config import EmbeddingProviderConfig


def test_app_config_loads_from_toml_and_env_overrides(monkeypatch, tmp_path: Path) -> None:
    config_file = tmp_path / "pallium.local.toml"
    config_file.write_text(
        """
        default_use_case = "agent_conversation_memory"

        [storage]
        backend = "sqlite"
        sqlite_url = "sqlite:///./configured.db"

        [llm_providers.openai]
        kind = "openai_compatible"
        base_url = "https://file.example/v1"
        api_key_env = "PALLIUM_OPENAI_API_KEY"
        timeout_seconds = 45
        max_attempts = 4
        base_backoff_ms = 150
        max_backoff_ms = 1200
        jitter_ratio = 0.1
        max_concurrency = 2

        [semantic_packages.agent_conversation_memory]
        implementation = "agent_conversation_memory"
        llm_provider = "openai"
        model = "file-model"
        prompt_variant = "strict_decision_v1"

        [semantic_packages.agent_conversation_memory.consolidation]
        enabled_strategies = ["thread_local_carry_forward", "thread_summary_anchored"]
        default_strategy = "thread_summary_anchored"
        max_candidates_per_run = 12
        max_group_size = 3
        same_container_required = true
        time_window_hours = 48
        lexical_overlap_threshold = 1
        """.strip(),
        encoding="utf-8",
    )

    monkeypatch.setenv("PALLIUM_CONFIG_FILE", str(config_file))
    monkeypatch.setenv("PALLIUM_OPENAI_API_KEY", "file-key")
    monkeypatch.setenv("PALLIUM_PACKAGE__AGENT_CONVERSATION_MEMORY__MODEL", "env-model")

    config = AppConfig.from_env()

    assert config.default_use_case == "agent_conversation_memory"
    assert config.sqlite_url == "sqlite:///./configured.db"
    package = config.package_config("agent_conversation_memory")
    assert package.model == "env-model"
    assert package.prompt_variant == "strict_decision_v1"
    assert package.consolidation is not None
    assert package.consolidation.enabled_strategies == ("thread_local_carry_forward", "thread_summary_anchored")
    assert package.consolidation.default_strategy == "thread_summary_anchored"
    assert package.consolidation.max_candidates_per_run == 12
    provider = config.provider_config("openai")
    assert provider.kind == "openai_compatible"
    assert provider.base_url == "https://file.example/v1"
    assert provider.api_key == "file-key"
    assert provider.timeout_seconds == 45.0
    assert provider.retry_policy.max_attempts == 4
    assert provider.retry_policy.base_backoff_ms == 150
    assert provider.retry_policy.max_backoff_ms == 1200
    assert provider.retry_policy.jitter_ratio == 0.1
    assert provider.retry_policy.max_concurrency == 2


def test_build_semantic_plugins_exposes_agent_conversation_package(monkeypatch) -> None:
    from app.dependencies import build_semantic_plugins

    class StubProvider:
        def generate_json(self, *, system_prompt: str, user_prompt: str, schema_description: str):
            raise AssertionError("not used")

    monkeypatch.setattr("app.dependencies.build_llm_provider", lambda config, **_: StubProvider())

    plugins = build_semantic_plugins(build_llm_test_config(default_use_case="agent_conversation_memory"))

    assert "agent_conversation_memory" in plugins
    assert plugins["agent_conversation_memory"].name == "agent_conversation_memory"
    assert "llm_agent_memory" in plugins


def test_legacy_env_values_still_map_to_llm_packages(monkeypatch, tmp_path: Path) -> None:
    env_file = tmp_path / ".env.local"
    env_file.write_text(
        "\n".join(
            [
                "PALLIUM_DEFAULT_USE_CASE=agent_conversation_memory",
                "PALLIUM_LLM_PROVIDER=openai_compatible",
                "PALLIUM_LLM_MODEL=legacy-model",
                "PALLIUM_LLM_BASE_URL=https://legacy.example/v1",
                "PALLIUM_LLM_API_KEY=legacy-key",
                f"PALLIUM_LLM_PROMPT_VARIANT={DEFAULT_PROMPT_VARIANT}",
                "PALLIUM_LLM_TIMEOUT_SECONDS=33",
                "PALLIUM_PROVIDER__LEGACY_DEFAULT__MAX_ATTEMPTS=5",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("PALLIUM_ENV_FILE", str(env_file))
    config = AppConfig.from_env()

    package = config.package_config("agent_conversation_memory")
    provider = config.provider_config("legacy_default")

    assert package.llm_provider == "legacy_default"
    assert package.model == "legacy-model"
    assert package.prompt_variant == DEFAULT_PROMPT_VARIANT
    assert provider.kind == "openai_compatible"
    assert provider.base_url == "https://legacy.example/v1"
    assert provider.api_key == "legacy-key"
    assert provider.timeout_seconds == 33.0
    assert provider.retry_policy.max_attempts == 5

def test_observability_debug_config_reads_toml_and_env_override(monkeypatch, tmp_path: Path) -> None:
    config_file = tmp_path / "pallium.local.toml"
    config_file.write_text(
        """
        default_use_case = "demo_agent_memory"

        [storage]
        backend = "sqlite"
        sqlite_url = "sqlite:///./configured.db"

        [observability]
        integration_debug = false
        """.strip(),
        encoding="utf-8",
    )

    monkeypatch.setenv("PALLIUM_CONFIG_FILE", str(config_file))
    monkeypatch.setenv("PALLIUM_OBSERVABILITY_INTEGRATION_DEBUG", "1")

    config = AppConfig.from_env()

    assert config.observability.integration_debug is True

def test_retention_config_reads_toml_and_env_override(monkeypatch, tmp_path: Path) -> None:
    config_file = tmp_path / "pallium.local.toml"
    config_file.write_text(
        """
        default_use_case = "demo_agent_memory"

        [storage]
        backend = "sqlite"
        sqlite_url = "sqlite:///./configured.db"

        [retention]
        enabled = false
        run_interval_seconds = 600
        lease_seconds = 420
        batch_size = 150
        """.strip(),
        encoding="utf-8",
    )

    monkeypatch.setenv("PALLIUM_CONFIG_FILE", str(config_file))
    monkeypatch.setenv("PALLIUM_RETENTION_ENABLED", "1")
    monkeypatch.setenv("PALLIUM_RETENTION_BATCH_SIZE", "80")

    config = AppConfig.from_env()

    assert config.retention.enabled is True
    assert config.retention.run_interval_seconds == 600
    assert config.retention.lease_seconds == 420
    assert config.retention.batch_size == 80


def test_prompt_variants_from_toml(monkeypatch, tmp_path: Path) -> None:
    config_file = tmp_path / "pallium.local.toml"
    config_file.write_text(
        """
        default_use_case = "agent_conversation_memory"

        [semantic_packages.agent_conversation_memory]
        implementation = "agent_conversation_memory"
        prompt_variant = "strict_decision_v1"

        [semantic_packages.agent_conversation_memory.prompt_variants]
        query_ambiguity_resolution = "qar_v1_compact_contract"
        write_extraction = "strict_typed_memory_v6_work_state_examples"
        """.strip(),
        encoding="utf-8",
    )

    monkeypatch.setenv("PALLIUM_CONFIG_FILE", str(config_file))
    config = AppConfig.from_env()
    package = config.package_config("agent_conversation_memory")

    assert package.prompt_variant == "strict_decision_v1"
    assert package.prompt_variants == {
        "query_ambiguity_resolution": "qar_v1_compact_contract",
        "write_extraction": "strict_typed_memory_v6_work_state_examples",
    }


def test_prompt_variants_role_specific_env_override(monkeypatch, tmp_path: Path) -> None:
    config_file = tmp_path / "pallium.local.toml"
    config_file.write_text(
        """
        default_use_case = "agent_conversation_memory"

        [semantic_packages.agent_conversation_memory]
        implementation = "agent_conversation_memory"
        prompt_variant = "strict_decision_v1"

        [semantic_packages.agent_conversation_memory.prompt_variants]
        query_ambiguity_resolution = "qar_v1_compact_contract"
        """.strip(),
        encoding="utf-8",
    )

    monkeypatch.setenv("PALLIUM_CONFIG_FILE", str(config_file))
    monkeypatch.setenv(
        "PALLIUM_PACKAGE__AGENT_CONVERSATION_MEMORY__PROMPT_VARIANTS__QUERY_AMBIGUITY_RESOLUTION",
        "qar_v1_compact_examples",
    )
    config = AppConfig.from_env()
    package = config.package_config("agent_conversation_memory")

    assert package.prompt_variants["query_ambiguity_resolution"] == "qar_v1_compact_examples"
    assert package.prompt_variant == "strict_decision_v1"


def test_prompt_variants_absent_inherits_package_default() -> None:
    from app.config import SemanticPackageConfig

    package = SemanticPackageConfig(
        name="test", implementation="test", prompt_variant="default_variant"
    )
    assert package.prompt_variants is None


def test_prompt_variants_legacy_fallback_unaffected(monkeypatch, tmp_path: Path) -> None:
    env_file = tmp_path / ".env.local"
    env_file.write_text(
        "\n".join(
            [
                "PALLIUM_DEFAULT_USE_CASE=agent_conversation_memory",
                "PALLIUM_LLM_PROVIDER=openai_compatible",
                "PALLIUM_LLM_MODEL=legacy-model",
                "PALLIUM_LLM_BASE_URL=https://legacy.example/v1",
                "PALLIUM_LLM_API_KEY=legacy-key",
                "PALLIUM_LLM_PROMPT_VARIANT=strict_decision_v1",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("PALLIUM_ENV_FILE", str(env_file))
    config = AppConfig.from_env()
    package = config.package_config("agent_conversation_memory")

    assert package.prompt_variant == "strict_decision_v1"
    assert package.prompt_variants is None


def test_resolve_prompt_variant_for_role() -> None:
    from semantic.llm_agent_memory import resolve_prompt_variant_for_role

    assert resolve_prompt_variant_for_role(
        "query_ambiguity_resolution",
        prompt_variants={"query_ambiguity_resolution": "qar_v1_compact_contract"},
        prompt_variant="strict_decision_v1",
    ) == "qar_v1_compact_contract"

    assert resolve_prompt_variant_for_role(
        "write_extraction",
        prompt_variants={"query_ambiguity_resolution": "qar_v1_compact_contract"},
        prompt_variant="strict_decision_v1",
    ) == "strict_decision_v1"

    assert resolve_prompt_variant_for_role(
        "write_extraction",
        prompt_variants=None,
        prompt_variant=None,
        default="fallback_default",
    ) == "fallback_default"


def test_resolver_enabled_defaults_to_true() -> None:
    from app.config import SemanticPackageConfig

    package = SemanticPackageConfig(name="test", implementation="test")
    assert package.resolver_enabled is True
    assert package.resolver_timeout_ms == 800


def test_resolver_enabled_from_toml(monkeypatch, tmp_path: Path) -> None:
    config_file = tmp_path / "pallium.local.toml"
    config_file.write_text(
        """
        default_use_case = "agent_conversation_memory"

        [semantic_packages.agent_conversation_memory]
        implementation = "agent_conversation_memory"
        resolver_enabled = false
        resolver_timeout_ms = 500
        """.strip(),
        encoding="utf-8",
    )

    monkeypatch.setenv("PALLIUM_CONFIG_FILE", str(config_file))
    config = AppConfig.from_env()
    package = config.package_config("agent_conversation_memory")

    assert package.resolver_enabled is False
    assert package.resolver_timeout_ms == 500


def test_resolver_enabled_env_override(monkeypatch, tmp_path: Path) -> None:
    config_file = tmp_path / "pallium.local.toml"
    config_file.write_text(
        """
        default_use_case = "agent_conversation_memory"

        [semantic_packages.agent_conversation_memory]
        implementation = "agent_conversation_memory"
        resolver_enabled = true
        """.strip(),
        encoding="utf-8",
    )

    monkeypatch.setenv("PALLIUM_CONFIG_FILE", str(config_file))
    monkeypatch.setenv("PALLIUM_PACKAGE__AGENT_CONVERSATION_MEMORY__RESOLVER_ENABLED", "false")
    config = AppConfig.from_env()
    package = config.package_config("agent_conversation_memory")

    assert package.resolver_enabled is False


# ---------------------------------------------------------------------------
# Embedding provider config parsing
# ---------------------------------------------------------------------------

def test_embedding_provider_config_from_toml(monkeypatch, tmp_path: Path) -> None:
    config_file = tmp_path / "pallium.local.toml"
    config_file.write_text(
        """
        default_use_case = "demo_agent_memory"

        [embedding_providers.local]
        kind = "fastembed"
        model = "BAAI/bge-small-en-v1.5"
        """.strip(),
        encoding="utf-8",
    )

    monkeypatch.setenv("PALLIUM_CONFIG_FILE", str(config_file))
    config = AppConfig.from_env()

    ep = config.embedding_provider_config("local")
    assert ep.kind == "fastembed"
    assert ep.model == "BAAI/bge-small-en-v1.5"
    assert ep.dimensions is None


def test_embedding_provider_config_with_dimensions(monkeypatch, tmp_path: Path) -> None:
    config_file = tmp_path / "pallium.local.toml"
    config_file.write_text(
        """
        default_use_case = "demo_agent_memory"

        [embedding_providers.local]
        kind = "fastembed"
        model = "BAAI/bge-small-en-v1.5"
        dimensions = 384
        """.strip(),
        encoding="utf-8",
    )

    monkeypatch.setenv("PALLIUM_CONFIG_FILE", str(config_file))
    config = AppConfig.from_env()

    ep = config.embedding_provider_config("local")
    assert ep.dimensions == 384


def test_embedding_provider_config_multiple(monkeypatch, tmp_path: Path) -> None:
    config_file = tmp_path / "pallium.local.toml"
    config_file.write_text(
        """
        default_use_case = "demo_agent_memory"

        [embedding_providers.local]
        kind = "fastembed"
        model = "BAAI/bge-small-en-v1.5"

        [embedding_providers.large]
        kind = "fastembed"
        model = "BAAI/bge-large-en-v1.5"
        dimensions = 1024
        """.strip(),
        encoding="utf-8",
    )

    monkeypatch.setenv("PALLIUM_CONFIG_FILE", str(config_file))
    config = AppConfig.from_env()

    assert "local" in config.embedding_providers
    assert "large" in config.embedding_providers
    assert config.embedding_provider_config("large").model == "BAAI/bge-large-en-v1.5"
    assert config.embedding_provider_config("large").dimensions == 1024


def test_embedding_provider_config_unknown_name_raises() -> None:
    config = AppConfig()
    with __import__("pytest").raises(KeyError, match="Unknown embedding provider config"):
        config.embedding_provider_config("nonexistent")


def test_embedding_providers_default_auto_created() -> None:
    config = AppConfig()
    assert "onnx" in config.embedding_providers
    default_ep = config.embedding_providers["onnx"]
    assert default_ep.kind == "onnx"
    assert default_ep.model == ""  # empty = use provider's built-in default


def test_embedding_provider_config_direct_construction() -> None:
    ep = EmbeddingProviderConfig(name="test", kind="fastembed", model="test-model")
    assert ep.name == "test"
    assert ep.kind == "fastembed"
    assert ep.model == "test-model"
    assert ep.dimensions is None


# ---------------------------------------------------------------------------
# Auth style config parsing
# ---------------------------------------------------------------------------

def test_auth_style_from_toml(monkeypatch, tmp_path: Path) -> None:
    config_file = tmp_path / "pallium.local.toml"
    config_file.write_text(
        """
        default_use_case = "demo_agent_memory"

        [llm_providers.hai_anthropic]
        kind = "anthropic_claude"
        base_url = "http://localhost:6655/anthropic/v1"
        api_key = "test-key"
        auth_style = "bearer"
        """.strip(),
        encoding="utf-8",
    )

    monkeypatch.setenv("PALLIUM_CONFIG_FILE", str(config_file))
    config = AppConfig.from_env()

    provider = config.provider_config("hai_anthropic")
    assert provider.auth_style == "bearer"


def test_auth_style_defaults_to_native() -> None:
    from app.config import LLMProviderConfig

    provider = LLMProviderConfig(name="test", kind="anthropic_claude", base_url="http://example.test")
    assert provider.auth_style == "native"


def test_auth_style_env_override(monkeypatch, tmp_path: Path) -> None:
    config_file = tmp_path / "pallium.local.toml"
    config_file.write_text(
        """
        default_use_case = "demo_agent_memory"

        [llm_providers.anthropic]
        kind = "anthropic_claude"
        base_url = "http://localhost:6655/anthropic/v1"
        api_key = "test-key"
        auth_style = "native"
        """.strip(),
        encoding="utf-8",
    )

    monkeypatch.setenv("PALLIUM_CONFIG_FILE", str(config_file))
    monkeypatch.setenv("PALLIUM_PROVIDER__ANTHROPIC__AUTH_STYLE", "bearer")
    config = AppConfig.from_env()

    provider = config.provider_config("anthropic")
    assert provider.auth_style == "bearer"


# ---------------------------------------------------------------------------
# Model roles config parsing
# ---------------------------------------------------------------------------

def test_model_roles_from_toml(monkeypatch, tmp_path: Path) -> None:
    config_file = tmp_path / "pallium.local.toml"
    config_file.write_text(
        """
        default_use_case = "agent_conversation_memory"

        [semantic_packages.agent_conversation_memory]
        implementation = "agent_conversation_memory"

        [semantic_packages.agent_conversation_memory.model_roles]
        write_extraction = "claude-sonnet"
        thread_aggregation = "claude-haiku"
        consolidation = "claude-haiku"
        query_ambiguity_resolution = "claude-haiku"
        """.strip(),
        encoding="utf-8",
    )

    monkeypatch.setenv("PALLIUM_CONFIG_FILE", str(config_file))
    config = AppConfig.from_env()
    package = config.package_config("agent_conversation_memory")

    assert package.model_roles == {
        "write_extraction": "claude-sonnet",
        "thread_aggregation": "claude-haiku",
        "consolidation": "claude-haiku",
        "query_ambiguity_resolution": "claude-haiku",
    }


def test_model_roles_defaults_to_none() -> None:
    from app.config import SemanticPackageConfig

    package = SemanticPackageConfig(name="test", implementation="test")
    assert package.model_roles is None


def test_model_roles_env_override(monkeypatch, tmp_path: Path) -> None:
    config_file = tmp_path / "pallium.local.toml"
    config_file.write_text(
        """
        default_use_case = "agent_conversation_memory"

        [semantic_packages.agent_conversation_memory]
        implementation = "agent_conversation_memory"

        [semantic_packages.agent_conversation_memory.model_roles]
        write_extraction = "claude-sonnet"
        """.strip(),
        encoding="utf-8",
    )

    monkeypatch.setenv("PALLIUM_CONFIG_FILE", str(config_file))
    monkeypatch.setenv(
        "PALLIUM_PACKAGE__AGENT_CONVERSATION_MEMORY__MODEL_ROLES__WRITE_EXTRACTION",
        "gpt-5-mini",
    )
    config = AppConfig.from_env()
    package = config.package_config("agent_conversation_memory")

    assert package.model_roles["write_extraction"] == "gpt-5-mini"


# ---------------------------------------------------------------------------
# Package enabled flag
# ---------------------------------------------------------------------------

def test_package_enabled_defaults_to_true() -> None:
    from app.config import SemanticPackageConfig

    package = SemanticPackageConfig(name="test", implementation="test")
    assert package.enabled is True


def test_package_enabled_false_from_toml(monkeypatch, tmp_path: Path) -> None:
    config_file = tmp_path / "pallium.local.toml"
    config_file.write_text(
        """
        default_use_case = "agent_conversation_memory"

        [semantic_packages.agent_conversation_memory]
        implementation = "agent_conversation_memory"

        [semantic_packages.conversational_knowledge]
        implementation = "conversational_knowledge"
        enabled = false
        """.strip(),
        encoding="utf-8",
    )

    monkeypatch.setenv("PALLIUM_CONFIG_FILE", str(config_file))
    config = AppConfig.from_env()

    acm = config.package_config("agent_conversation_memory")
    assert acm.enabled is True

    ck = config.package_config("conversational_knowledge")
    assert ck.enabled is False


def test_build_semantic_plugins_skips_disabled_package(monkeypatch) -> None:
    from app.config import SemanticPackageConfig
    from app.dependencies import build_semantic_plugins
    from tests.config_helpers import DEFAULT_CONSOLIDATION_POLICY

    class StubProvider:
        def generate_json(self, *, system_prompt: str, user_prompt: str, schema_description: str):
            raise AssertionError("not used")

    monkeypatch.setattr("app.dependencies.build_llm_provider", lambda config, **_: StubProvider())

    config = build_llm_test_config(default_use_case="agent_conversation_memory")
    assert "llm_agent_memory" in config.semantic_packages
    assert config.semantic_packages["llm_agent_memory"].enabled is True

    # Disable llm_agent_memory via a new config with enabled=False
    disabled_packages = dict(config.semantic_packages)
    original = disabled_packages["llm_agent_memory"]
    disabled_packages["llm_agent_memory"] = SemanticPackageConfig(
        name=original.name,
        implementation=original.implementation,
        enabled=False,
        llm_provider=original.llm_provider,
        model=original.model,
        prompt_variant=original.prompt_variant,
    )

    from dataclasses import replace
    config_with_disabled = replace(config, semantic_packages=disabled_packages)

    plugins = build_semantic_plugins(config_with_disabled)

    assert "llm_agent_memory" not in plugins
    assert "agent_conversation_memory" in plugins


def test_provider_api_key_file_from_toml(monkeypatch, tmp_path: Path) -> None:
    api_key_file = tmp_path / "hai_api_key"
    api_key_file.write_text("pelican-managed-key\n", encoding="utf-8")
    config_file = tmp_path / "pallium.local.toml"
    config_file.write_text(
        f"""
        default_use_case = "demo_agent_memory"

        [llm_providers.hai_anthropic]
        kind = "anthropic_claude"
        base_url = "http://localhost:6655/anthropic/v1"
        api_key_file = "{api_key_file.as_posix()}"
        auth_style = "bearer"
        """.strip(),
        encoding="utf-8",
    )

    monkeypatch.setenv("PALLIUM_CONFIG_FILE", str(config_file))

    config = AppConfig.from_env()

    provider = config.provider_config("hai_anthropic")
    assert provider.api_key_file == api_key_file.as_posix()
    assert provider.api_key == "pelican-managed-key"


def test_provider_api_key_file_env_override(monkeypatch, tmp_path: Path) -> None:
    api_key_file = tmp_path / "hai_api_key"
    api_key_file.write_text("env-file-key", encoding="utf-8")

    monkeypatch.setenv("PALLIUM_PROVIDER__HAI_ANTHROPIC__KIND", "anthropic_claude")
    monkeypatch.setenv("PALLIUM_PROVIDER__HAI_ANTHROPIC__BASE_URL", "http://localhost:6655/anthropic/v1")
    monkeypatch.setenv("PALLIUM_PROVIDER__HAI_ANTHROPIC__API_KEY_FILE", str(api_key_file))
    monkeypatch.setenv("PALLIUM_PROVIDER__HAI_ANTHROPIC__AUTH_STYLE", "bearer")

    config = AppConfig.from_env()

    provider = config.provider_config("hai_anthropic")
    assert provider.api_key_file == str(api_key_file)
    assert provider.api_key == "env-file-key"


def test_relay_sqlite_url_derivation_and_validation(tmp_path: Path) -> None:
    main = tmp_path / "main.sqlite"
    assert AppConfig(sqlite_url=f"sqlite:///{main}").resolved_relay_sqlite_url == f"sqlite:///{tmp_path / 'main-relay.sqlite'}"

    same = tmp_path / "nested" / ".." / "main.sqlite"
    with pytest.raises(ValueError, match="must differ"):
        AppConfig(
            sqlite_url=f"sqlite:///{main}",
            relay_sqlite_url=f"sqlite:///{same}",
        ).resolved_relay_sqlite_url
    with pytest.raises(ValueError, match="file-backed Relay"):
        AppConfig(
            sqlite_url=f"sqlite:///{main}",
            relay_sqlite_url="sqlite:///:memory:",
        ).resolved_relay_sqlite_url
    assert AppConfig(sqlite_url="sqlite:///:memory:").resolved_relay_sqlite_url == "sqlite:///:memory:"