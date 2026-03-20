from __future__ import annotations

import sys
import types

import pytest

from app.config import AppConfig, EmbeddingProviderConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _FakeNdarray:
    """Minimal stand-in for a numpy ndarray — supports tolist() and len()."""

    def __init__(self, values: list[float]):
        self._values = values

    def tolist(self) -> list[float]:
        return list(self._values)

    def __len__(self) -> int:
        return len(self._values)


def _make_mock_fastembed_module(*, dimensions: int = 384):
    """Create a mock fastembed module with a working TextEmbedding stub."""
    mock_module = types.ModuleType("fastembed")

    class MockTextEmbedding:
        def __init__(self, model_name: str):
            self.model_name = model_name
            self._dims = dimensions

        def embed(self, texts):
            for _ in texts:
                yield _FakeNdarray([0.0] * self._dims)

    mock_module.TextEmbedding = MockTextEmbedding  # type: ignore[attr-defined]
    return mock_module


def _make_mock_onnx_modules(*, dimensions: int = 384):
    """Create mock onnxruntime, tokenizers, and huggingface_hub modules."""
    import numpy as np

    # Mock onnxruntime
    mock_ort = types.ModuleType("onnxruntime")

    class MockInferenceSession:
        def __init__(self, model_path, providers=None):
            self._dims = dimensions

        def run(self, output_names, inputs):
            batch_size = inputs["input_ids"].shape[0]
            # Return [batch, seq_len=1, dims] to simulate CLS pooling
            return [np.random.randn(batch_size, 1, self._dims).astype(np.float32)]

    mock_ort.InferenceSession = MockInferenceSession  # type: ignore[attr-defined]

    # Mock tokenizers
    mock_tokenizers = types.ModuleType("tokenizers")

    class MockEncoding:
        def __init__(self, length: int = 5):
            self.ids = list(range(length))

    class MockTokenizer:
        @classmethod
        def from_file(cls, path):
            return cls()

        def encode_batch(self, texts):
            return [MockEncoding() for _ in texts]

    mock_tokenizers.Tokenizer = MockTokenizer  # type: ignore[attr-defined]

    # Mock huggingface_hub
    mock_hf = types.ModuleType("huggingface_hub")

    def mock_download(repo_id=None, filename=None, **kwargs):
        return f"/fake/{repo_id}/{filename}"

    mock_hf.hf_hub_download = mock_download  # type: ignore[attr-defined]

    return mock_ort, mock_tokenizers, mock_hf


def _build_embedding_test_config(
    *,
    provider_name: str = "local",
    kind: str = "fastembed",
    model: str = "BAAI/bge-small-en-v1.5",
    dimensions: int | None = None,
) -> AppConfig:
    return AppConfig(
        embedding_providers={
            provider_name: EmbeddingProviderConfig(
                name=provider_name,
                kind=kind,
                model=model,
                dimensions=dimensions,
            )
        },
    )


# ---------------------------------------------------------------------------
# FastEmbedProvider — core behaviour (mock fastembed)
# ---------------------------------------------------------------------------

class TestFastEmbedProvider:
    def test_embed_returns_correct_number_of_vectors(self, monkeypatch):
        mock_module = _make_mock_fastembed_module(dimensions=384)
        monkeypatch.setitem(sys.modules, "fastembed", mock_module)

        from providers.embedding.fastembed_provider import FastEmbedProvider

        provider = FastEmbedProvider(model="BAAI/bge-small-en-v1.5")
        result = provider.embed(["hello", "world", "test"])

        assert len(result) == 3
        assert all(isinstance(vec, list) for vec in result)
        assert all(len(vec) == 384 for vec in result)

    def test_embed_returns_correct_dimensions(self, monkeypatch):
        mock_module = _make_mock_fastembed_module(dimensions=256)
        monkeypatch.setitem(sys.modules, "fastembed", mock_module)

        from providers.embedding.fastembed_provider import FastEmbedProvider

        provider = FastEmbedProvider(model="test-model")
        result = provider.embed(["single"])

        assert len(result) == 1
        assert len(result[0]) == 256

    def test_dimensions_probed_when_not_specified(self, monkeypatch):
        mock_module = _make_mock_fastembed_module(dimensions=768)
        monkeypatch.setitem(sys.modules, "fastembed", mock_module)

        from providers.embedding.fastembed_provider import FastEmbedProvider

        provider = FastEmbedProvider(model="test-model")
        assert provider.dimensions() == 768

    def test_dimensions_uses_explicit_override(self, monkeypatch):
        mock_module = _make_mock_fastembed_module(dimensions=768)
        monkeypatch.setitem(sys.modules, "fastembed", mock_module)

        from providers.embedding.fastembed_provider import FastEmbedProvider

        provider = FastEmbedProvider(model="test-model", dimensions=384)
        assert provider.dimensions() == 384

    def test_model_name_accessor(self, monkeypatch):
        mock_module = _make_mock_fastembed_module()
        monkeypatch.setitem(sys.modules, "fastembed", mock_module)

        from providers.embedding.fastembed_provider import FastEmbedProvider

        provider = FastEmbedProvider(model="BAAI/bge-small-en-v1.5")
        assert provider.model_name() == "BAAI/bge-small-en-v1.5"

    def test_embed_empty_list_returns_empty(self, monkeypatch):
        mock_module = _make_mock_fastembed_module()
        monkeypatch.setitem(sys.modules, "fastembed", mock_module)

        from providers.embedding.fastembed_provider import FastEmbedProvider

        provider = FastEmbedProvider(model="test-model")
        assert provider.embed([]) == []

    def test_embed_values_are_plain_floats(self, monkeypatch):
        """Vectors must be plain Python floats, not numpy scalars."""
        mock_module = _make_mock_fastembed_module(dimensions=3)
        monkeypatch.setitem(sys.modules, "fastembed", mock_module)

        from providers.embedding.fastembed_provider import FastEmbedProvider

        provider = FastEmbedProvider(model="test-model")
        result = provider.embed(["hello"])
        assert all(isinstance(v, float) for v in result[0])


# ---------------------------------------------------------------------------
# Import guard — fastembed not installed
# ---------------------------------------------------------------------------

class TestFastEmbedImportGuard:
    def test_import_error_when_fastembed_missing(self, monkeypatch):
        """When fastembed is not installed, constructing FastEmbedProvider
        raises a clear ImportError mentioning pip install."""
        # Setting a module to None in sys.modules makes import raise ImportError
        monkeypatch.setitem(sys.modules, "fastembed", None)

        from providers.embedding.fastembed_provider import FastEmbedProvider

        with pytest.raises(ImportError, match="fastembed is required"):
            FastEmbedProvider(model="BAAI/bge-small-en-v1.5")


# ---------------------------------------------------------------------------
# DI factory — build_embedding_provider
# ---------------------------------------------------------------------------

class TestBuildEmbeddingProvider:
    def test_builds_fastembed_provider(self, monkeypatch):
        mock_module = _make_mock_fastembed_module(dimensions=384)
        monkeypatch.setitem(sys.modules, "fastembed", mock_module)

        from app.dependencies import build_embedding_provider

        config = _build_embedding_test_config(model="BAAI/bge-small-en-v1.5")
        provider = build_embedding_provider(config, provider_name="local")

        assert provider.model_name() == "BAAI/bge-small-en-v1.5"
        assert provider.dimensions() == 384

    def test_raises_for_unknown_kind(self):
        config = _build_embedding_test_config(kind="unknown_kind")

        from app.dependencies import build_embedding_provider

        with pytest.raises(ValueError, match="Unsupported embedding provider kind"):
            build_embedding_provider(config, provider_name="local")

    def test_raises_for_unknown_provider_name(self):
        config = _build_embedding_test_config()

        from app.dependencies import build_embedding_provider

        with pytest.raises(KeyError, match="Unknown embedding provider config"):
            build_embedding_provider(config, provider_name="nonexistent")

    def test_passes_explicit_dimensions(self, monkeypatch):
        mock_module = _make_mock_fastembed_module(dimensions=768)
        monkeypatch.setitem(sys.modules, "fastembed", mock_module)

        from app.dependencies import build_embedding_provider

        config = _build_embedding_test_config(
            model="test-model",
            dimensions=512,
        )
        provider = build_embedding_provider(config, provider_name="local")
        # Explicit dimensions should override the probe
        assert provider.dimensions() == 512

    def test_builds_onnx_provider(self, monkeypatch):
        mock_ort, mock_tokenizers, mock_hf = _make_mock_onnx_modules(dimensions=384)
        monkeypatch.setitem(sys.modules, "onnxruntime", mock_ort)
        monkeypatch.setitem(sys.modules, "tokenizers", mock_tokenizers)
        monkeypatch.setitem(sys.modules, "huggingface_hub", mock_hf)

        from app.dependencies import build_embedding_provider

        config = _build_embedding_test_config(kind="onnx", model="BAAI/bge-small-en-v1.5")
        provider = build_embedding_provider(config, provider_name="local")

        assert provider.model_name() == "BAAI/bge-small-en-v1.5"
        assert provider.dimensions() == 384


# ---------------------------------------------------------------------------
# ONNX provider — import guard
# ---------------------------------------------------------------------------

class TestOnnxImportGuard:
    def test_import_error_when_onnxruntime_missing(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "onnxruntime", None)

        from providers.embedding.onnx_provider import OnnxEmbeddingProvider

        with pytest.raises(ImportError, match="onnxruntime is required"):
            OnnxEmbeddingProvider(model="BAAI/bge-small-en-v1.5")

    def test_import_error_when_tokenizers_missing(self, monkeypatch):
        # onnxruntime available but tokenizers missing
        mock_ort = types.ModuleType("onnxruntime")
        monkeypatch.setitem(sys.modules, "onnxruntime", mock_ort)
        monkeypatch.setitem(sys.modules, "tokenizers", None)

        from providers.embedding.onnx_provider import OnnxEmbeddingProvider

        with pytest.raises(ImportError, match="tokenizers is required"):
            OnnxEmbeddingProvider(model="BAAI/bge-small-en-v1.5")


# ---------------------------------------------------------------------------
# ONNX provider — core behavior (mocked)
# ---------------------------------------------------------------------------

class TestOnnxEmbeddingProvider:
    def test_embed_returns_correct_dimensions(self, monkeypatch):
        mock_ort, mock_tokenizers, mock_hf = _make_mock_onnx_modules(dimensions=384)
        monkeypatch.setitem(sys.modules, "onnxruntime", mock_ort)
        monkeypatch.setitem(sys.modules, "tokenizers", mock_tokenizers)
        monkeypatch.setitem(sys.modules, "huggingface_hub", mock_hf)

        from providers.embedding.onnx_provider import OnnxEmbeddingProvider

        provider = OnnxEmbeddingProvider(model="test-model")
        vecs = provider.embed(["hello world", "test"])
        assert len(vecs) == 2
        assert len(vecs[0]) == 384

    def test_embed_empty_list(self, monkeypatch):
        mock_ort, mock_tokenizers, mock_hf = _make_mock_onnx_modules()
        monkeypatch.setitem(sys.modules, "onnxruntime", mock_ort)
        monkeypatch.setitem(sys.modules, "tokenizers", mock_tokenizers)
        monkeypatch.setitem(sys.modules, "huggingface_hub", mock_hf)

        from providers.embedding.onnx_provider import OnnxEmbeddingProvider

        provider = OnnxEmbeddingProvider(model="test-model")
        assert provider.embed([]) == []

    def test_model_name(self, monkeypatch):
        mock_ort, mock_tokenizers, mock_hf = _make_mock_onnx_modules()
        monkeypatch.setitem(sys.modules, "onnxruntime", mock_ort)
        monkeypatch.setitem(sys.modules, "tokenizers", mock_tokenizers)
        monkeypatch.setitem(sys.modules, "huggingface_hub", mock_hf)

        from providers.embedding.onnx_provider import OnnxEmbeddingProvider

        provider = OnnxEmbeddingProvider(model="my-custom-model")
        assert provider.model_name() == "my-custom-model"

    def test_returns_plain_floats(self, monkeypatch):
        mock_ort, mock_tokenizers, mock_hf = _make_mock_onnx_modules(dimensions=3)
        monkeypatch.setitem(sys.modules, "onnxruntime", mock_ort)
        monkeypatch.setitem(sys.modules, "tokenizers", mock_tokenizers)
        monkeypatch.setitem(sys.modules, "huggingface_hub", mock_hf)

        from providers.embedding.onnx_provider import OnnxEmbeddingProvider

        provider = OnnxEmbeddingProvider(model="test-model")
        vecs = provider.embed(["test"])
        assert all(isinstance(v, float) for v in vecs[0])
