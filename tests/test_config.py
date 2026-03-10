from __future__ import annotations

from pathlib import Path

from app.config import AppConfig
from tests.config_helpers import DEFAULT_PROMPT_VARIANT, build_llm_test_config


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

        [semantic_packages.agent_conversation_memory]
        implementation = "agent_conversation_memory"
        llm_provider = "openai"
        model = "file-model"
        prompt_variant = "strict_decision_v1"
        """.strip(),
        encoding="utf-8",
    )

    monkeypatch.setenv("PALLIUM_CONFIG_FILE", str(config_file))
    monkeypatch.setenv("PALLIUM_OPENAI_API_KEY", "file-key")
    monkeypatch.setenv("PALLIUM_PACKAGE__AGENT_CONVERSATION_MEMORY__MODEL", "env-model")

    config = AppConfig.from_env()

    assert config.default_use_case == "agent_conversation_memory"
    assert config.sqlite_url == "sqlite:///./configured.db"
    assert config.package_config("agent_conversation_memory").model == "env-model"
    assert config.package_config("agent_conversation_memory").prompt_variant == "strict_decision_v1"
    provider = config.provider_config("openai")
    assert provider.kind == "openai_compatible"
    assert provider.base_url == "https://file.example/v1"
    assert provider.api_key == "file-key"
    assert provider.timeout_seconds == 45.0


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

