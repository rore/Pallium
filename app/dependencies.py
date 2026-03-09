from __future__ import annotations

from api.routes import create_router
from app.config import AppConfig
from core.service import PalliumService
from retrieval.base import RetrievalProvider
from retrieval.lexical import LexicalRetrievalProvider
from semantic.base import SemanticPlugin
from semantic.demo_agent_memory import DemoAgentMemoryPlugin
from storage.base import StorageProvider
from storage.sqlite import SQLiteStorageProvider


def build_storage_provider(config: AppConfig) -> StorageProvider:
    if config.storage_backend != "sqlite":
        raise ValueError(f"Unsupported storage backend: {config.storage_backend}")
    return SQLiteStorageProvider(database_url=config.sqlite_url)


def build_semantic_plugins() -> dict[str, SemanticPlugin]:
    plugin = DemoAgentMemoryPlugin()
    return {plugin.name: plugin}


def build_retrieval_provider(storage: StorageProvider) -> RetrievalProvider:
    return LexicalRetrievalProvider(storage)


def build_service(config: AppConfig | None = None) -> PalliumService:
    resolved_config = config or AppConfig.from_env()
    storage = build_storage_provider(resolved_config)
    plugins = build_semantic_plugins()
    retrieval = build_retrieval_provider(storage)
    return PalliumService(
        storage=storage,
        retrieval=retrieval,
        semantic_plugins=plugins,
        default_use_case=resolved_config.default_use_case,
    )


def build_router(service: PalliumService):
    return create_router(service)
