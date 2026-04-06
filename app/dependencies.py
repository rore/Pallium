from __future__ import annotations

import logging
from pathlib import Path

from api.routes import create_router
from app.config import AppConfig, EmbeddingProviderConfig, SemanticPackageConfig
from core.observability import IntegrationDebugLogger
from core.service import PalliumService
from providers.embedding.base import EmbeddingProvider
from providers.llm.aicore_anthropic import AICoreAnthropicLLMProvider
from providers.llm.aicore_auth import AICoreDeploymentCatalog, AICoreTokenProvider
from providers.llm.anthropic_claude import AnthropicClaudeLLMProvider
from providers.llm.base import LLMProvider
from providers.llm.openai_compatible import OpenAICompatibleLLMProvider
from retrieval.base import RetrievalProvider
from retrieval.lexical import LexicalRetrievalProvider
from retrieval.vector import VectorRetrievalProvider
from semantic.base import SemanticPlugin
from semantic.agent_conversation_memory import AgentConversationMemoryPlugin
from semantic.agent_conversation_memory_routing import RoutingOverrides
from semantic.demo_agent_memory import DemoAgentMemoryPlugin
from semantic.llm_agent_memory import LLMAgentMemoryPlugin
from storage.base import StorageProvider
from storage.sqlite import SQLiteStorageProvider
from storage.vector_index import VectorIndex, VectorIndexConfig

logger = logging.getLogger(__name__)


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
            auth_style=provider_config.auth_style,
            max_tokens=provider_config.max_tokens,
        )

    if provider_kind == "aicore_anthropic":
        aicore_cfg = provider_config.aicore
        if not aicore_cfg:
            raise ValueError(
                f"LLM provider '{provider_name}' (kind=aicore_anthropic) "
                "requires an [aicore] configuration sub-table"
            )
        token_provider = AICoreTokenProvider(
            client_id=aicore_cfg.client_id,
            client_secret=aicore_cfg.client_secret,
            auth_url=aicore_cfg.auth_url,
            timeout_seconds=provider_config.timeout_seconds,
        )
        deployment_catalog = AICoreDeploymentCatalog(
            base_url=aicore_cfg.base_url,
            resource_group=aicore_cfg.resource_group,
            token_provider=token_provider,
            timeout_seconds=provider_config.timeout_seconds,
        )
        return AICoreAnthropicLLMProvider(
            provider_name=provider_name,
            model=model,
            base_url=aicore_cfg.base_url,
            resource_group=aicore_cfg.resource_group,
            token_provider=token_provider,
            deployment_catalog=deployment_catalog,
            timeout_seconds=provider_config.timeout_seconds,
            retry_policy=provider_config.retry_policy,
            max_tokens=provider_config.max_tokens,
        )

    raise ValueError(f"Unsupported LLM provider kind: {provider_config.kind}")


def build_embedding_provider(config: AppConfig, *, provider_name: str) -> EmbeddingProvider:
    """Build an EmbeddingProvider from config. Dispatches on ``kind``."""
    provider_config: EmbeddingProviderConfig = config.embedding_provider_config(provider_name)

    provider_kind = provider_config.kind.lower()
    if provider_kind == "fastembed":
        from providers.embedding.fastembed_provider import FastEmbedProvider

        return FastEmbedProvider(
            model=provider_config.model,
            dimensions=provider_config.dimensions,
        )

    if provider_kind == "onnx":
        from providers.embedding.onnx_provider import OnnxEmbeddingProvider

        return OnnxEmbeddingProvider(
            model=provider_config.model,
            dimensions=provider_config.dimensions,
            cache_dir=provider_config.cache_dir,
            query_prefix=provider_config.query_prefix,
            passage_prefix=provider_config.passage_prefix,
        )

    raise ValueError(f"Unsupported embedding provider kind: {provider_config.kind}")


def build_semantic_plugins(config: AppConfig, routing_overrides: RoutingOverrides | None = None) -> dict[str, SemanticPlugin]:
    plugins: dict[str, SemanticPlugin] = {}

    for package_name, package_config in config.semantic_packages.items():
        plugin = _build_plugin_for_package(config=config, package_config=package_config, routing_overrides=routing_overrides)
        if plugin is not None:
            plugins[package_name] = plugin

    if "demo_agent_memory" not in plugins:
        demo_plugin = DemoAgentMemoryPlugin()
        plugins[demo_plugin.name] = demo_plugin

    return plugins


def _build_plugin_for_package(*, config: AppConfig, package_config: SemanticPackageConfig, routing_overrides: RoutingOverrides | None = None) -> SemanticPlugin | None:
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
        providers_by_role = _resolve_providers_by_role(config, package_config, provider)
        default_prompt_variant = "strict_typed_memory_v5_compact_examples" if implementation == "llm_agent_memory" else "strict_typed_memory_v6_work_state_examples"
        prompt_variant = package_config.prompt_variant or default_prompt_variant
        if implementation == "llm_agent_memory":
            return LLMAgentMemoryPlugin(provider=providers_by_role.get("write_extraction", provider), prompt_variant=prompt_variant)
        return AgentConversationMemoryPlugin(
            provider=provider,
            prompt_variant=prompt_variant,
            consolidation_config=package_config.consolidation,
            routing_overrides=routing_overrides,
            providers_by_role=providers_by_role or None,
        )

    if implementation == "conversational_knowledge":
        if not package_config.llm_provider or not package_config.model:
            return None
        provider = build_llm_provider(
            config,
            provider_name=package_config.llm_provider,
            model=package_config.model,
        )
        providers_by_role = _resolve_providers_by_role(config, package_config, provider)
        from semantic.conversational_knowledge import ConversationalKnowledgePlugin
        return ConversationalKnowledgePlugin(
            provider=provider,
            providers_by_role=providers_by_role or None,
        )

    raise ValueError(f"Unsupported semantic package implementation: {implementation}")


def _resolve_providers_by_role(
    config: AppConfig,
    package_config: SemanticPackageConfig,
    default_provider: LLMProvider,
) -> dict[str, LLMProvider]:
    if not package_config.model_roles:
        return {}
    by_role: dict[str, LLMProvider] = {}
    provider_cache: dict[str, LLMProvider] = {}
    if package_config.model:
        provider_cache[package_config.model] = default_provider
    for role, role_model in package_config.model_roles.items():
        if role_model not in provider_cache:
            provider_cache[role_model] = build_llm_provider(
                config, provider_name=package_config.llm_provider, model=role_model,
            )
        by_role[role] = provider_cache[role_model]
    return by_role


def _build_resolver_config(*, provider: LLMProvider, package_config: SemanticPackageConfig) -> dict[str, object] | None:
    if not package_config.resolver_enabled:
        return None
    from semantic.llm_agent_memory import resolve_prompt_variant_for_role
    prompt_variant = resolve_prompt_variant_for_role(
        "query_ambiguity_resolution",
        prompt_variants=package_config.prompt_variants,
        prompt_variant=package_config.prompt_variant,
        default="qar_v1_compact_contract",
    )
    return {
        "resolver_enabled": package_config.resolver_enabled,
        "resolver_timeout_ms": package_config.resolver_timeout_ms,
        "prompt_variant": prompt_variant,
        "provider": provider,
    }


def build_retrieval_provider(storage: StorageProvider) -> RetrievalProvider:
    return LexicalRetrievalProvider(storage)


def build_service(
    config: AppConfig | None = None,
    routing_overrides: RoutingOverrides | None = None,
    *,
    enable_vector: bool = True,
) -> PalliumService:
    resolved_config = config or AppConfig.from_env()
    storage = build_storage_provider(resolved_config)
    plugins = build_semantic_plugins(resolved_config, routing_overrides=routing_overrides)
    if resolved_config.default_use_case not in plugins:
        raise ValueError(f"Unsupported default use case: {resolved_config.default_use_case}")
    retrieval = build_retrieval_provider(storage)

    # Vector retrieval (enabled by default, can be disabled for processor subprocesses)
    vector_retrieval: VectorRetrievalProvider | None = None
    vector_index: VectorIndex | None = None
    embedding_provider: EmbeddingProvider | None = None
    vector_config = resolved_config.vector_index

    if vector_config.enabled and enable_vector:
        # 1. Build embedding provider
        if not vector_config.embedding_provider:
            logger.error("Vector index enabled but no embedding_provider configured. Vector disabled.")
        else:
            try:
                embedding_provider = build_embedding_provider(
                    resolved_config,
                    provider_name=vector_config.embedding_provider,
                )
            except Exception as exc:
                logger.error("Vector embedding provider failed to initialize: %s. Vector disabled.", exc)
                embedding_provider = None

        # 2. Load or create vector index
        if embedding_provider is not None:
            vector_index = _load_or_create_vector_index(vector_config, embedding_provider)

        # 3. Model consistency check
        if vector_index is not None and embedding_provider is not None:
            if vector_index.entry_count() > 0:
                if vector_index.model_name != embedding_provider.model_name():
                    logger.error(
                        "Vector index model mismatch: index=%s, provider=%s. "
                        "Vector disabled. Run rebuild-vector-index.",
                        vector_index.model_name,
                        embedding_provider.model_name(),
                    )
                    vector_index = None
                    embedding_provider = None

        # 4. Count reconciliation check — warn but continue; runtime reconciliation fills gaps
        if vector_index is not None and embedding_provider is not None:
            sqlite_count = storage.count_index_entries_by_type("vector")
            index_count = vector_index.entry_count()
            if sqlite_count != index_count:
                logger.warning(
                    "Vector index count mismatch: SQLite=%d, index=%d. "
                    "Continuing with reduced recall; runtime reconciliation will backfill.",
                    sqlite_count,
                    index_count,
                )

        # 5. Build VectorRetrievalProvider
        if vector_index is not None and embedding_provider is not None:
            vector_retrieval = VectorRetrievalProvider(
                storage=storage,
                vector_index=vector_index,
                embedding_provider=embedding_provider,
                min_similarity=vector_config.min_similarity,
            )

    # Wrap lexical + vector into composite retrieval if vector is available
    if vector_retrieval is not None:
        from retrieval.composite import CompositeRetrievalProvider
        retrieval = CompositeRetrievalProvider(
            lexical=retrieval,
            vector=vector_retrieval,
        )

    # Build type registry from plugins that support type registration
    from core.type_registry import TypeRegistry
    type_registry = TypeRegistry()
    for plugin in plugins.values():
        register_routing_types = getattr(plugin, "register_routing_types", None)
        if callable(register_routing_types):
            register_routing_types(type_registry)

    return PalliumService(
        storage=storage,
        retrieval=retrieval,
        semantic_plugins=plugins,
        default_use_case=resolved_config.default_use_case,
        observability=IntegrationDebugLogger(enabled=resolved_config.observability.integration_debug),
        retention_enabled=resolved_config.retention.enabled,
        retention_lease_seconds=resolved_config.retention.lease_seconds,
        retention_batch_size=resolved_config.retention.batch_size,
        embedding_provider=embedding_provider,
        vector_index=vector_index,
        type_registry=type_registry if len(type_registry) > 0 else None,
        routing_overrides=routing_overrides,
    )


def _load_or_create_vector_index(
    config: VectorIndexConfig,
    embedding_provider: EmbeddingProvider,
) -> VectorIndex | None:
    """Load an existing vector index or create a new empty one.

    Returns ``None`` if usearch is not installed or the index cannot be loaded.
    """
    index_path = Path(config.index_path)
    try:
        if index_path.exists() and Path(f"{index_path}.meta.json").exists():
            return VectorIndex.load(index_path)
        else:
            return VectorIndex.create_empty(
                index_path,
                dimensions=embedding_provider.dimensions(),
                model_name=embedding_provider.model_name(),
            )
    except ImportError:
        logger.error("usearch not installed. Vector index disabled. pip install usearch")
        return None
    except Exception as exc:
        logger.error("Failed to load vector index: %s. Vector disabled.", exc)
        return None


def build_router(service: PalliumService):
    return create_router(service)

