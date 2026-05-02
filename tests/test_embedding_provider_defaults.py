"""Tests for embedding provider default model and min_similarity resolution."""

from __future__ import annotations

import pytest

from providers.embedding.base import EmbeddingProvider, EmbedMode
from providers.embedding.onnx_provider import (
    DEFAULT_MODEL_REPO,
    OnnxEmbeddingProvider,
    _KNOWN_MODEL_MIN_SIMILARITY,
)
from storage.vector_index import VectorIndexConfig


class TestDefaultModel:
    def test_default_model_is_e5_base(self):
        assert DEFAULT_MODEL_REPO == "intfloat/multilingual-e5-base"


class TestRecommendedMinSimilarity:
    def test_base_class_default_min_similarity(self):
        """EmbeddingProvider ABC returns 0.3 as the safe fallback."""

        class _Stub(EmbeddingProvider):
            def embed(self, texts: list[str], *, mode: EmbedMode = "passage") -> list[list[float]]:
                return []

            def dimensions(self) -> int:
                return 384

            def model_name(self) -> str:
                return "test-model"

        stub = _Stub()
        assert stub.recommended_min_similarity() == 0.3

    def test_recommended_min_similarity_for_known_model(self):
        """OnnxEmbeddingProvider returns 0.55 for E5 family models."""
        # Create an uninitialized instance to avoid model download
        instance = object.__new__(OnnxEmbeddingProvider)
        instance._model = "intfloat/multilingual-e5-base"
        assert instance.recommended_min_similarity() == 0.55

    def test_recommended_min_similarity_for_e5_small(self):
        """OnnxEmbeddingProvider returns 0.55 for e5-small."""
        instance = object.__new__(OnnxEmbeddingProvider)
        instance._model = "intfloat/multilingual-e5-small"
        assert instance.recommended_min_similarity() == 0.55

    def test_recommended_min_similarity_for_bge(self):
        """OnnxEmbeddingProvider returns 0.55 for BGE model."""
        instance = object.__new__(OnnxEmbeddingProvider)
        instance._model = "BAAI/bge-small-en-v1.5"
        assert instance.recommended_min_similarity() == 0.55

    def test_recommended_min_similarity_for_unknown_model(self):
        """OnnxEmbeddingProvider returns 0.3 for unknown models."""
        instance = object.__new__(OnnxEmbeddingProvider)
        instance._model = "some/unknown-model"
        assert instance.recommended_min_similarity() == 0.3

    def test_known_model_min_similarity_dict_completeness(self):
        """All E5 family models should have min_similarity entries."""
        expected_models = [
            "intfloat/multilingual-e5-small",
            "intfloat/multilingual-e5-base",
            "intfloat/multilingual-e5-large",
            "intfloat/e5-small-v2",
            "intfloat/e5-base-v2",
            "intfloat/e5-large-v2",
            "BAAI/bge-small-en-v1.5",
        ]
        for model in expected_models:
            assert model in _KNOWN_MODEL_MIN_SIMILARITY, f"Missing min_similarity for {model}"


class TestVectorIndexConfigNoneMinSimilarity:
    def test_default_min_similarity_is_none(self):
        """VectorIndexConfig defaults min_similarity to None."""
        config = VectorIndexConfig()
        assert config.min_similarity is None

    def test_explicit_min_similarity_preserved(self):
        """Explicit min_similarity value is preserved."""
        config = VectorIndexConfig(min_similarity=0.6)
        assert config.min_similarity == 0.6

    def test_min_similarity_none_explicit(self):
        """Explicitly passing None is valid."""
        config = VectorIndexConfig(min_similarity=None)
        assert config.min_similarity is None


class TestConfigResolution:
    def test_embedding_provider_config_empty_model(self):
        """EmbeddingProviderConfig defaults model to empty string."""
        from app.config import EmbeddingProviderConfig

        config = EmbeddingProviderConfig(name="test", kind="onnx")
        assert config.model == ""

    def test_resolve_optional_float_none_inputs(self):
        """_resolve_optional_float returns None when both inputs are None."""
        from app.config import _resolve_optional_float

        assert _resolve_optional_float(None, None) is None

    def test_resolve_optional_float_env_value(self):
        """_resolve_optional_float prefers env value."""
        from app.config import _resolve_optional_float

        assert _resolve_optional_float("0.7", 0.5) == 0.7

    def test_resolve_optional_float_config_value(self):
        """_resolve_optional_float uses config when env is None."""
        from app.config import _resolve_optional_float

        assert _resolve_optional_float(None, 0.6) == 0.6

    def test_resolve_optional_float_empty_env_string(self):
        """_resolve_optional_float treats empty string env as unset."""
        from app.config import _resolve_optional_float

        assert _resolve_optional_float("", 0.6) == 0.6

    def test_resolve_optional_float_empty_env_no_config(self):
        """_resolve_optional_float returns None for empty env and no config."""
        from app.config import _resolve_optional_float

        assert _resolve_optional_float("", None) is None
