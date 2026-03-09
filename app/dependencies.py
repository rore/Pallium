from __future__ import annotations

from api.routes import create_router
from app.config import AppConfig
from core.service import PalliumService
from providers.llm.base import LLMProvider
from providers.llm.anthropic_claude import AnthropicClaudeLLMProvider
from providers.llm.openai_compatible import OpenAICompatibleLLMProvider
from retrieval.base import RetrievalProvider
from retrieval.lexical import LexicalRetrievalProvider
from semantic.base import SemanticPlugin
from semantic.demo_agent_memory import DemoAgentMemoryPlugin
from semantic.llm_agent_memory import LLMAgentMemoryPlugin
from storage.base import StorageProvider
from storage.sqlite import SQLiteStorageProvider


def build_storage_provider(config: AppConfig) -> StorageProvider:
    if config.storage_backend != "sqlite":
        raise ValueError(f"Unsupported storage backend: {config.storage_backend}")
    return SQLiteStorageProvider(database_url=config.sqlite_url)


def build_llm_provider(config: AppConfig) -> LLMProvider | None:
    if not config.llm_provider:
        return None
    if not config.llm_model or not config.llm_base_url:
        raise ValueError("LLM provider configuration requires model and base URL")

    provider_name = config.llm_provider.lower()
    if provider_name == "openai_compatible":
        return OpenAICompatibleLLMProvider(
            model=config.llm_model,
            base_url=config.llm_base_url,
            api_key=config.llm_api_key,
            timeout_seconds=config.llm_timeout_seconds,
        )
    if provider_name in {"anthropic_claude", "claude", "anthropic"}:
        return AnthropicClaudeLLMProvider(
            model=config.llm_model,
            base_url=config.llm_base_url,
            api_key=config.llm_api_key,
            timeout_seconds=config.llm_timeout_seconds,
        )

    raise ValueError(f"Unsupported LLM provider: {config.llm_provider}")


def build_semantic_plugins(config: AppConfig) -> dict[str, SemanticPlugin]:
    demo_plugin = DemoAgentMemoryPlugin()
    plugins: dict[str, SemanticPlugin] = {demo_plugin.name: demo_plugin}

    llm_provider = build_llm_provider(config)
    if llm_provider is not None:
        llm_plugin = LLMAgentMemoryPlugin(provider=llm_provider)
        plugins[llm_plugin.name] = llm_plugin

    return plugins


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
