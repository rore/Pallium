"""Tests for quality_score computation from raw retrieval scores."""
from semantic.agent_conversation_memory_routing_scoring import _compute_quality_score
from semantic.agent_conversation_memory_routing_constants import normalize_lexical_score

def test_vector_dominant():
    assert abs(_compute_quality_score(lexical_score=2, vector_score=800) - 0.8) < 0.01

def test_lexical_dominant():
    assert abs(_compute_quality_score(lexical_score=5, vector_score=400) - 0.833) < 0.01

def test_clamps_lexical():
    assert abs(_compute_quality_score(lexical_score=8, vector_score=0) - 1.0) < 0.01

def test_zero_both():
    assert _compute_quality_score(lexical_score=0, vector_score=0) == 0.0


def test_normalize_lexical_score_strong_match():
    assert normalize_lexical_score(6.0) == 1.0

def test_normalize_lexical_score_half():
    assert abs(normalize_lexical_score(3.0) - 0.5) < 0.01

def test_normalize_lexical_score_caps_at_one():
    assert normalize_lexical_score(12.0) == 1.0

def test_normalize_lexical_score_none():
    assert normalize_lexical_score(None) == 0.0

def test_normalize_lexical_score_zero():
    assert normalize_lexical_score(0) == 0.0

def test_normalize_lexical_score_accepts_int():
    assert abs(normalize_lexical_score(3) - 0.5) < 0.01


def test_structured_recall_family_candidate_score():
    from semantic.agent_conversation_memory_routing_scoring import _query_family_candidate_score
    signals = {
        "layer_support": {}, "top_layers": [], "sharp_lower_level_in_scope": False,
        "strong_task_checkpoint_in_scope": False, "strong_source_evidence_in_scope": False,
        "relevant_cross_thread_continuity_in_scope": False, "continuity_topic_alignment_tokens": []
    }
    score, reasons = _query_family_candidate_score(
        "structured_recall", candidate_signals=signals, query_shape_tags=[], runtime_context=None
    )
    assert isinstance(score, int)
    assert isinstance(reasons, list)
