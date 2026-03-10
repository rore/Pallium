from __future__ import annotations

from app.config import AppConfig, LLMProviderConfig, SemanticPackageConfig


DEFAULT_PROMPT_VARIANT = "strict_typed_memory_v4_evidence_guarded"


def build_llm_test_config(
    *,
    default_use_case: str,
    sqlite_url: str = "sqlite:///./test.db",
    provider_name: str = "openai",
    provider_kind: str = "openai_compatible",
    model: str = "fake-model",
    prompt_variant: str = DEFAULT_PROMPT_VARIANT,
    base_url: str = "http://fake-provider.local",
) -> AppConfig:
    return AppConfig(
        storage_backend="sqlite",
        sqlite_url=sqlite_url,
        default_use_case=default_use_case,
        llm_providers={
            provider_name: LLMProviderConfig(
                name=provider_name,
                kind=provider_kind,
                base_url=base_url,
                api_key="test-key",
                timeout_seconds=30.0,
            )
        },
        semantic_packages={
            "llm_agent_memory": SemanticPackageConfig(
                name="llm_agent_memory",
                implementation="llm_agent_memory",
                llm_provider=provider_name,
                model=model,
                prompt_variant=prompt_variant,
            ),
            "agent_conversation_memory": SemanticPackageConfig(
                name="agent_conversation_memory",
                implementation="agent_conversation_memory",
                llm_provider=provider_name,
                model=model,
                prompt_variant=prompt_variant,
            ),
        },
    )
