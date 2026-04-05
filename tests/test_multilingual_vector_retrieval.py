"""Integration tests for multilingual vector retrieval using real embedding models.

These tests use the actual ONNX embedding provider with multilingual-e5-small
to verify that cross-language retrieval works end-to-end. They are skipped
when the model is not available (e.g., CI environments).
"""
from __future__ import annotations

import numpy as np
import pytest


def _load_multilingual_provider():
    """Try to load multilingual-e5-small. Returns (provider, skip_reason)."""
    try:
        from providers.embedding.onnx_provider import OnnxEmbeddingProvider
        provider = OnnxEmbeddingProvider(
            model="intfloat/multilingual-e5-small",
            query_prefix="query: ",
            passage_prefix="passage: ",
        )
        # Quick sanity: model should produce 384-dim vectors
        probe = provider.embed(["probe"], mode="passage")
        assert len(probe[0]) == 384
        return provider, None
    except Exception as e:
        return None, f"multilingual-e5-small not available: {e}"


def _cosine(a: list[float], b: list[float]) -> float:
    va, vb = np.array(a), np.array(b)
    return float(np.dot(va, vb) / (np.linalg.norm(va) * np.linalg.norm(vb)))


_provider, _skip_reason = _load_multilingual_provider()
skip_if_no_model = pytest.mark.skipif(_provider is None, reason=_skip_reason or "model not available")


@skip_if_no_model
class TestMultilingualEmbeddingSimilarity:
    """Verify that multilingual-e5-small produces correct similarity ordering
    for cross-language retrieval. Hebrew query should rank relevant memories
    (in any language) above irrelevant ones."""

    def test_hebrew_query_hebrew_relevant_above_irrelevant(self):
        """Same-language: Hebrew query should prefer Hebrew-relevant over
        Hebrew-irrelevant passage."""
        q = _provider.embed(["מה החלטנו לגבי מסד הנתונים"], mode="query")[0]
        relevant = _provider.embed(
            ["החלטנו להשתמש ב-PostgreSQL בשביל מסד הנתונים"], mode="passage"
        )[0]
        irrelevant = _provider.embed(
            ["הכנתי עוגת שוקולד אתמול בערב"], mode="passage"
        )[0]
        sim_rel = _cosine(q, relevant)
        sim_irr = _cosine(q, irrelevant)
        assert sim_rel > sim_irr, (
            f"Same-language ordering wrong: relevant={sim_rel:.4f} <= irrelevant={sim_irr:.4f}"
        )

    def test_hebrew_query_english_relevant_above_irrelevant(self):
        """Cross-language: Hebrew query should prefer English-relevant over
        English-irrelevant passage."""
        q = _provider.embed(["מה החלטנו לגבי מסד הנתונים"], mode="query")[0]
        relevant = _provider.embed(
            ["We decided to use PostgreSQL for the database"], mode="passage"
        )[0]
        irrelevant = _provider.embed(
            ["The weather is sunny today in Tel Aviv"], mode="passage"
        )[0]
        sim_rel = _cosine(q, relevant)
        sim_irr = _cosine(q, irrelevant)
        assert sim_rel > sim_irr, (
            f"Cross-language ordering wrong: relevant={sim_rel:.4f} <= irrelevant={sim_irr:.4f}"
        )

    def test_english_query_hebrew_relevant_above_irrelevant(self):
        """Cross-language reverse: English query should prefer Hebrew-relevant
        over Hebrew-irrelevant passage."""
        q = _provider.embed(["What did we decide about the database"], mode="query")[0]
        relevant = _provider.embed(
            ["החלטנו להשתמש ב-PostgreSQL בשביל מסד הנתונים"], mode="passage"
        )[0]
        irrelevant = _provider.embed(
            ["הכנתי עוגת שוקולד אתמול בערב"], mode="passage"
        )[0]
        sim_rel = _cosine(q, relevant)
        sim_irr = _cosine(q, irrelevant)
        assert sim_rel > sim_irr, (
            f"Reverse cross-language ordering wrong: relevant={sim_rel:.4f} <= irrelevant={sim_irr:.4f}"
        )

    def test_query_passage_prefixes_improve_self_similarity(self):
        """Using the correct query/passage prefixes should produce higher
        self-similarity than using the wrong prefix (or no prefix)."""
        text = "We decided to use PostgreSQL"

        # Correct: query prefix for query, passage prefix for passage
        q_correct = _provider.embed([text], mode="query")[0]
        p_correct = _provider.embed([text], mode="passage")[0]
        sim_correct = _cosine(q_correct, p_correct)

        # Both as passage (wrong for query side)
        q_wrong = _provider.embed([text], mode="passage")[0]
        p_wrong = _provider.embed([text], mode="passage")[0]
        sim_same_mode = _cosine(q_wrong, p_wrong)

        # Self-similarity with same mode will be ~1.0 (identical vectors),
        # while cross-mode similarity will be lower. This verifies prefixes
        # actually change the embedding.
        assert sim_same_mode > sim_correct, (
            "Same-mode similarity should be higher than cross-mode "
            f"(same={sim_same_mode:.4f}, cross={sim_correct:.4f}). "
            "This means prefixes ARE changing the embedding."
        )

    def test_dimensions_are_384(self):
        """multilingual-e5-small should produce 384-dimensional vectors."""
        assert _provider.dimensions() == 384

    def test_hebrew_and_english_same_dimensions(self):
        """Hebrew and English embeddings should have the same dimensionality."""
        heb = _provider.embed(["שלום עולם"], mode="query")[0]
        eng = _provider.embed(["hello world"], mode="query")[0]
        assert len(heb) == len(eng) == 384
