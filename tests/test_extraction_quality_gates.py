"""Tests for extraction quality gates."""
import pytest
from semantic.conversational_knowledge import _is_ephemeral_fact


class TestEphemeralFactFilter:
    def test_filters_port_number(self):
        assert _is_ephemeral_fact({"subject": "Pallium service", "statement": "Pallium service runs on port 19836", "category": "event"})

    def test_filters_test_count(self):
        assert _is_ephemeral_fact({"subject": "test suite", "statement": "All 1579 tests pass", "category": "event"})

    def test_filters_commit_hash(self):
        assert _is_ephemeral_fact({"subject": "service", "statement": "Service lifecycle feature was committed with commit hash 9e19594", "category": "event"})

    def test_filters_uptime(self):
        assert _is_ephemeral_fact({"subject": "Pallium", "statement": "Pallium service uptime is 4.5 seconds", "category": "event"})

    def test_filters_pid(self):
        assert _is_ephemeral_fact({"subject": "Pallium", "statement": "Pallium service was running as PID 36440", "category": "event"})

    def test_filters_process_count(self):
        assert _is_ephemeral_fact({"subject": "Pallium", "statement": "Pallium has 3 small wrapper processes each using 5MB memory", "category": "event"})

    def test_keeps_durable_preference(self):
        assert not _is_ephemeral_fact({"subject": "Pallium packages", "statement": "Demo packages should never be activated", "category": "preference"})

    def test_keeps_architecture_choice(self):
        assert not _is_ephemeral_fact({"subject": "dashboard", "statement": "dashboard uses vanilla HTML/CSS/JS with no framework dependencies", "category": "preference"})

    def test_keeps_named_model_choice(self):
        assert not _is_ephemeral_fact({"subject": "embedding", "statement": "multilingual-e5-small was chosen as the embedding model", "category": "preference"})

    def test_keeps_user_activity_without_numbers(self):
        assert not _is_ephemeral_fact({"subject": "user", "statement": "user requested a documentation pass covering install and dashboard docs", "category": "activity"})
