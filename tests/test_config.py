from __future__ import annotations

from pathlib import Path

from app.config import AppConfig


def test_app_config_loads_from_env_file_and_env_overrides(monkeypatch, tmp_path: Path) -> None:
    env_file = tmp_path / ".env.local"
    env_file.write_text(
        "\n".join(
            [
                "PALLIUM_DEFAULT_USE_CASE=llm_agent_memory",
                "PALLIUM_LLM_PROVIDER=openai_compatible",
                "PALLIUM_LLM_MODEL=file-model",
                "PALLIUM_LLM_BASE_URL=https://file.example/v1",
                "PALLIUM_LLM_API_KEY=file-key",
                "PALLIUM_LLM_PROMPT_VARIANT=strict_decision_v1",
                "PALLIUM_LLM_TIMEOUT_SECONDS=45",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("PALLIUM_ENV_FILE", str(env_file))
    monkeypatch.setenv("PALLIUM_LLM_MODEL", "env-model")

    config = AppConfig.from_env()

    assert config.default_use_case == "llm_agent_memory"
    assert config.llm_provider == "openai_compatible"
    assert config.llm_model == "env-model"
    assert config.llm_base_url == "https://file.example/v1"
    assert config.llm_api_key == "file-key"
    assert config.llm_prompt_variant == "strict_decision_v1"
    assert config.llm_timeout_seconds == 45.0
