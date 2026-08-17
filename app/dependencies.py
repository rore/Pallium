from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from api.routes import create_router
from app.config import AppConfig, EmbeddingProviderConfig, SemanticPackageConfig
from core.observability import IntegrationDebugLogger, QueryStats
from core.service import PalliumService
from core.vector_index_holder import VectorIndexHolder
from providers.embedding.base import EmbeddingProvider
from providers.llm.aicore_anthropic import AICoreAnthropicLLMProvider
from providers.llm.aicore_auth import AICoreDeploymentCatalog, AICoreTokenProvider
from providers.llm.anthropic_claude import AnthropicClaudeLLMProvider
from providers.llm.base import LLMProvider
from providers.llm.openai_compatible import OpenAICompatibleLLMProvider
from providers.llm.redacting_wrapper import RedactingLLMProviderWrapper
from retrieval.base import RetrievalProvider
from retrieval.lexical import LexicalRetrievalProvider
from retrieval.vector import VectorRetrievalProvider
from semantic.base import SemanticPlugin
from semantic.agent_conversation_memory import AgentConversationMemoryPlugin
from semantic.agent_work_trace import AgentWorkTracePlugin
from semantic.agent_conversation_memory_routing import RoutingOverrides
from semantic.demo_agent_memory import DemoAgentMemoryPlugin
from semantic.llm_agent_memory import LLMAgentMemoryPlugin
from storage.base import StorageProvider
from storage.sqlite import SQLiteStorageProvider
from storage.vector_index import VectorIndex, VectorIndexConfig

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BuildResult:
    service: PalliumService
    storage: StorageProvider
    index_holder: VectorIndexHolder
    rebuild_needed: bool
    rebuild_reason: str
    index_path: Path | None
    embedding_provider: EmbeddingProvider | None


def build_storage_provider(config: AppConfig) -> StorageProvider:
    if config.storage_backend != "sqlite":
        raise ValueError(f"Unsupported storage backend: {config.storage_backend}")
    return SQLiteStorageProvider(database_url=config.sqlite_url)


def build_llm_provider(config: AppConfig, *, provider_name: str, model: str) -> LLMProvider:
    """Construct an LLM provider from config, wrapped in the shared
    redaction barrier (:class:`RedactingLLMProviderWrapper`).

    The wrapper redacts every string leaf of the model's response
    before returning it. This closes the leak channel that would
    otherwise let LLM-extracted memory (thread_summary,
    task_checkpoint, investigation_outcome, task_trace, ...) carry
    a secret directly into ``MemoryObject.payload`` even after the
    write barrier at ingest redacted the source.

    Every provider path (openai_compatible, anthropic_claude,
    aicore_anthropic) is wrapped uniformly — the barrier's presence
    is not a per-provider choice.
    """
    provider_config = config.provider_config(provider_name)
    if not provider_config.base_url:
        raise ValueError(f"LLM provider '{provider_name}' requires a base URL")

    provider_kind = provider_config.kind.lower()
    inner: LLMProvider
    if provider_kind == "openai_compatible":
        inner = OpenAICompatibleLLMProvider(
            provider_name=provider_name,
            model=model,
            base_url=provider_config.base_url,
            api_key=provider_config.api_key,
            timeout_seconds=provider_config.timeout_seconds,
            retry_policy=provider_config.retry_policy,
        )
    elif provider_kind in {"anthropic_claude", "claude", "anthropic"}:
        inner = AnthropicClaudeLLMProvider(
            provider_name=provider_name,
            model=model,
            base_url=provider_config.base_url,
            api_key=provider_config.api_key,
            timeout_seconds=provider_config.timeout_seconds,
            retry_policy=provider_config.retry_policy,
            auth_style=provider_config.auth_style,
            max_tokens=provider_config.max_tokens,
        )
    elif provider_kind == "aicore_anthropic":
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
        inner = AICoreAnthropicLLMProvider(
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
    else:
        raise ValueError(f"Unsupported LLM provider kind: {provider_config.kind}")

    return RedactingLLMProviderWrapper(inner)


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

        kwargs: dict[str, Any] = {
            "cache_dir": provider_config.cache_dir,
            "query_prefix": provider_config.query_prefix,
            "passage_prefix": provider_config.passage_prefix,
            "max_tokens": provider_config.max_tokens,
        }
        if provider_config.model:
            kwargs["model"] = provider_config.model
        if provider_config.dimensions is not None:
            kwargs["dimensions"] = provider_config.dimensions
        return OnnxEmbeddingProvider(**kwargs)

    raise ValueError(f"Unsupported embedding provider kind: {provider_config.kind}")


def build_semantic_plugins(config: AppConfig, routing_overrides: RoutingOverrides | None = None) -> dict[str, SemanticPlugin]:
    plugins: dict[str, SemanticPlugin] = {}

    for package_name, package_config in config.semantic_packages.items():
        if not package_config.enabled:
            continue
        plugin = _build_plugin_for_package(config=config, package_config=package_config, routing_overrides=routing_overrides)
        if plugin is not None:
            plugins[package_name] = plugin

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

    if implementation == "agent_work_trace":
        if not package_config.llm_provider or not package_config.model:
            return None
        provider = build_llm_provider(
            config,
            provider_name=package_config.llm_provider,
            model=package_config.model,
        )
        return AgentWorkTracePlugin(
            provider=provider,
            operational_fact_derivation_enabled=(
                config.features.operational_fact_derivation
            ),
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
        # Default: use sonnet for fact_consolidation (contradiction detection
        # needs stronger reasoning than haiku provides — tested P=0.94 R=1.00
        # vs haiku P=0.82 R=0.82). Override via model_roles config if needed.
        if "fact_consolidation" not in providers_by_role and package_config.model:
            sonnet_model = _upgrade_to_sonnet(package_config.model)
            if sonnet_model != package_config.model:
                providers_by_role["fact_consolidation"] = build_llm_provider(
                    config, provider_name=package_config.llm_provider, model=sonnet_model,
                )
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
    _apply_role_defaults(by_role)
    return by_role


_LIGHTWEIGHT_ROLE_DEFAULTS: dict[str, tuple[str, ...]] = {
    "note_extraction": ("consolidation", "thread_aggregation", "query_ambiguity_resolution"),
}


def _apply_role_defaults(by_role: dict[str, LLMProvider]) -> None:
    """Fill in missing roles from existing ones in the same tier."""
    for role, donors in _LIGHTWEIGHT_ROLE_DEFAULTS.items():
        if role not in by_role:
            for donor in donors:
                if donor in by_role:
                    by_role[role] = by_role[donor]
                    break


def _upgrade_to_sonnet(model: str) -> str:
    """Derive a sonnet model identifier from a haiku one.

    Returns the original model unchanged if it doesn't contain 'haiku'.
    """
    if "haiku" in model:
        return model.replace("haiku", "sonnet")
    return model


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
    query_stats: QueryStats | None = None,
    metrics_store=None,
) -> BuildResult:
    resolved_config = config or AppConfig.from_env()
    storage = build_storage_provider(resolved_config)
    plugins = build_semantic_plugins(resolved_config, routing_overrides=routing_overrides)

    active_names = list(plugins.keys())
    logger.info("Active semantic packages: %s", ", ".join(active_names) if active_names else "(none)")

    if resolved_config.default_use_case not in plugins:
        raise ValueError(f"Unsupported default use case: {resolved_config.default_use_case}")
    retrieval = build_retrieval_provider(storage)

    # Vector retrieval (enabled by default, can be disabled for processor subprocesses)
    vector_retrieval: VectorRetrievalProvider | None = None
    vector_index: VectorIndex | None = None
    embedding_provider: EmbeddingProvider | None = None
    index_holder: VectorIndexHolder | None = None
    vector_config = resolved_config.vector_index
    rebuild_needed = False
    rebuild_reason = ""

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

        # Create holder early — rebuild coordinator will swap into it
        if vector_index is not None:
            index_holder = VectorIndexHolder(vector_index)

        # 3. Model/schema consistency check — detect need, don't block
        if vector_index is not None and embedding_provider is not None:
            from semantic.agent_conversation_memory_embedding import EMBEDDING_SCHEMA_VERSION

            if vector_index.entry_count() > 0:
                if vector_index.model_name != embedding_provider.model_name():
                    rebuild_needed = True
                    rebuild_reason = f"model changed: {vector_index.model_name} -> {embedding_provider.model_name()}"
                elif vector_index.embedding_schema_version != EMBEDDING_SCHEMA_VERSION:
                    rebuild_needed = True
                    rebuild_reason = f"schema version: {vector_index.embedding_schema_version} -> {EMBEDDING_SCHEMA_VERSION}"

        # Check for pending rebuild from prior crash
        if not rebuild_needed and vector_config.enabled and enable_vector:
            from core.rebuild_coordinator import RebuildCoordinator
            pending = RebuildCoordinator.has_pending_rebuild(Path(vector_config.index_path))
            if pending is not None and pending.status == "in_progress":
                rebuild_needed = True
                rebuild_reason = f"resuming: {pending.reason}"

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
            effective_min_similarity = vector_config.min_similarity
            if effective_min_similarity is None:
                effective_min_similarity = embedding_provider.recommended_min_similarity()

            vector_retrieval = VectorRetrievalProvider(
                storage=storage,
                embedding_provider=embedding_provider,
                min_similarity=effective_min_similarity,
                index_holder=index_holder,
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

    # Shadow-only sub-task selector (REPORT6 validation experiment). Default
    # off. Reuses the default package's LLM provider/model. If the default
    # package has no LLM provider, or the provider fails to build, the shadow
    # stays disabled (runner=None) — never blocks startup.
    shadow_subtask_selector = None
    obs = resolved_config.observability
    if obs.shadow_subtask_selector_enabled:
        pkg = resolved_config.semantic_packages.get(resolved_config.default_use_case)
        if pkg is not None and pkg.llm_provider and pkg.model:
            try:
                from semantic.agent_conversation_memory_subtask_selector_shadow import (
                    SubtaskSelectorShadowRunner,
                )
                selector_provider = build_llm_provider(
                    resolved_config, provider_name=pkg.llm_provider, model=pkg.model,
                )
                shadow_subtask_selector = SubtaskSelectorShadowRunner(
                    storage=storage,
                    provider=selector_provider,
                    model=pkg.model,
                    timeout_ms=obs.shadow_subtask_selector_timeout_ms,
                )
                logger.info("Shadow sub-task selector ENABLED (model=%s)", pkg.model)
            except Exception:
                logger.warning("Shadow sub-task selector disabled: provider build failed", exc_info=True)
        else:
            logger.warning(
                "Shadow sub-task selector enabled but default package '%s' has no LLM provider; disabled",
                resolved_config.default_use_case,
            )

    service = PalliumService(
        storage=storage,
        retrieval=retrieval,
        semantic_plugins=plugins,
        default_use_case=resolved_config.default_use_case,
        observability=IntegrationDebugLogger(enabled=resolved_config.observability.integration_debug),
        retention_enabled=resolved_config.retention.enabled,
        retention_lease_seconds=resolved_config.retention.lease_seconds,
        retention_batch_size=resolved_config.retention.batch_size,
        embedding_provider=embedding_provider,
        index_holder=index_holder,
        type_registry=type_registry if len(type_registry) > 0 else None,
        routing_overrides=routing_overrides,
        query_stats=query_stats,
        metrics_store=metrics_store,
        metrics_retention_days=resolved_config.observability.metrics_retention_days,
        # Phase 3a (2026-06-27): per-type / per-container abstention policy.
        # Default is empty → bit-exact no-op vs prior behaviour. See
        # docs/specs/2026-06-27-injection-policy-abstention.md.
        injection_policy=resolved_config.injection.policy,
        shadow_subtask_selector=shadow_subtask_selector,
    )

    return BuildResult(
        service=service,
        storage=storage,
        index_holder=index_holder or VectorIndexHolder(),
        rebuild_needed=rebuild_needed,
        rebuild_reason=rebuild_reason,
        index_path=Path(vector_config.index_path) if vector_config.enabled else None,
        embedding_provider=embedding_provider,
    )


def _load_or_create_vector_index(
    config: VectorIndexConfig,
    embedding_provider: EmbeddingProvider,
) -> VectorIndex | None:
    """Load an existing vector index or create a new empty one.

    Returns ``None`` if usearch is not installed or the index cannot be loaded.
    """
    from semantic.agent_conversation_memory_embedding import EMBEDDING_SCHEMA_VERSION

    index_path = Path(config.index_path)
    try:
        if index_path.exists() and Path(f"{index_path}.meta.json").exists():
            return VectorIndex.load(index_path)
        else:
            return VectorIndex.create_empty(
                index_path,
                dimensions=embedding_provider.dimensions(),
                model_name=embedding_provider.model_name(),
                embedding_schema_version=EMBEDDING_SCHEMA_VERSION,
            )
    except ImportError:
        logger.error("usearch not installed. Vector index disabled. pip install usearch")
        return None
    except Exception as exc:
        logger.error("Failed to load vector index: %s. Vector disabled.", exc)
        return None


def build_router(service: PalliumService, *, audit_log_enabled: bool = False):
    return create_router(service, audit_log_enabled=audit_log_enabled)

