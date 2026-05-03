"""Test thread-level decision detection via merged thread summary call."""
import pytest
from semantic.agent_conversation_memory_threads import _validate_thread_decisions


class TestValidateThreadDecisions:
    """Test the grounding validation applied to LLM-returned decisions."""

    def test_accepts_grounded_decision(self):
        thread_text = (
            "[user] I think the dashboard should use vanilla HTML/CSS/JS, no framework\n"
            "[assistant] Done. I've implemented the dashboard using vanilla HTML/CSS/JS — "
            "no framework, no build step, just a single static file.\n"
        )
        raw_decisions = [
            {
                "decision_text": "implemented the dashboard using vanilla HTML/CSS/JS",
                "evidence": "I've implemented the dashboard using vanilla HTML/CSS/JS — no framework, no build step",
            }
        ]
        result = _validate_thread_decisions(raw_decisions, thread_text)
        assert len(result) == 1
        assert "vanilla" in result[0]["decision_text"]

    def test_rejects_hallucinated_decision(self):
        thread_text = "[user] Should we use React?\n[assistant] Let me think about it.\n"
        raw_decisions = [
            {
                "decision_text": "chose React for the frontend",
                "evidence": "we decided to use React",
            }
        ]
        result = _validate_thread_decisions(raw_decisions, thread_text)
        assert len(result) == 0

    def test_rejects_empty_fields(self):
        thread_text = "[user] Use vanilla JS\n[assistant] Done.\n"
        raw_decisions = [{"decision_text": "", "evidence": "Done."}]
        result = _validate_thread_decisions(raw_decisions, thread_text)
        assert len(result) == 0

    def test_returns_empty_for_none_input(self):
        result = _validate_thread_decisions(None, "some text")
        assert result == []

    def test_returns_empty_for_non_list(self):
        result = _validate_thread_decisions("not a list", "some text")
        assert result == []

    def test_accepts_multiple_decisions(self):
        thread_text = (
            "[user] Let's use SQLite for storage and FastAPI for the web layer\n"
            "[assistant] Done. Switched to SQLite for persistence and data storage. "
            "Also set up FastAPI as the HTTP framework for serving requests.\n"
        )
        raw_decisions = [
            {
                "decision_text": "Switched to SQLite for persistence and data storage",
                "evidence": "Switched to SQLite for persistence and data storage. Also set up FastAPI as the HTTP framework for serving requests.",
            },
            {
                "decision_text": "set up FastAPI as the HTTP framework for serving requests",
                "evidence": "Switched to SQLite for persistence and data storage. Also set up FastAPI as the HTTP framework for serving requests.",
            },
        ]
        result = _validate_thread_decisions(raw_decisions, thread_text)
        assert len(result) == 2

    def test_filters_mixed_grounded_and_hallucinated(self):
        thread_text = (
            "[assistant] I've replaced the old auth system with JWT tokens for all API endpoints.\n"
        )
        raw_decisions = [
            {
                "decision_text": "replaced the old auth system with JWT tokens for all API endpoints",
                "evidence": "I've replaced the old auth system with JWT tokens for all API endpoints",
            },
            {
                "decision_text": "migrated to OAuth2",
                "evidence": "switched to OAuth2 for external clients",
            },
        ]
        result = _validate_thread_decisions(raw_decisions, thread_text)
        assert len(result) == 1
        assert "JWT" in result[0]["decision_text"]


class TestSubstanceFilters:
    """Language-agnostic substance filters for self-containment."""

    def test_rejects_too_short_decision(self):
        # "let's say 5% overhead" is only 21 chars — not self-contained
        thread_text = "user/msg: ok, so let's say 5% overhead. what will justify it?\nassistant/msg: done"
        raw_decisions = [{"decision_text": "let's say 5% overhead", "evidence": "ok, so let's say 5% overhead. what will justify it?"}]
        result = _validate_thread_decisions(raw_decisions, thread_text)
        assert len(result) == 0

    def test_rejects_decision_equals_evidence(self):
        # When decision == evidence, it's a lazy copy
        thread_text = "user/msg: we should use vanilla JS\nassistant/msg: we should use vanilla JS"
        raw_decisions = [{"decision_text": "we should use vanilla JS", "evidence": "we should use vanilla JS"}]
        # This is also short (24 chars), so caught by length too
        result = _validate_thread_decisions(raw_decisions, thread_text)
        assert len(result) == 0

    def test_rejects_decision_equals_evidence_above_length_threshold(self):
        # Isolate the "equals" filter: both fields >= 30 chars but identical
        text = "we decided to use SQLite for all storage needs"
        thread_text = f"user/msg: {text}\nassistant/msg: {text}"
        raw_decisions = [{"decision_text": text, "evidence": text}]
        result = _validate_thread_decisions(raw_decisions, thread_text)
        assert len(result) == 0

    def test_rejects_short_decision_contained_in_evidence(self):
        # "yes, let's evaluate the threshold" (33 chars) contained in longer evidence
        thread_text = "user/msg: a couple of things regarding this: 1. yes, let's evaluate the threshold.\nassistant/msg: done"
        raw_decisions = [{"decision_text": "yes, let's evaluate the threshold", "evidence": "a couple of things regarding this: 1. yes, let's evaluate the threshold."}]
        result = _validate_thread_decisions(raw_decisions, thread_text)
        assert len(result) == 0

    def test_keeps_long_self_contained_decision(self):
        # Good decision — 145 chars, self-contained
        decision = 'this should be a 2 step. 1 - suppress items we want to remove. 2 - have an option on pallium to "delete suppressed items" that does that properly'
        evidence = 'i think in general this should be a 2 step. 1 - suppress items we want to remove. 2 - have an option on pallium to "delete suppressed items" that does that properly, for now this can be called manually'
        thread_text = f"user/msg: {evidence}\nassistant/msg: Done. Implemented the 2-step approach."
        raw_decisions = [{"decision_text": decision, "evidence": evidence}]
        result = _validate_thread_decisions(raw_decisions, thread_text)
        assert len(result) == 1

    def test_keeps_decision_above_50_chars_even_if_contained_in_evidence(self):
        # "remember to do an architect review before and after every change" (64 chars)
        # evidence is different text
        decision = "remember to do an architect review before and after every change"
        evidence = "ok, so let's add it. but remember to do an architect review before and after every change"
        thread_text = f"user/msg: {evidence}\nassistant/msg: Added to the process."
        raw_decisions = [{"decision_text": decision, "evidence": evidence}]
        result = _validate_thread_decisions(raw_decisions, thread_text)
        assert len(result) == 1
