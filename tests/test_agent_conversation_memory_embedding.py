from __future__ import annotations

import pytest

from core.models import MemoryObject
from semantic.agent_conversation_memory_embedding import EMBEDDABLE_MEMORY_TYPES, build_embedding_text


def _make_memory(memory_type: str, payload: dict) -> MemoryObject:
    return MemoryObject(
        type=memory_type,
        schema_id=f"test.{memory_type}",
        schema_version="v1",
        payload=payload,
    )


class TestBuildEmbeddingTextDecision:
    def test_returns_natural_language(self):
        mo = _make_memory("decision", {
            "decision": "Use PostgreSQL for the main database",
            "rationale": "Better JSON support and full-text search",
            "decision_evidence_text": "We decided to use PostgreSQL",
        })
        text = build_embedding_text(mo)
        assert text is not None
        assert "Decision: Use PostgreSQL for the main database" in text
        assert "Rationale: Better JSON support and full-text search" in text

    def test_missing_optional_fields(self):
        mo = _make_memory("decision", {
            "decision": "Use PostgreSQL for the production database backend",
        })
        text = build_embedding_text(mo)
        assert text is not None
        assert "PostgreSQL" in text

    def test_empty_payload(self):
        mo = _make_memory("decision", {})
        text = build_embedding_text(mo)
        assert text is None


class TestBuildEmbeddingTextInvestigationOutcome:
    def test_returns_natural_language(self):
        mo = _make_memory("investigation_outcome", {
            "investigation_outcome": "Token refresh was failing due to clock skew",
            "rationale": "Server clocks were 30 seconds apart",
            "key_finding_text": "NTP was disabled on prod-02",
            "investigation_evidence_text": "Root cause: clock skew",
        })
        text = build_embedding_text(mo)
        assert text is not None
        assert "Investigation outcome: Token refresh was failing due to clock skew" in text
        assert "Key finding: NTP was disabled on prod-02" in text
        assert "Rationale: Server clocks were 30 seconds apart" in text

    def test_missing_optional_fields(self):
        mo = _make_memory("investigation_outcome", {
            "investigation_outcome": "Root cause identified",
        })
        text = build_embedding_text(mo)
        assert text is not None
        assert "Investigation outcome: Root cause identified" in text


class TestBuildEmbeddingTextThreadSummary:
    def test_returns_natural_language(self):
        mo = _make_memory("thread_summary", {
            "summary": "Discussed migration strategy for auth service",
            "conclusions": [
                {"type": "decision", "text": "We will use OAuth2 with PKCE"},
                {"type": "investigation_outcome", "text": "Current tokens expire too fast"},
            ],
        })
        text = build_embedding_text(mo)
        assert text is not None
        assert "Discussed migration strategy for auth service" in text
        assert "We will use OAuth2 with PKCE" in text
        assert "Current tokens expire too fast" in text

    def test_no_conclusions(self):
        mo = _make_memory("thread_summary", {
            "summary": "Quick sync about deployment timeline and staging environment readiness",
        })
        text = build_embedding_text(mo)
        assert text is not None
        assert "deployment" in text

    def test_too_short_summary_returns_none(self):
        mo = _make_memory("thread_summary", {
            "summary": "Quick sync about deployment",
        })
        assert build_embedding_text(mo) is None


class TestBuildEmbeddingTextTaskCheckpoint:
    def test_returns_natural_language(self):
        mo = _make_memory("task_checkpoint", {
            "summary": "Auth migration in progress",
            "task": "Migrate auth to OAuth2",
            "current_state": "Token refresh endpoint done",
            "blocker_state": "Waiting on security review",
            "next_step": "Submit PR for review",
            "key_findings": ["Old tokens incompatible", "Need migration script"],
        })
        text = build_embedding_text(mo)
        assert text is not None
        assert "Task: Migrate auth to OAuth2" in text
        assert "Current state: Token refresh endpoint done" in text
        assert "Blocker: Waiting on security review" in text
        assert "Next step: Submit PR for review" in text
        assert "Finding: Old tokens incompatible" in text
        assert "Finding: Need migration script" in text

    def test_minimal_fields(self):
        mo = _make_memory("task_checkpoint", {
            "task": "Investigate catalog sync scheduled job failure and token rotation",
        })
        text = build_embedding_text(mo)
        assert text is not None
        assert "catalog sync" in text

    def test_too_short_task_returns_none(self):
        mo = _make_memory("task_checkpoint", {"task": "Fix bug"})
        assert build_embedding_text(mo) is None


class TestBuildEmbeddingTextPatternMemory:
    def test_returns_natural_language(self):
        mo = _make_memory("pattern_memory", {
            "summary": "Auth services frequently hit token expiration issues",
            "pattern_label": "token_expiration_pattern",
            "conclusions": [
                {"type": "decision", "text": "Always add clock skew tolerance"},
            ],
        })
        text = build_embedding_text(mo)
        assert text is not None
        assert "Auth services frequently hit token expiration issues" in text
        assert "Always add clock skew tolerance" in text


class TestBuildEmbeddingTextContinuityMemory:
    def test_returns_natural_language(self):
        mo = _make_memory("continuity_memory", {
            "summary": "Token refresh resolution carried forward",
            "continuity_question": "What was the resolution for the token refresh bug?",
            "carry_forward_answer": "Clock skew was the root cause; NTP fix deployed",
        })
        text = build_embedding_text(mo)
        assert text is not None
        assert "Question: What was the resolution for the token refresh bug?" in text
        assert "Answer: Clock skew was the root cause; NTP fix deployed" in text
        assert "Token refresh resolution carried forward" in text


class TestTypePrefixInEmbeddingText:
    def test_decision_has_type_prefix(self):
        mo = _make_memory("decision", {
            "decision": "Use PostgreSQL for the main database",
            "rationale": "Better JSON support and full-text search",
        })
        text = build_embedding_text(mo)
        assert text is not None
        assert text.startswith("[decision] ")

    def test_investigation_outcome_has_type_prefix(self):
        mo = _make_memory("investigation_outcome", {
            "investigation_outcome": "Token refresh was failing due to clock skew",
            "rationale": "Server clocks were 30 seconds apart",
        })
        text = build_embedding_text(mo)
        assert text is not None
        assert text.startswith("[investigation_outcome] ")

    def test_interest_has_type_prefix(self):
        mo = _make_memory("interest", {
            "interest_text": "Chroma vector database for lightweight local embedding and retrieval",
            "summary": "User expressed interest in trying Chroma for a side project",
        })
        text = build_embedding_text(mo)
        assert text is not None
        assert text.startswith("[interest] ")

    def test_constraint_memory_has_type_prefix(self):
        mo = _make_memory("constraint_memory", {
            "constraint_text": "No GPL-licensed dependencies allowed in this project per legal requirement",
        })
        text = build_embedding_text(mo)
        assert text is not None
        assert text.startswith("[constraint_memory] ")

    def test_short_content_still_returns_none(self):
        """Type prefix does not rescue too-short content from the 40-char guard."""
        mo = _make_memory("decision", {"decision": "Use option B"})
        text = build_embedding_text(mo)
        assert text is None

    def test_all_embeddable_types_have_prefix(self):
        """Every embeddable type gets its bracket prefix."""
        payloads = {
            "decision": {"decision": "Use event-time ordering for reservation priority during catalog sync delays"},
            "investigation_outcome": {"investigation_outcome": "Duplicate hold entries caused by missing deduplication check in queue consumer"},
            "thread_summary": {"summary": "Investigation into catalog sync failures found expired API token on nightly batch service account"},
            "task_checkpoint": {"task": "Investigate catalog sync scheduled job failure and token rotation policy gap"},
            "pattern_memory": {"summary": "Recurring pattern: nightly batch jobs accumulating backlogs cause downstream queue failures"},
            "continuity_memory": {"continuity_question": "What is the status of the catalog sync investigation and token refresh?"},
            "interest": {"interest_text": "Chroma vector database for lightweight local embedding and retrieval", "summary": "User expressed interest in trying Chroma for a side project"},
            "constraint_memory": {"constraint_text": "No GPL-licensed dependencies allowed in this project per legal requirement"},
        }
        for memory_type in EMBEDDABLE_MEMORY_TYPES:
            mo = _make_memory(memory_type, payloads[memory_type])
            text = build_embedding_text(mo)
            assert text is not None, f"build_embedding_text returned None for {memory_type}"
            assert text.startswith(f"[{memory_type}] "), f"{memory_type} missing prefix, got: {text[:30]}"


class TestNonEmbeddableTypes:
    def test_turn_summary_returns_none(self):
        mo = _make_memory("turn_summary", {
            "summary": "Just a discussion",
        })
        assert build_embedding_text(mo) is None

    def test_unknown_type_returns_none(self):
        mo = _make_memory("some_unknown_type", {
            "summary": "Unknown",
        })
        assert build_embedding_text(mo) is None


class TestEmbeddableMemoryTypes:
    def test_all_types_covered(self):
        """Every type in EMBEDDABLE_MEMORY_TYPES produces non-None for a valid payload with enough content."""
        payloads = {
            "decision": {"decision": "Use event-time ordering for reservation priority during catalog sync delays"},
            "investigation_outcome": {"investigation_outcome": "Duplicate hold entries caused by missing deduplication check in queue consumer"},
            "thread_summary": {"summary": "Investigation into catalog sync failures found expired API token on nightly batch service account"},
            "task_checkpoint": {"task": "Investigate catalog sync scheduled job failure and token rotation policy gap"},
            "pattern_memory": {"summary": "Recurring pattern: nightly batch jobs accumulating backlogs cause downstream queue failures"},
            "continuity_memory": {"continuity_question": "What is the status of the catalog sync investigation and token refresh?"},
            "interest": {"interest_text": "Chroma vector database for lightweight local embedding and retrieval", "summary": "User expressed interest in trying Chroma for a side project"},
            "constraint_memory": {"constraint_text": "No GPL-licensed dependencies allowed in this project per legal requirement"},
        }
        for memory_type in EMBEDDABLE_MEMORY_TYPES:
            mo = _make_memory(memory_type, payloads[memory_type])
            text = build_embedding_text(mo)
            assert text is not None, f"build_embedding_text returned None for {memory_type}"
            assert len(text) >= 40, f"build_embedding_text returned text shorter than 40 chars for {memory_type}"

    def test_short_text_below_guard_returns_none(self):
        """Embedding text shorter than 40 characters returns None (too generic to embed)."""
        mo = _make_memory("decision", {"decision": "Use option B"})
        text = build_embedding_text(mo)
        assert text is None

    def test_text_at_guard_boundary_returns_value(self):
        """Embedding text at exactly 40 characters is kept."""
        # "Decision: " (10 chars) + 30 chars of content = 40
        mo = _make_memory("decision", {"decision": "Use event-time ordering for sync"})
        text = build_embedding_text(mo)
        assert text is not None
        assert len(text) >= 40

    def test_text_is_natural_language_not_normalized(self):
        """Embedding text should preserve case and punctuation (not lowercase token soup)."""
        mo = _make_memory("decision", {
            "decision": "Use PostgreSQL for Production",
            "rationale": "Better JSON Support",
        })
        text = build_embedding_text(mo)
        assert text is not None
        # Should preserve uppercase letters (not normalized to lowercase)
        assert "PostgreSQL" in text
        assert "Production" in text
