from __future__ import annotations

from api.routes import create_router
from app.config import AppConfig, SemanticPackageConfig
from core.service import PalliumService
from providers.llm.anthropic_claude import AnthropicClaudeLLMProvider
from providers.llm.base import LLMProvider
from providers.llm.openai_compatible import OpenAICompatibleLLMProvider
from retrieval.base import RetrievalProvider
from retrieval.lexical import LexicalRetrievalProvider
from semantic.base import SemanticPlugin
from semantic.agent_conversation_memory import AgentConversationMemoryPlugin
from semantic.demo_agent_memory import DemoAgentMemoryPlugin
from semantic.llm_agent_memory import LLMAgentMemoryPlugin
from storage.base import StorageProvider
from storage.sqlite import SQLiteStorageProvider


def build_storage_provider(config: AppConfig) -> StorageProvider:
    if config.storage_backend != "sqlite":
        raise ValueError(f"Unsupported storage backend: {config.storage_backend}")
    return SQLiteStorageProvider(database_url=config.sqlite_url)


def build_llm_provider(config: AppConfig, *, provider_name: str, model: str) -> LLMProvider:
    provider_config = config.provider_config(provider_name)
    if not provider_config.base_url:
        raise ValueError(f"LLM provider '{provider_name}' requires a base URL")

    provider_kind = provider_config.kind.lower()
    if provider_kind == "openai_compatible":
        return OpenAICompatibleLLMProvider(
            provider_name=provider_name,
            model=model,
            base_url=provider_config.base_url,
            api_key=provider_config.api_key,
            timeout_seconds=provider_config.timeout_seconds,
            retry_policy=provider_config.retry_policy,
        )
    if provider_kind in {"anthropic_claude", "claude", "anthropic"}:
        return AnthropicClaudeLLMProvider(
            provider_name=provider_name,
            model=model,
            base_url=provider_config.base_url,
            api_key=provider_config.api_key,
            timeout_seconds=provider_config.timeout_seconds,
            retry_policy=provider_config.retry_policy,
        )

    raise ValueError(f"Unsupported LLM provider kind: {provider_config.kind}")


def build_semantic_plugins(config: AppConfig) -> dict[str, SemanticPlugin]:
    plugins: dict[str, SemanticPlugin] = {}

    for package_name, package_config in config.semantic_packages.items():
        plugin = _build_plugin_for_package(config=config, package_config=package_config)
        if plugin is not None:
            plugins[package_name] = plugin

    if "demo_agent_memory" not in plugins:
        demo_plugin = DemoAgentMemoryPlugin()
        plugins[demo_plugin.name] = demo_plugin

    return plugins


def _build_plugin_for_package(*, config: AppConfig, package_config: SemanticPackageConfig) -> SemanticPlugin | None:
    implementation = package_config.implementation
    if implementation == "demo_agent_memory":
        return DemoAgentMemoryPlugin()

    if implementation in {"llm_agent_memory", "agent_conversation_memory"}:
        if not package_config.llm_provider or not package_config.model:
            return None
        provider = build_llm_provider(
            config,
            provider_name=package_config.llm_provider,
            model=package_config.model,
        )
        prompt_variant = package_config.prompt_variant or "strict_typed_memory_v4_evidence_guarded"
        if implementation == "llm_agent_memory":
            return LLMAgentMemoryPlugin(provider=provider, prompt_variant=prompt_variant)
        return AgentConversationMemoryPlugin(
            provider=provider,
            prompt_variant=prompt_variant,
            consolidation_config=package_config.consolidation,
        )

    raise ValueError(f"Unsupported semantic package implementation: {implementation}")


def build_retrieval_provider(storage: StorageProvider) -> RetrievalProvider:
    return LexicalRetrievalProvider(storage)


def build_service(config: AppConfig | None = None) -> PalliumService:
    resolved_config = config or AppConfig.from_env()
    storage = build_storage_provider(resolved_config)
    plugins = build_semantic_plugins(resolved_config)
    if resolved_config.default_use_case not in plugins:
        raise ValueError(f"Unsupported default use case: {resolved_config.default_use_case}")
    retrieval = build_retrieval_provider(storage)
    return PalliumService(
        storage=storage,
        retrieval=retrieval,
        semantic_plugins=plugins,
        default_use_case=resolved_config.default_use_case,
    )


def build_router(service: PalliumService):
    return create_router(service)
