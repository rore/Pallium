"""Phase 5b match-text plumbing (2026-06-28).

Verifies the chain that surfaces a per-type memory text view to the
usage-audit populator:

  semantic.agent_conversation_memory_embedding.build_memory_match_text
    -> core.service.PalliumService.get_memory_expand (3rd tuple element)
    -> api MemoryExpandResponse.match_text
    -> integrations/{claude-code,codex}/hooks/stop.py _fetch_memory_match_text

The fix addresses a code-review finding that the hook's hardcoded
7-key scalar coalesce undercounted real memory usage for task_checkpoint,
continuity_memory, thread_summary, and pattern_memory. See
docs/specs/2026-06-27-injection-policy-abstention.md Phase 5b.

Tests in this file:

1. build_memory_match_text covers the reviewer-flagged fields per type
   (regression against the original 7-key list).
2. build_memory_match_text omits the [type] prefix and the 40-char floor
   that ``build_embedding_text`` enforces.
3. PalliumService.get_memory_expand returns the match_text in slot 3.
4. GET /memory/{id}/expand surfaces ``match_text`` in JSON.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import AppConfig
from app.main import create_app
from core.models import MemoryObject, Relation, SourceItem
from semantic.agent_conversation_memory_embedding import (
    build_embedding_text,
    build_memory_match_text,
)
from storage.vector_index import VectorIndexConfig
from tests.config_helpers import DEMO_SEMANTIC_PACKAGES


def _memory(memory_type: str, payload: dict, container_ref: str = "c") -> MemoryObject:
    return MemoryObject(
        type=memory_type,
        schema_id=f"test.{memory_type}",
        schema_version="v1",
        payload=payload,
        container_ref=container_ref,
        visibility="private",
    )


# ---------------------------------------------------------------------------
# build_memory_match_text — per-type coverage (regression against the bug)
# ---------------------------------------------------------------------------

class TestBuildMemoryMatchTextPerType:
    """The reviewer flagged four types whose substantive content lived
    in fields outside the hook's hardcoded scalar list. Each test
    asserts at least one such field is now present in the match_text.
    """

    def test_task_checkpoint_includes_task_and_state_fields(self) -> None:
        mo = _memory("task_checkpoint", {
            "task": "Refactor the routing layer",
            "current_state": "halfway through the rename pass",
            "blocker_state": "waiting on architect review",
            "next_step": "split the resolver into two functions",
            "key_findings": ["winner-replace breaks under window-trim"],
        })
        text = build_memory_match_text(mo)
        # The old 7-key hook list would only see `summary` here — which is
        # absent. Without the fix this would be the empty string.
        assert "Refactor the routing layer" in text
        assert "halfway through the rename pass" in text
        assert "waiting on architect review" in text
        assert "split the resolver into two functions" in text
        assert "winner-replace breaks under window-trim" in text

    def test_continuity_memory_includes_question_and_answer(self) -> None:
        mo = _memory("continuity_memory", {
            "continuity_question": "How did we end up handling near-dup supersession?",
            "carry_forward_answer": (
                "SequenceMatcher.ratio over normalized canonical_keys at "
                "threshold 0.85, hint carries the old record's key."
            ),
            "summary": "Near-dup supersession (2026-06-28)",
        })
        text = build_memory_match_text(mo)
        # The old hook list would only see `summary`.
        assert "How did we end up handling near-dup supersession?" in text
        assert "SequenceMatcher.ratio over normalized canonical_keys" in text

    def test_thread_summary_includes_conclusion_texts(self) -> None:
        mo = _memory("thread_summary", {
            "summary": "Discussed the abstention plan and Phase 5b populator.",
            "conclusions": [
                {"text": "Reviewer flagged the 7-key coalesce as too narrow."},
                {"text": "Fix: reuse the embedding-text builder via API."},
            ],
        })
        text = build_memory_match_text(mo)
        # The old hook list saw `summary` only — conclusions[*].text was lost.
        assert "Reviewer flagged the 7-key coalesce as too narrow." in text
        assert "Fix: reuse the embedding-text builder via API." in text

    def test_pattern_memory_includes_conclusion_texts(self) -> None:
        mo = _memory("pattern_memory", {
            "summary": "Pattern across recent rebuilds.",
            "conclusions": [
                {"text": "Three rebuilds in a row produced byte-different keys."},
            ],
        })
        text = build_memory_match_text(mo)
        assert "Three rebuilds in a row produced byte-different keys." in text

    def test_decision_includes_rationale(self) -> None:
        mo = _memory("decision", {
            "decision": "Use difflib over canonical_key for paraphrase detection.",
            "rationale": "Pure-Python, no deps, deterministic, easy to test.",
        })
        text = build_memory_match_text(mo)
        # `rationale` was absent from the hook's 7-key list. It's
        # substantial recallable content for the agent.
        assert "Use difflib over canonical_key for paraphrase detection." in text
        assert "Pure-Python, no deps, deterministic, easy to test." in text

    def test_investigation_outcome_includes_key_finding_and_rationale(self) -> None:
        mo = _memory("investigation_outcome", {
            "investigation_outcome": "Hint must carry the OLD record's canonical_key.",
            "key_finding_text": "Resolver matches via exact-equality.",
            "rationale": "Otherwise the lookup never finds the prior row.",
        })
        text = build_memory_match_text(mo)
        # `key_finding_text` and `rationale` were absent from the 7-key list.
        assert "Resolver matches via exact-equality." in text
        assert "Otherwise the lookup never finds the prior row." in text


# ---------------------------------------------------------------------------
# build_memory_match_text vs build_embedding_text — divergence properties
# ---------------------------------------------------------------------------

class TestMatchTextDivergesFromEmbedding:
    """build_memory_match_text shares the per-type field map with
    build_embedding_text but differs on:

      - no [type] prefix (the agent would not quote it)
      - no 40-char floor (the matcher's own 60-char threshold handles it,
        and short legitimate texts like `constraint_text` should still
        be matchable)
    """

    def test_no_type_prefix(self) -> None:
        mo = _memory("decision", {
            "decision": "Pick PostgreSQL for the catalog service.",
            "rationale": "Better JSON support and full-text search.",
        })
        match = build_memory_match_text(mo)
        embed = build_embedding_text(mo)
        assert match
        assert embed is not None
        assert match.startswith("Decision: ") or match.startswith("Decision:")
        assert embed.startswith("[decision]")
        # Embedding view has the bracketed prefix; match view does not.
        assert not match.startswith("[")

    def test_short_constraint_below_embedding_floor_still_returned(self) -> None:
        """A constraint shorter than 40 chars would yield None from
        build_embedding_text but must still appear in match_text."""
        mo = _memory("constraint_memory", {
            "constraint_text": "No GPL deps.",
        })
        match = build_memory_match_text(mo)
        embed = build_embedding_text(mo)
        assert "No GPL deps." in match
        assert embed is None  # below the 40-char embedding floor

    def test_unembeddable_type_returns_empty(self) -> None:
        # `task_trace` is not in EMBEDDABLE_MEMORY_TYPES.
        mo = _memory("task_trace", {"summary": "trace details"})
        assert build_memory_match_text(mo) == ""


# ---------------------------------------------------------------------------
# Service tuple shape — Phase 5b plumbing in core.service.get_memory_expand
# ---------------------------------------------------------------------------

def _config(db_url: str) -> AppConfig:
    return AppConfig(
        storage_backend="sqlite",
        sqlite_url=db_url,
        default_use_case="demo_agent_memory",
        semantic_packages=DEMO_SEMANTIC_PACKAGES,
        vector_index=VectorIndexConfig(enabled=False),
    )


class TestServiceReturnsMatchText:
    def test_returns_match_text_in_slot_3(self, test_db_url: str) -> None:
        app = create_app(_config(test_db_url))
        service = app.state.pallium_service
        storage = service._storage

        mo = _memory(
            "task_checkpoint",
            {
                "task": "Land the Phase 5b match-text plumbing fix",
                "next_step": "Push and run the live backfill verification",
            },
            container_ref="phase5b:c",
        )
        storage.create_memory_object(mo)

        result = service.get_memory_expand(mo.id, container_ref="phase5b:c")
        assert isinstance(result, tuple) and len(result) == 3, (
            "service.get_memory_expand must return (payload, items, match_text)"
        )
        _payload, _items, match_text = result
        assert match_text is not None
        assert "Land the Phase 5b match-text plumbing fix" in match_text
        assert "Push and run the live backfill verification" in match_text

    def test_none_match_text_for_unembeddable_type(self, test_db_url: str) -> None:
        app = create_app(_config(test_db_url))
        service = app.state.pallium_service
        storage = service._storage

        mo = _memory("task_trace", {"summary": "trace details"}, container_ref="phase5b:c")
        storage.create_memory_object(mo)

        _payload, _items, match_text = service.get_memory_expand(
            mo.id, container_ref="phase5b:c",
        )
        assert match_text is None


# ---------------------------------------------------------------------------
# HTTP endpoint — MemoryExpandResponse.match_text surfaces correctly
# ---------------------------------------------------------------------------


class TestHttpExpandResponseMatchText:
    def test_endpoint_returns_match_text_field(self, test_db_url: str) -> None:
        app = create_app(_config(test_db_url))
        service = app.state.pallium_service
        storage = service._storage

        mo = _memory(
            "continuity_memory",
            {
                "continuity_question": "Where did we leave the abstention rollout?",
                "carry_forward_answer": "Phase 3a shipped, Phase 3b config is opt-in.",
            },
            container_ref="phase5b-http:c",
        )
        storage.create_memory_object(mo)

        client = TestClient(app)
        resp = client.get(f"/memory/{mo.id}/expand", params={"container_ref": "phase5b-http:c"})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "match_text" in body, "response must include match_text (Phase 5b)"
        match_text = body["match_text"]
        assert match_text is not None
        assert "Where did we leave the abstention rollout?" in match_text
        assert "Phase 3a shipped, Phase 3b config is opt-in." in match_text

    def test_endpoint_returns_null_match_text_for_unembeddable(self, test_db_url: str) -> None:
        app = create_app(_config(test_db_url))
        service = app.state.pallium_service
        storage = service._storage

        mo = _memory(
            "task_trace",
            {"summary": "trace details"},
            container_ref="phase5b-http:c",
        )
        storage.create_memory_object(mo)

        client = TestClient(app)
        resp = client.get(f"/memory/{mo.id}/expand", params={"container_ref": "phase5b-http:c"})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        # Field must be present (so hooks don't KeyError) but value is None
        assert "match_text" in body
        assert body["match_text"] is None
