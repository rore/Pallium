"""Test thread-level investigation detection via merged thread summary call."""
import pytest
from semantic.agent_conversation_memory_threads import _validate_thread_investigations


class TestValidateThreadInvestigations:
    """Test the grounding validation applied to LLM-returned investigations."""

    def test_accepts_grounded_investigation(self):
        thread_text = (
            "[user] Why are hold updates being skipped during catalog sync?\n"
            "[assistant] I found that arrival-time ordering skipped hold updates during catalog sync delays because the provider delivered updates late.\n"
        )
        raw_investigations = [
            {
                "investigation_text": "arrival-time ordering skipped hold updates during catalog sync delays because the provider delivered updates late",
                "evidence": "I found that arrival-time ordering skipped hold updates during catalog sync delays because the provider delivered updates late",
            }
        ]
        result = _validate_thread_investigations(raw_investigations, thread_text)
        assert len(result) == 1
        assert "arrival-time ordering" in result[0]["investigation_text"]

    def test_rejects_hallucinated_investigation(self):
        thread_text = "[user] Check the sync logs\n[assistant] Looking into it now.\n"
        raw_investigations = [
            {
                "investigation_text": "the catalog sync retry hit a 401 because the service token expired after 312 records",
                "evidence": "confirmed the token expiry caused the 401 after 312 records",
            }
        ]
        result = _validate_thread_investigations(raw_investigations, thread_text)
        assert len(result) == 0

    def test_rejects_short_investigation(self):
        thread_text = "user/msg: the token expired mid-sync\nassistant/msg: noted, the token expired mid-sync"
        raw_investigations = [
            {
                "investigation_text": "the token expired mid-sync",
                "evidence": "noted, the token expired mid-sync",
            }
        ]
        result = _validate_thread_investigations(raw_investigations, thread_text)
        assert len(result) == 0

    def test_rejects_lazy_copy(self):
        text = "reservation ordering using item event timestamps prevents missed updates when catalog sync introduces delivery delays"
        thread_text = f"user/msg: {text}\nassistant/msg: {text}"
        raw_investigations = [{"investigation_text": text, "evidence": text}]
        result = _validate_thread_investigations(raw_investigations, thread_text)
        assert len(result) == 0

    def test_rejects_short_contained_in_evidence(self):
        investigation = "the retry loop exits after three consecutive timeouts"
        evidence = "looking at the logs, the retry loop exits after three consecutive timeouts from the upstream provider"
        thread_text = f"user/msg: what did you find?\nassistant/msg: {evidence}"
        raw_investigations = [{"investigation_text": investigation, "evidence": evidence}]
        result = _validate_thread_investigations(raw_investigations, thread_text)
        assert len(result) == 0

    def test_rejects_user_line_evidence(self):
        thread_text = (
            "user/catalog_check: the catalog sync retry hit a 401 because the service token expired after 312 records were processed\n"
            "assistant/msg: I'll investigate the token expiry.\n"
        )
        raw_investigations = [
            {
                "investigation_text": "the catalog sync retry hit a 401 because the service token expired after 312 records were processed",
                "evidence": "user/catalog_check: the catalog sync retry hit a 401 because the service token expired after 312 records were processed",
            }
        ]
        result = _validate_thread_investigations(raw_investigations, thread_text)
        assert len(result) == 0

    def test_returns_empty_for_none_input(self):
        result = _validate_thread_investigations(None, "some text")
        assert result == []

    def test_returns_empty_for_non_list(self):
        result = _validate_thread_investigations("not a list", "some text")
        assert result == []

    def test_accepts_multiple_investigations(self):
        thread_text = (
            "[assistant] The catalog sync retry hit a 401 because the service token expired after 312 records were processed. "
            "Additionally, reservation ordering using item event timestamps prevents missed updates when catalog sync introduces delivery delays.\n"
        )
        raw_investigations = [
            {
                "investigation_text": "The catalog sync retry hit a 401 because the service token expired after 312 records were processed",
                "evidence": "The catalog sync retry hit a 401 because the service token expired after 312 records were processed. Additionally, reservation ordering using item event timestamps prevents missed updates when catalog sync introduces delivery delays.",
            },
            {
                "investigation_text": "reservation ordering using item event timestamps prevents missed updates when catalog sync introduces delivery delays",
                "evidence": "The catalog sync retry hit a 401 because the service token expired after 312 records were processed. Additionally, reservation ordering using item event timestamps prevents missed updates when catalog sync introduces delivery delays.",
            },
        ]
        result = _validate_thread_investigations(raw_investigations, thread_text)
        assert len(result) == 2

    def test_filters_mixed_valid_and_invalid(self):
        thread_text = (
            "[assistant] The catalog sync retry hit a 401 because the service token expired after 312 records were processed.\n"
        )
        raw_investigations = [
            {
                "investigation_text": "The catalog sync retry hit a 401 because the service token expired after 312 records were processed",
                "evidence": "The catalog sync retry hit a 401 because the service token expired after 312 records were processed.",
            },
            {
                "investigation_text": "the hold queue overflowed due to a race condition in the reservation lock",
                "evidence": "confirmed the race condition caused overflow",
            },
        ]
        result = _validate_thread_investigations(raw_investigations, thread_text)
        assert len(result) == 1
        assert "401" in result[0]["investigation_text"]
