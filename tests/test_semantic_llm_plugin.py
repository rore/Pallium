from __future__ import annotations

import pytest

from core.models import MemorySubjectAnchor, SourceItem
from semantic.common import (
    _normalize_for_containment,
    has_grounded_decision_evidence,
    has_grounded_investigation_evidence,
)


def test_normalize_for_containment_collapses_whitespace() -> None:
    assert _normalize_for_containment("hello   world") == "hello world"
    assert _normalize_for_containment("hello\nworld") == "hello world"
    assert _normalize_for_containment("hello\r\n  world") == "hello world"
    assert _normalize_for_containment("  Hello  WORLD  ") == "hello world"


def test_grounded_decision_evidence_tolerates_whitespace_normalization() -> None:
    source = SourceItem(
        source_type="note", source_id="ws-1", content_type="text/plain",
        content="Decision: use item\n  event time for\n  reservation ordering.",
    )
    assert has_grounded_decision_evidence(source, "Decision: use item event time for reservation ordering.") is True


def test_grounded_decision_evidence_rejects_fabricated_quote() -> None:
    source = SourceItem(
        source_type="note", source_id="fab-1", content_type="text/plain",
        content="We discussed reservation ordering approaches.",
    )
    assert has_grounded_decision_evidence(source, "Decision: use item event time for reservation ordering.") is False


def test_grounded_investigation_evidence_requires_source_containment() -> None:
    source = SourceItem(
        source_type="note", source_id="inv-1", content_type="text/plain",
        content="Investigation found that arrival-time ordering missed hold updates.",
    )
    assert has_grounded_investigation_evidence(source, "Investigation found that arrival-time ordering missed hold updates.") is True
    assert has_grounded_investigation_evidence(source, "Investigation found something completely different.") is False


def test_grounded_decision_evidence_accepts_llm_extracted_substance_without_prefix() -> None:
    """LLM may extract the decision substance without the 'Decision:' prefix."""
    source = SourceItem(
        source_type="note", source_id="llm-1", content_type="text/plain",
        content="Decision: use item event time for reservation ordering.",
    )
    assert has_grounded_decision_evidence(source, "use item event time for reservation ordering.") is True


def test_grounded_investigation_evidence_accepts_llm_extracted_substance_without_prefix() -> None:
    """LLM may extract investigation substance without 'Investigation found that' prefix."""
    source = SourceItem(
        source_type="note", source_id="llm-2", content_type="text/plain",
        content="Investigation found that arrival-time ordering missed hold updates.",
    )
    assert has_grounded_investigation_evidence(source, "arrival-time ordering missed hold updates.") is True


def test_grounded_investigation_evidence_tolerates_whitespace_normalization() -> None:
    source = SourceItem(
        source_type="note", source_id="inv-ws-1", content_type="text/plain",
        content="Investigation found that\n  arrival-time ordering missed\n  hold updates.",
    )
    assert has_grounded_investigation_evidence(source, "Investigation found that arrival-time ordering missed hold updates.") is True


# ---------------------------------------------------------------------------
# Multilingual write-time grounding
# ---------------------------------------------------------------------------

def test_grounded_decision_evidence_hebrew_exact_containment() -> None:
    source = SourceItem(
        source_type="note", source_id="he-1", content_type="text/plain",
        content="החלטה: להשתמש בזמן האירוע של הפריט לסידור ההזמנות.",
    )
    assert has_grounded_decision_evidence(source, "להשתמש בזמן האירוע של הפריט לסידור ההזמנות") is True


def test_grounded_decision_evidence_hebrew_whitespace_variation() -> None:
    source = SourceItem(
        source_type="note", source_id="he-ws-1", content_type="text/plain",
        content="החלטה: להשתמש בזמן\n  האירוע של הפריט\n  לסידור ההזמנות.",
    )
    assert has_grounded_decision_evidence(source, "להשתמש בזמן האירוע של הפריט לסידור ההזמנות") is True


def test_grounded_decision_evidence_hebrew_niqud_mismatch() -> None:
    """Source has niqud (vowel marks), evidence does not — grounding should succeed."""
    source = SourceItem(
        source_type="note", source_id="he-niqud-1", content_type="text/plain",
        content="הַחְלָטָה: לְהִשְׁתַּמֵּשׁ בִּזְמַן הָאֵירוּעַ שֶׁל הַפְּרִיט.",
    )
    assert has_grounded_decision_evidence(source, "להשתמש בזמן האירוע של הפריט") is True


def test_grounded_decision_evidence_mixed_script_literal_grounding() -> None:
    """Mixed Hebrew + English evidence succeeds when literally grounded."""
    source = SourceItem(
        source_type="note", source_id="mixed-1", content_type="text/plain",
        content="החלטה: להשתמש ב-FastAPI לשרת ה-API.",
    )
    assert has_grounded_decision_evidence(source, "להשתמש ב-FastAPI לשרת ה-API") is True


def test_grounded_decision_evidence_rejects_translated_evidence() -> None:
    """English evidence must not match Hebrew source — translation is not grounding."""
    source = SourceItem(
        source_type="note", source_id="trans-1", content_type="text/plain",
        content="החלטה: להשתמש בזמן האירוע של הפריט לסידור ההזמנות.",
    )
    assert has_grounded_decision_evidence(source, "use item event time for reservation ordering") is False


def test_grounded_decision_evidence_rejects_paraphrased_evidence() -> None:
    """Paraphrased Hebrew evidence is not grounded even if semantically equivalent."""
    source = SourceItem(
        source_type="note", source_id="para-1", content_type="text/plain",
        content="החלטה: להשתמש בזמן האירוע של הפריט לסידור ההזמנות.",
    )
    assert has_grounded_decision_evidence(source, "בחרנו לסדר הזמנות לפי זמן האירוע של הפריט") is False


def test_grounded_decision_evidence_arabic_exact_containment() -> None:
    source = SourceItem(
        source_type="note", source_id="ar-1", content_type="text/plain",
        content="القرار: استخدام وقت الحدث للعنصر لترتيب الطلبات.",
    )
    assert has_grounded_decision_evidence(source, "استخدام وقت الحدث للعنصر لترتيب الطلبات") is True


def test_grounded_decision_evidence_arabic_tashkeel_mismatch() -> None:
    """Source has tashkeel (vowel marks), evidence does not — grounding should succeed."""
    source = SourceItem(
        source_type="note", source_id="ar-tashkeel-1", content_type="text/plain",
        content="القَرَارُ: اِسْتِخْدَامُ وَقْتِ الحَدَثِ لِلْعُنْصُرِ لِتَرْتِيبِ الطَّلَبَاتِ.",
    )
    assert has_grounded_decision_evidence(source, "استخدام وقت الحدث للعنصر لترتيب الطلبات") is True


def test_grounded_decision_evidence_arabic_rejects_paraphrase() -> None:
    source = SourceItem(
        source_type="note", source_id="ar-para-1", content_type="text/plain",
        content="القرار: استخدام وقت الحدث للعنصر لترتيب الطلبات.",
    )
    assert has_grounded_decision_evidence(source, "اخترنا ترتيب الطلبات بحسب وقت حدث العنصر") is False


def test_grounded_decision_evidence_french_exact_containment() -> None:
    source = SourceItem(
        source_type="note", source_id="fr-1", content_type="text/plain",
        content="Décision: utiliser le temps de l'événement pour le tri des réservations.",
    )
    assert has_grounded_decision_evidence(source, "utiliser le temps de l'événement pour le tri des réservations") is True


def test_grounded_decision_evidence_french_diacritic_mismatch() -> None:
    """Source has accented characters, evidence drops accents — grounding should succeed."""
    source = SourceItem(
        source_type="note", source_id="fr-accent-1", content_type="text/plain",
        content="Décision: utiliser le temps de l'événement pour le tri des réservations.",
    )
    assert has_grounded_decision_evidence(source, "utiliser le temps de l'evenement pour le tri des reservations") is True


def test_grounded_decision_evidence_french_rejects_paraphrase() -> None:
    source = SourceItem(
        source_type="note", source_id="fr-para-1", content_type="text/plain",
        content="Décision: utiliser le temps de l'événement pour le tri des réservations.",
    )
    assert has_grounded_decision_evidence(source, "on a choisi de trier les réservations par horodatage") is False


def test_grounded_investigation_evidence_cyrillic_exact_containment() -> None:
    source = SourceItem(
        source_type="note", source_id="ru-1", content_type="text/plain",
        content="Вывод: использовать время события для сортировки заказов.",
    )
    assert has_grounded_investigation_evidence(source, "использовать время события для сортировки заказов") is True


def test_grounded_investigation_evidence_cyrillic_whitespace_variation() -> None:
    source = SourceItem(
        source_type="note", source_id="ru-ws-1", content_type="text/plain",
        content="Вывод: использовать время\n  события для\n  сортировки заказов.",
    )
    assert has_grounded_investigation_evidence(source, "использовать время события для сортировки заказов") is True


def test_grounded_investigation_evidence_cyrillic_rejects_translation() -> None:
    source = SourceItem(
        source_type="note", source_id="ru-trans-1", content_type="text/plain",
        content="Вывод: использовать время события для сортировки заказов.",
    )
    assert has_grounded_investigation_evidence(source, "use event time for order sorting") is False


from providers.llm.base import LLMCallMetadata, LLMJsonResponse, LLMProviderError
from semantic.common import SEMANTIC_SIGNAL_METADATA_KEY
from semantic.llm_agent_memory import DEFAULT_PROMPT_VARIANT, LLMAgentMemoryPlugin, build_analysis_request
from semantic.prompt_roles import get_prompt_role_contract


WRITE_EXTRACTION_PROMPT_ROLE = get_prompt_role_contract("write_extraction")

class StubLLMProvider:
    def __init__(self, *, response: LLMJsonResponse | None = None, error: Exception | None = None) -> None:
        self._response = response
        self._error = error
        self.last_system_prompt: str | None = None

    def generate_json(self, *, system_prompt: str, user_prompt: str, schema_description: str) -> LLMJsonResponse:
        self.last_system_prompt = system_prompt
        if self._error is not None:
            raise self._error
        assert self._response is not None
        return self._response


def test_llm_plugin_promotes_decision_memory_from_valid_extraction() -> None:
    plugin = LLMAgentMemoryPlugin(
        provider=StubLLMProvider(
            response=LLMJsonResponse(
                raw_text='{"summary":"Decision discussion","candidate_type":"decision","decision_text":"use item item event time reservation ordering","decision_evidence_text":"Decision: use item item event time reservation ordering","investigation_text":null,"investigation_evidence_text":null,"rationale_text":"to avoid missed hold updates","is_low_value_meta":false,"constraint_text":null,"next_step_text":null,"blocker_text":null,"progress_text":null,"key_finding_text":null}',
                metadata=LLMCallMetadata(provider_name="stub_provider", provider_kind="stub_kind", model="stub-model"),
                parsed_json={
                    "summary": "Decision discussion",
                    "candidate_type": "decision",
                    "decision_text": "use item item event time reservation ordering",
                    "decision_evidence_text": "Decision: use item item event time reservation ordering",
                    "investigation_text": None,
                    "investigation_evidence_text": None,
                    "rationale_text": "to avoid missed hold updates",
                    "is_low_value_meta": False,
                    "constraint_text": None,
                    "next_step_text": None,
                    "blocker_text": None,
                    "progress_text": None,
                    "key_finding_text": None,
                },
            )
        )
    )
    source_item = SourceItem(
        source_type="decision_note",
        source_id="decision-123",
        content_type="text/plain",
        content="Decision: use item item event time reservation ordering for reservation ordering to avoid missed hold updates.",
    )

    result = plugin.process_item(source_item)

    assert result.memory_objects[0].type == "decision"
    assert result.memory_objects[0].schema_id == "llm.decision"
    assert result.memory_objects[0].payload["decision"] == "use item item event time reservation ordering"
    assert result.memory_objects[0].payload["decision_evidence_text"] == "Decision: use item item event time reservation ordering"
    assert result.memory_objects[0].payload["semantic_provenance"]["prompt_role"] == WRITE_EXTRACTION_PROMPT_ROLE.role
    assert result.memory_objects[0].payload["semantic_provenance"]["prompt_schema_id"] == WRITE_EXTRACTION_PROMPT_ROLE.schema_id
    assert result.memory_objects[0].payload["semantic_provenance"]["prompt_schema_version"] == WRITE_EXTRACTION_PROMPT_ROLE.schema_version
    assert result.memory_objects[0].payload["semantic_provenance"]["prompt_variant"] == DEFAULT_PROMPT_VARIANT
    assert result.memory_objects[0].payload["semantic_provenance"]["model_role"] == WRITE_EXTRACTION_PROMPT_ROLE.default_model_role
    assert result.memory_objects[0].payload["semantic_provenance"]["provider_name"] == "stub_provider"
    assert result.memory_objects[0].payload["semantic_provenance"]["provider_kind"] == "stub_kind"
    assert result.memory_objects[0].payload["semantic_provenance"]["model"] == "stub-model"


def test_llm_plugin_promotes_investigation_outcome_from_explicit_verdict_extraction() -> None:
    plugin = LLMAgentMemoryPlugin(
        provider=StubLLMProvider(
            response=LLMJsonResponse(
                raw_text='{"summary":"Comparative verdict","candidate_type":"investigation_outcome","decision_text":null,"decision_evidence_text":null,"investigation_text":"transaction-transformer had the most significant recent ledger changes","investigation_evidence_text":"Here\'s the verdict: transaction-transformer had the most significant recent ledger changes by a wide margin.","rationale_text":"because it touched more tickets, files, and transaction flows","is_low_value_meta":false,"constraint_text":null,"next_step_text":null,"blocker_text":null,"progress_text":null,"key_finding_text":"transaction-transformer had the most significant recent ledger changes because it touched more tickets, files, and transaction flows than ledger-query"}',
                metadata=LLMCallMetadata(provider_name="stub_provider", provider_kind="stub_kind", model="stub-model"),
                parsed_json={
                    "summary": "Comparative verdict",
                    "candidate_type": "investigation_outcome",
                    "decision_text": None,
                    "decision_evidence_text": None,
                    "investigation_text": "transaction-transformer had the most significant recent ledger changes",
                    "investigation_evidence_text": "Here's the verdict: transaction-transformer had the most significant recent ledger changes by a wide margin.",
                    "rationale_text": "because it touched more tickets, files, and transaction flows",
                    "is_low_value_meta": False,
                    "constraint_text": None,
                    "next_step_text": None,
                    "blocker_text": None,
                    "progress_text": None,
                    "key_finding_text": "transaction-transformer had the most significant recent ledger changes because it touched more tickets, files, and transaction flows than ledger-query",
                },
            )
        )
    )
    source_item = SourceItem(
        source_type="assistant_output",
        source_id="investigation-verdict-123",
        content_type="text/plain",
        content="Here's the verdict: transaction-transformer had the most significant recent ledger changes by a wide margin. It touched more tickets, files, and transaction flows than ledger-query.",
        artifact_kind="assistant_output",
        role="assistant",
    )

    result = plugin.process_item(source_item)

    assert result.memory_objects[0].type == "investigation_outcome"
    assert result.memory_objects[0].payload["investigation_outcome"] == "transaction-transformer had the most significant recent ledger changes"
    assert result.memory_objects[0].payload["investigation_evidence_text"] == "Here's the verdict: transaction-transformer had the most significant recent ledger changes by a wide margin."
    assert result.source_item_metadata_updates[source_item.id][SEMANTIC_SIGNAL_METADATA_KEY]["key_finding_text"].startswith("transaction-transformer")


def test_llm_plugin_preserves_valid_subject_hints_and_ignores_invalid_entries() -> None:
    plugin = LLMAgentMemoryPlugin(
        provider=StubLLMProvider(
            response=LLMJsonResponse(
                raw_text='{"summary":"Decision discussion","candidate_type":"decision","decision_text":"use item item event time reservation ordering","decision_evidence_text":"Decision: use item item event time reservation ordering","investigation_text":null,"investigation_evidence_text":null,"rationale_text":"to avoid missed hold updates","is_low_value_meta":false,"constraint_text":null,"next_step_text":null,"blocker_text":null,"progress_text":null,"key_finding_text":null,"subject_hints":[{"kind":"component","value":"reservation ordering"},{"kind":"surface","value":"   catalog sync   "},{"kind":"unknown","value":"ignored"},{"kind":"component","value":"unknown"},{"kind":"bad_kind","value":"ignored"},{"kind":"workstream","value":""}]}',
                metadata=LLMCallMetadata(provider_name="stub_provider", provider_kind="stub_kind", model="stub-model"),
                parsed_json={
                    "summary": "Decision discussion",
                    "candidate_type": "decision",
                    "decision_text": "use item item event time reservation ordering",
                    "decision_evidence_text": "Decision: use item item event time reservation ordering",
                    "investigation_text": None,
                    "investigation_evidence_text": None,
                    "rationale_text": "to avoid missed hold updates",
                    "is_low_value_meta": False,
                    "constraint_text": None,
                    "next_step_text": None,
                    "blocker_text": None,
                    "progress_text": None,
                    "key_finding_text": None,
                    "subject_hints": [
                        {"kind": "component", "value": "reservation ordering"},
                        {"kind": "surface", "value": "   catalog sync   "},
                        {"kind": "unknown", "value": "ignored"},
                        {"kind": "component", "value": "unknown"},
                        {"kind": "bad_kind", "value": "ignored"},
                        {"kind": "workstream", "value": ""},
                    ],
                },
            )
        )
    )
    source_item = SourceItem(
        source_type="decision_note",
        source_id="decision-subjects-123",
        content_type="text/plain",
        content="Decision: use item item event time reservation ordering for reservation ordering to avoid missed hold updates.",
    )

    trace = plugin.analyze_item(source_item)

    assert trace.extraction.subject_hints == (
        MemorySubjectAnchor(kind="component", value="reservation ordering"),
        MemorySubjectAnchor(kind="surface", value="catalog sync"),
    )





def test_llm_plugin_returns_internal_signals_and_metadata_patch_from_single_call() -> None:
    provider = StubLLMProvider(
        response=LLMJsonResponse(
            raw_text='{"summary":"Local-only operating plan","candidate_type":null,"decision_text":null,"decision_evidence_text":null,"investigation_text":null,"investigation_evidence_text":null,"rationale_text":null,"is_low_value_meta":false,"constraint_text":"No browser auth, no Jira or Slack auth; use the local repos only and ask the user directly for anything behind those services.","next_step_text":"Compare ledger-query vs transaction-transformer locally and explain which repo changed more.","blocker_text":"Browser and SSO-backed services are unavailable in this environment.","progress_text":"The latest ledger changes were already summarized across the local repos.","key_finding_text":"transaction-transformer expanded transaction coverage while ledger-query focused on export and ADX plumbing"}',
            parsed_json={
                "summary": "Local-only operating plan",
                "candidate_type": None,
                "decision_text": None,
                "decision_evidence_text": None,
                "investigation_text": None,
                "investigation_evidence_text": None,
                "rationale_text": None,
                "is_low_value_meta": False,
                "constraint_text": "No browser auth, no Jira or Slack auth; use the local repos only and ask the user directly for anything behind those services.",
                "next_step_text": "Compare ledger-query vs transaction-transformer locally and explain which repo changed more.",
                "blocker_text": "Browser and SSO-backed services are unavailable in this environment.",
                "progress_text": "The latest ledger changes were already summarized across the local repos.",
                "key_finding_text": "transaction-transformer expanded transaction coverage while ledger-query focused on export and ADX plumbing",
            },
        )
    )
    plugin = LLMAgentMemoryPlugin(provider=provider)
    source_item = SourceItem(
        source_type="assistant_output",
        source_id="signal-rich-1",
        content_type="text/plain",
        content="No browser auth, no Jira or Slack auth. Use the local repos only. I already summarized the latest ledger changes; next I should compare ledger-query vs transaction-transformer locally and explain which repo changed more.",
        artifact_kind="assistant_output",
        role="assistant",
    )

    trace = plugin.analyze_item(source_item)

    assert trace.process_result.memory_objects[0].type == "discussion_summary"
    semantic_signals = trace.process_result.source_item_metadata_updates[source_item.id][SEMANTIC_SIGNAL_METADATA_KEY]
    assert semantic_signals["constraint_text"].startswith("No browser auth")
    assert semantic_signals["next_step_text"].startswith("Compare ledger-query")
    assert semantic_signals["blocker_text"].startswith("Browser and SSO")
    assert semantic_signals["progress_text"].startswith("The latest ledger changes")
    assert semantic_signals["key_finding_text"].startswith("transaction-transformer expanded")
    assert trace.process_result.source_item_metadata_updates == {
        source_item.id: {SEMANTIC_SIGNAL_METADATA_KEY: semantic_signals}
    }


def test_llm_plugin_flags_low_value_meta_without_promoting_typed_memory() -> None:
    provider = StubLLMProvider(
        response=LLMJsonResponse(
            raw_text='{"summary":"No durable update.","candidate_type":null,"decision_text":null,"decision_evidence_text":null,"investigation_text":null,"investigation_evidence_text":null,"rationale_text":null,"is_low_value_meta":true,"constraint_text":null,"next_step_text":null,"blocker_text":null,"progress_text":null,"key_finding_text":null}',
            parsed_json={
                "summary": "No durable update.",
                "candidate_type": None,
                "decision_text": None,
                "decision_evidence_text": None,
                "investigation_text": None,
                "investigation_evidence_text": None,
                "rationale_text": None,
                "is_low_value_meta": True,
                "constraint_text": None,
                "next_step_text": None,
                "blocker_text": None,
                "progress_text": None,
                "key_finding_text": None,
            },
        )
    )
    plugin = LLMAgentMemoryPlugin(provider=provider)
    source_item = SourceItem(
        source_type="assistant_output",
        source_id="meta-1",
        content_type="text/plain",
        content="Task complete. No Slack message needed. Nothing new to report.",
        artifact_kind="assistant_output",
        role="assistant",
    )

    result = plugin.process_item(source_item)

    assert result.memory_objects == []
    assert result.thread_rebuild_requested is False
    assert result.source_item_metadata_updates[source_item.id][SEMANTIC_SIGNAL_METADATA_KEY]["is_low_value_meta"] is True


def test_llm_plugin_promotes_investigation_outcome_from_valid_extraction() -> None:
    plugin = LLMAgentMemoryPlugin(
        provider=StubLLMProvider(
            response=LLMJsonResponse(
                raw_text='{"summary":"Investigation summary","candidate_type":"investigation_outcome","decision_text":null,"decision_evidence_text":null,"investigation_text":"arrival-time ordering missed hold updates during sync delays","investigation_evidence_text":"Investigation found that arrival-time ordering missed hold updates during sync delays","rationale_text":"because the catalog provider delivered updates late","is_low_value_meta":false,"constraint_text":null,"next_step_text":null,"blocker_text":null,"progress_text":null,"key_finding_text":"arrival-time ordering missed hold updates during sync delays because the catalog provider delivered updates late"}',
                metadata=LLMCallMetadata(provider_name="stub_provider", provider_kind="stub_kind", model="stub-model"),
                parsed_json={
                    "summary": "Investigation summary",
                    "candidate_type": "investigation_outcome",
                    "decision_text": None,
                    "decision_evidence_text": None,
                    "investigation_text": "arrival-time ordering missed hold updates during sync delays",
                    "investigation_evidence_text": "Investigation found that arrival-time ordering missed hold updates during sync delays",
                    "rationale_text": "because the catalog provider delivered updates late",
                    "is_low_value_meta": False,
                    "constraint_text": None,
                    "next_step_text": None,
                    "blocker_text": None,
                    "progress_text": None,
                    "key_finding_text": "arrival-time ordering missed hold updates during sync delays because the catalog provider delivered updates late",
                },
            )
        )
    )
    source_item = SourceItem(
        source_type="investigation_summary",
        source_id="investigation-123",
        content_type="text/plain",
        content="Investigation found that arrival-time ordering missed hold updates during sync delays.",
        artifact_kind="tool_use_summary",
    )

    result = plugin.process_item(source_item)

    assert result.memory_objects[0].type == "investigation_outcome"
    assert result.memory_objects[0].payload["investigation_outcome"] == "arrival-time ordering missed hold updates during sync delays"
    assert result.memory_objects[0].payload["investigation_evidence_text"] == "Investigation found that arrival-time ordering missed hold updates during sync delays"


def test_llm_plugin_uses_discussion_summary_when_typed_output_lacks_evidence_text() -> None:
    plugin = LLMAgentMemoryPlugin(
        provider=StubLLMProvider(
            response=LLMJsonResponse(
                raw_text='{"summary":"We discussed reservation ordering","candidate_type":"investigation_outcome","decision_text":null,"decision_evidence_text":null,"investigation_text":"arrival-time ordering missed hold updates","investigation_evidence_text":null,"rationale_text":null,"is_low_value_meta":false,"constraint_text":null,"next_step_text":null,"blocker_text":null,"progress_text":null,"key_finding_text":null}',
                metadata=LLMCallMetadata(provider_name="stub_provider", provider_kind="stub_kind", model="stub-model"),
                parsed_json={
                    "summary": "We discussed reservation ordering",
                    "candidate_type": "investigation_outcome",
                    "decision_text": None,
                    "decision_evidence_text": None,
                    "investigation_text": "arrival-time ordering missed hold updates",
                    "investigation_evidence_text": None,
                    "rationale_text": None,
                    "is_low_value_meta": False,
                    "constraint_text": None,
                    "next_step_text": None,
                    "blocker_text": None,
                    "progress_text": None,
                    "key_finding_text": None,
                },
            )
        )
    )
    source_item = SourceItem(
        source_type="chat_thread",
        source_id="thread-123",
        content_type="text/plain",
        content="We discussed reservation ordering options today.",
    )

    result = plugin.process_item(source_item)

    assert result.memory_objects[0].type == "discussion_summary"


def test_llm_plugin_demotes_markdown_table_cell_investigation_fragment() -> None:
    plugin = LLMAgentMemoryPlugin(
        provider=StubLLMProvider(
            response=LLMJsonResponse(
                raw_text='{"summary":"Capability comparison table.","candidate_type":"investigation_outcome","decision_text":null,"decision_evidence_text":null,"investigation_text":"| Can do |","investigation_evidence_text":"| Can do |","rationale_text":null,"is_low_value_meta":false,"constraint_text":null,"next_step_text":null,"blocker_text":null,"progress_text":null,"key_finding_text":null}',
                parsed_json={
                    "summary": "Capability comparison table.",
                    "candidate_type": "investigation_outcome",
                    "decision_text": None,
                    "decision_evidence_text": None,
                    "investigation_text": "| Can do |",
                    "investigation_evidence_text": "| Can do |",
                    "rationale_text": None,
                    "is_low_value_meta": False,
                    "constraint_text": None,
                    "next_step_text": None,
                    "blocker_text": None,
                    "progress_text": None,
                    "key_finding_text": None,
                },
            )
        )
    )
    source_item = SourceItem(
        source_type="assistant_output",
        source_id="table-fragment-1",
        content_type="text/plain",
        content=(
            "| Action | Can do | Can't yet do |\n"
            "|--------|--------|-------------|\n"
            "| Query memory | Yes - pallium_query | - |\n"
            "| Delete/correct memory | - | No write endpoint yet |"
        ),
        artifact_kind="assistant_output",
        role="assistant",
    )

    result = plugin.process_item(source_item)

    assert [memory.type for memory in result.memory_objects] == ["discussion_summary"]


def test_llm_plugin_demotes_markdown_list_fragment_in_non_english_text() -> None:
    plugin = LLMAgentMemoryPlugin(
        provider=StubLLMProvider(
            response=LLMJsonResponse(
                raw_text='{"summary":"שלבי בדיקה.","candidate_type":"investigation_outcome","decision_text":null,"decision_evidence_text":null,"investigation_text":"- אם הזיכרון שגוי: מחק או תקן אותו דרך Pallium","investigation_evidence_text":"- אם הזיכרון שגוי: מחק או תקן אותו דרך Pallium","rationale_text":null,"is_low_value_meta":false,"constraint_text":null,"next_step_text":null,"blocker_text":null,"progress_text":null,"key_finding_text":null}',
                parsed_json={
                    "summary": "שלבי בדיקה.",
                    "candidate_type": "investigation_outcome",
                    "decision_text": None,
                    "decision_evidence_text": None,
                    "investigation_text": "- אם הזיכרון שגוי: מחק או תקן אותו דרך Pallium",
                    "investigation_evidence_text": "- אם הזיכרון שגוי: מחק או תקן אותו דרך Pallium",
                    "rationale_text": None,
                    "is_low_value_meta": False,
                    "constraint_text": None,
                    "next_step_text": None,
                    "blocker_text": None,
                    "progress_text": None,
                    "key_finding_text": None,
                },
            )
        )
    )
    source_item = SourceItem(
        source_type="assistant_output",
        source_id="list-fragment-1",
        content_type="text/plain",
        content=(
            "- שאל את Pallium על אובייקט הזיכרון שנשמר\n"
            "- בדוק את יומן הביקורת כדי לעקוב אחרי המקור\n"
            "- אם הזיכרון שגוי: מחק או תקן אותו דרך Pallium\n"
            "- אם הזיכרון נכון אבל מיושן: סמן לרענון"
        ),
        artifact_kind="assistant_output",
        role="assistant",
    )

    result = plugin.process_item(source_item)

    assert [memory.type for memory in result.memory_objects] == ["discussion_summary"]
    assert result.memory_objects[0].schema_id == "llm.discussion_summary"


def test_llm_plugin_demotes_agreed_need_statement_from_decision() -> None:
    """A grounded need statement should not harden into durable decision memory."""
    plugin = LLMAgentMemoryPlugin(
        provider=StubLLMProvider(
            response=LLMJsonResponse(
                raw_text='{"summary":"Playbook note","candidate_type":"decision","decision_text":"create a clearer librarian playbook","decision_evidence_text":"The team agreed that we need a clearer librarian playbook for catalog sync incidents.","investigation_text":null,"investigation_evidence_text":null,"rationale_text":null,"is_low_value_meta":false,"constraint_text":null,"next_step_text":null,"blocker_text":null,"progress_text":null,"key_finding_text":null}',
                metadata=LLMCallMetadata(provider_name="stub_provider", provider_kind="stub_kind", model="stub-model"),
                parsed_json={
                    "summary": "Playbook note",
                    "candidate_type": "decision",
                    "decision_text": "create a clearer librarian playbook",
                    "decision_evidence_text": "The team agreed that we need a clearer librarian playbook for catalog sync incidents.",
                    "investigation_text": None,
                    "investigation_evidence_text": None,
                    "rationale_text": None,
                    "is_low_value_meta": False,
                    "constraint_text": None,
                    "next_step_text": None,
                    "blocker_text": None,
                    "progress_text": None,
                    "key_finding_text": None,
                },
            )
        )
    )
    source_item = SourceItem(
        source_type="meeting_summary",
        source_id="discussion-guard-1",
        content_type="text/plain",
        content="The team agreed that we need a clearer librarian playbook for catalog sync incidents.",
        artifact_kind="assistant_output",
    )

    result = plugin.process_item(source_item)

    assert [memory.type for memory in result.memory_objects] == ["discussion_summary"]


def test_llm_plugin_demotes_monitoring_note_with_next_step_from_investigation_outcome() -> None:
    """Monitoring-only status with a follow-up action should not become durable investigation memory."""
    plugin = LLMAgentMemoryPlugin(
        provider=StubLLMProvider(
            response=LLMJsonResponse(
                raw_text='{"summary":"Status update","candidate_type":"investigation_outcome","decision_text":null,"decision_evidence_text":null,"investigation_text":"catalog sync delay increased after the provider restart","investigation_evidence_text":"Catalog sync delay increased after the provider restart, and we should watch it closely tonight.","rationale_text":null,"is_low_value_meta":false,"constraint_text":null,"next_step_text":"Watch it closely tonight.","blocker_text":null,"progress_text":null,"key_finding_text":null}',
                metadata=LLMCallMetadata(provider_name="stub_provider", provider_kind="stub_kind", model="stub-model"),
                parsed_json={
                    "summary": "Status update",
                    "candidate_type": "investigation_outcome",
                    "decision_text": None,
                    "decision_evidence_text": None,
                    "investigation_text": "catalog sync delay increased after the provider restart",
                    "investigation_evidence_text": "Catalog sync delay increased after the provider restart, and we should watch it closely tonight.",
                    "rationale_text": None,
                    "is_low_value_meta": False,
                    "constraint_text": None,
                    "next_step_text": "Watch it closely tonight.",
                    "blocker_text": None,
                    "progress_text": None,
                    "key_finding_text": None,
                },
            )
        )
    )
    source_item = SourceItem(
        source_type="status_update",
        source_id="discussion-guard-2",
        content_type="text/plain",
        content="Catalog sync delay increased after the provider restart, and we should watch it closely tonight.",
        artifact_kind="notification",
    )

    result = plugin.process_item(source_item)

    assert result.memory_objects[0].type == "discussion_summary"
    semantic_signals = result.source_item_metadata_updates[source_item.id][SEMANTIC_SIGNAL_METADATA_KEY]
    assert semantic_signals["next_step_text"] == "Watch it closely tonight."


def test_llm_plugin_raises_on_invalid_output() -> None:
    plugin = LLMAgentMemoryPlugin(provider=StubLLMProvider(error=LLMProviderError("malformed output")))
    source_item = SourceItem(
        source_type="decision_note",
        source_id="decision-456",
        content_type="text/plain",
        content="Decision: use item item event time reservation ordering for reservation ordering to avoid missed hold updates.",
    )

    with pytest.raises(LLMProviderError):
        plugin.process_item(source_item)


def test_build_analysis_request_uses_requested_prompt_variant() -> None:
    source_item = SourceItem(
        source_type="chat_thread",
        source_id="thread-789",
        content_type="text/plain",
        content="We need to decide whether reservation ordering should use arrival time or item event time.",
        artifact_kind="message",
        role="user",
    )

    request = build_analysis_request(source_item, prompt_variant="strict_typed_memory_v7_claude_structured")

    assert request.prompt_role == WRITE_EXTRACTION_PROMPT_ROLE.role
    assert request.prompt_variant == "strict_typed_memory_v7_claude_structured"
    assert request.prompt_schema_id == WRITE_EXTRACTION_PROMPT_ROLE.schema_id
    assert request.prompt_schema_version == WRITE_EXTRACTION_PROMPT_ROLE.schema_version
    assert request.model_role == WRITE_EXTRACTION_PROMPT_ROLE.default_model_role
    assert 'investigation_outcome' in request.schema_description
    assert 'constraint_text' in request.schema_description
    assert 'Artifact kind: message' in request.user_prompt


def test_llm_plugin_with_prompt_variant_uses_variant_prompt() -> None:
    provider = StubLLMProvider(
        response=LLMJsonResponse(
            raw_text='{"summary":"Summary","candidate_type":null,"decision_text":null,"decision_evidence_text":null,"investigation_text":null,"investigation_evidence_text":null,"rationale_text":null,"is_low_value_meta":false,"constraint_text":null,"next_step_text":null,"blocker_text":null,"progress_text":null,"key_finding_text":null}',
            parsed_json={
                "summary": "Summary",
                "candidate_type": None,
                "decision_text": None,
                "decision_evidence_text": None,
                "investigation_text": None,
                "investigation_evidence_text": None,
                "rationale_text": None,
                "is_low_value_meta": False,
                "constraint_text": None,
                "next_step_text": None,
                "blocker_text": None,
                "progress_text": None,
                "key_finding_text": None,
            },
        )
    )
    plugin = LLMAgentMemoryPlugin(provider=provider, prompt_variant="strict_typed_memory_v4_evidence_guarded")
    source_item = SourceItem(
        source_type="investigation_summary",
        source_id="investigation-999",
        content_type="text/plain",
        content="Investigation found that arrival-time ordering missed hold updates during sync delays.",
        artifact_kind="tool_use_summary",
    )

    plugin.process_item(source_item)

    assert provider.last_system_prompt is not None
    assert 'investigation_outcome' in provider.last_system_prompt
    assert 'Evidence rule:' in provider.last_system_prompt
    assert 'we should watch' in provider.last_system_prompt
    assert 'low-value meta chatter' in provider.last_system_prompt
