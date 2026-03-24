from __future__ import annotations

from pathlib import Path

from app.config import AppConfig, LLMProviderConfig, SemanticPackageConfig
from app.main import create_app
from capabilities.consolidation import ConsolidationPolicy, DEFAULT_CONSOLIDATION_STRATEGIES
from storage.vector_index import VectorIndexConfig
from starlette.testclient import TestClient


DEFAULT_LLM_PROMPT_VARIANT = "strict_typed_memory_v5_compact_examples"
DEFAULT_AGENT_CONVERSATION_PROMPT_VARIANT = "strict_typed_memory_v6_work_state_examples"
DEFAULT_PROMPT_VARIANT = DEFAULT_LLM_PROMPT_VARIANT
DEFAULT_CONSOLIDATION_POLICY = ConsolidationPolicy(
    enabled_strategies=DEFAULT_CONSOLIDATION_STRATEGIES,
    default_strategy="thread_summary_anchored",
    max_candidates_per_run=24,
    max_group_size=4,
    same_container_required=True,
    time_window_hours=168,
    lexical_overlap_threshold=2,
)


def build_llm_test_config(
    *,
    default_use_case: str,
    sqlite_url: str = "sqlite:///./test.db",
    provider_name: str = "openai",
    provider_kind: str = "openai_compatible",
    model: str = "fake-model",
    prompt_variant: str | None = None,
    llm_agent_prompt_variant: str | None = None,
    agent_conversation_prompt_variant: str | None = None,
    agent_conversation_prompt_variants: dict[str, str] | None = None,
    base_url: str = "http://fake-provider.local",
) -> AppConfig:
    llm_prompt = prompt_variant or llm_agent_prompt_variant or DEFAULT_LLM_PROMPT_VARIANT
    agent_conversation_prompt = prompt_variant or agent_conversation_prompt_variant or DEFAULT_AGENT_CONVERSATION_PROMPT_VARIANT

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
                prompt_variant=llm_prompt,
            ),
            "agent_conversation_memory": SemanticPackageConfig(
                name="agent_conversation_memory",
                implementation="agent_conversation_memory",
                llm_provider=provider_name,
                model=model,
                prompt_variant=agent_conversation_prompt,
                prompt_variants=agent_conversation_prompt_variants,
                consolidation=DEFAULT_CONSOLIDATION_POLICY,
            ),
        },
        vector_index=VectorIndexConfig(enabled=False),
    )


def _vector_index_path_for_sqlite(sqlite_url: str) -> str:
    prefix = "sqlite:///"
    if not sqlite_url.startswith(prefix):
        return VectorIndexConfig().index_path
    db_path = Path(sqlite_url[len(prefix):])
    return str(db_path.with_suffix(".vector.index"))


def build_agent_conversation_client(
    monkeypatch,
    sqlite_url: str,
    *,
    llm_provider_factory=None,
    auto_drain: bool = False,
    drain_worker_id: str = "test-worker",
) -> TestClient:
    """Build a TestClient for agent_conversation_memory tests.

    Patches the LLM provider, creates a TestClient, and wraps ``post``
    to auto-inject ``visibility: "public"`` on /items, /query,
    and /query/debug endpoints.

    Parameters
    ----------
    auto_drain:
        When *True*, automatically drain the processing queue after
        successful ``/items`` ingests.
    drain_worker_id:
        Worker ID used when auto-draining.
    llm_provider_factory:
        Callable that returns an LLM provider stub.  When *None*,
        ``TieredMemorySemanticProvider()`` is used (imported lazily to
        avoid circular imports in config_helpers).
    """
    if llm_provider_factory is None:
        from tests.tiered_memory_stub_providers import TieredMemorySemanticProvider
        llm_provider_factory = TieredMemorySemanticProvider

    monkeypatch.setattr(
        "app.dependencies.build_llm_provider",
        lambda config, **_: llm_provider_factory(),
    )
    client = TestClient(
        create_app(
            build_llm_test_config(
                default_use_case="agent_conversation_memory",
                sqlite_url=sqlite_url,
            )
        )
    )
    original_post = client.post

    def post_with_public_visibility(url: str, *args, **kwargs):
        payload = kwargs.get("json")
        if isinstance(payload, dict) and url in {"/items", "/query", "/query/debug"} and "visibility" not in payload:
            payload = dict(payload)
            payload["visibility"] = "public"
            kwargs["json"] = payload
        elif isinstance(payload, list) and url == "/items":
            kwargs["json"] = [
                {**item, "visibility": "public"}
                if isinstance(item, dict) and "visibility" not in item
                else item
                for item in payload
            ]
        response = original_post(url, *args, **kwargs)
        if auto_drain and url == "/items" and response.status_code == 200:
            client.app.state.pallium_service.drain_processing_queue(worker_id=drain_worker_id)
        return response

    client.post = post_with_public_visibility
    return client