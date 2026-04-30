from __future__ import annotations

import os

import pytest

from app.config import AppConfig
from app.dependencies import build_llm_provider
from core.models import SourceItem
from semantic.common import SEMANTIC_SIGNAL_METADATA_KEY
from semantic.llm_agent_memory import LLMAgentMemoryPlugin


ENABLE_ENV = "PALLIUM_RUN_LIVE_LLM_TESTS"


def _build_live_plugin() -> LLMAgentMemoryPlugin:
    if os.getenv(ENABLE_ENV) != "1":
        pytest.skip(f"Set {ENABLE_ENV}=1 to run live LLM semantic smoke tests.")

    config = AppConfig.from_env()
    package = config.package_config("llm_agent_memory")
    if not package.llm_provider or not package.model:
        pytest.skip("llm_agent_memory is not configured with a real provider/model.")

    provider_config = config.provider_config(package.llm_provider)
    if not provider_config.base_url or not provider_config.api_key:
        pytest.skip("Real LLM provider credentials are not available in the current config.")

    provider = build_llm_provider(config, provider_name=package.llm_provider, model=package.model)
    return LLMAgentMemoryPlugin(provider=provider, prompt_variant=package.prompt_variant or "strict_typed_memory_v4_evidence_guarded")


@pytest.fixture(scope="module")
def live_plugin() -> LLMAgentMemoryPlugin:
    return _build_live_plugin()


def test_live_llm_promotes_explicit_comparative_verdict(live_plugin: LLMAgentMemoryPlugin) -> None:
    source_item = SourceItem(
        source_type="assistant_output",
        source_id="live-verdict-001",
        content_type="text/plain",
        content=(
            "Verdict: transaction-transformer had the most significant recent ledger changes. "
            "It touched more tickets, files, and core transaction flows than ledger-query."
        ),
        artifact_kind="assistant_output",
        role="assistant",
    )

    result = live_plugin.process_item(source_item)

    assert result.memory_objects[0].type == "investigation_outcome"
    investigation_text = str(result.memory_objects[0].payload["investigation_outcome"]).lower()
    assert "transaction-transformer" in investigation_text
    assert "significant" in investigation_text or "more" in investigation_text

    signals = result.source_item_metadata_updates[source_item.id][SEMANTIC_SIGNAL_METADATA_KEY]
    key_finding = str(signals.get("key_finding_text") or "").lower()
    assert "transaction-transformer" in key_finding


def test_live_llm_extracts_constraint_and_next_step_signals_from_plain_text(live_plugin: LLMAgentMemoryPlugin) -> None:
    source_item = SourceItem(
        source_type="assistant_output",
        source_id="live-signals-001",
        content_type="text/plain",
        content=(
            "Constraint: do not open a browser or use Jira/Slack auth. "
            "Work only from the local repos. "
            "Blocker: browser and SSO-backed services are unavailable in this environment. "
            "Progress: the latest ledger changes were already summarized locally. "
            "Next step: compare ledger-query vs transaction-transformer locally and explain which repo changed more."
        ),
        artifact_kind="assistant_output",
        role="assistant",
    )

    result = live_plugin.process_item(source_item)

    assert result.memory_objects[0].type == "turn_summary"
    signals = result.source_item_metadata_updates[source_item.id][SEMANTIC_SIGNAL_METADATA_KEY]
    constraint_text = str(signals.get("constraint_text") or "").lower()
    blocker_text = str(signals.get("blocker_text") or "").lower()
    progress_text = str(signals.get("progress_text") or "").lower()
    next_step_text = str(signals.get("next_step_text") or "").lower()
    assert "browser" in constraint_text or "local repos" in constraint_text
    assert "sso" in blocker_text or "browser" in blocker_text
    assert "summarized" in progress_text or "ledger changes" in progress_text
    assert "compare ledger-query" in next_step_text or "repo changed more" in next_step_text


def test_live_llm_flags_low_value_meta_chatter(live_plugin: LLMAgentMemoryPlugin) -> None:
    source_item = SourceItem(
        source_type="assistant_output",
        source_id="live-meta-001",
        content_type="text/plain",
        content="Task complete. No Slack message needed. Nothing new to report.",
        artifact_kind="assistant_output",
        role="assistant",
    )

    result = live_plugin.process_item(source_item)

    assert result.memory_objects[0].type == "turn_summary"
    signals = result.source_item_metadata_updates[source_item.id][SEMANTIC_SIGNAL_METADATA_KEY]
    assert signals.get("is_low_value_meta") is True
    assert signals.get("constraint_text") is None
    assert signals.get("next_step_text") is None
    assert signals.get("blocker_text") is None
    assert signals.get("progress_text") is None
    assert signals.get("key_finding_text") is None


def test_live_llm_does_not_turn_monitoring_status_into_key_finding(live_plugin: LLMAgentMemoryPlugin) -> None:
    source_item = SourceItem(
        source_type="status_update",
        source_id="live-status-001",
        content_type="text/plain",
        content="Catalog sync delay increased after the provider restart, and we should watch it closely tonight.",
        artifact_kind="notification",
        role="assistant",
    )

    result = live_plugin.process_item(source_item)

    assert result.memory_objects[0].type == "turn_summary"
    signals = result.source_item_metadata_updates[source_item.id][SEMANTIC_SIGNAL_METADATA_KEY]
    assert signals.get("key_finding_text") is None
