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
            "[assistant] Done. Switched to SQLite for persistence. "
            "Also set up FastAPI as the HTTP framework.\n"
        )
        raw_decisions = [
            {
                "decision_text": "Switched to SQLite for persistence",
                "evidence": "Switched to SQLite for persistence",
            },
            {
                "decision_text": "set up FastAPI as the HTTP framework",
                "evidence": "set up FastAPI as the HTTP framework",
            },
        ]
        result = _validate_thread_decisions(raw_decisions, thread_text)
        assert len(result) == 2

    def test_filters_mixed_grounded_and_hallucinated(self):
        thread_text = (
            "[assistant] I've replaced the old auth with JWT tokens.\n"
        )
        raw_decisions = [
            {
                "decision_text": "replaced the old auth with JWT tokens",
                "evidence": "I've replaced the old auth with JWT tokens",
            },
            {
                "decision_text": "migrated to OAuth2",
                "evidence": "switched to OAuth2 for external clients",
            },
        ]
        result = _validate_thread_decisions(raw_decisions, thread_text)
        assert len(result) == 1
        assert "JWT" in result[0]["decision_text"]
