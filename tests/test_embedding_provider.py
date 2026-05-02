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

        def get_inputs(self):
            class _Input:
                def __init__(self, name):
                    self.name = name
            return [_Input("input_ids"), _Input("attention_mask"), _Input("token_type_ids")]

    mock_ort.InferenceSession = MockInferenceSession  # type: ignore[attr-defined]

    # Mock tokenizers
    mock_tokenizers = types.ModuleType("tokenizers")

    class MockEncoding:
        def __init__(self, length: int = 5):
            self.ids = list(range(length))
            self.overflowing: list = []

    class MockTokenizer:
        def __init__(self):
            self._max_length: int | None = None

        @classmethod
        def from_file(cls, path):
            return cls()

        def enable_truncation(self, max_length: int) -> None:
            self._max_length = max_length

        def encode_batch(self, texts):
            encodings = []
            for text in texts:
                # Simulate token count roughly proportional to word count
                token_count = max(1, len(text.split()))
                enc = MockEncoding(token_count)
                if self._max_length is not None and token_count > self._max_length:
                    overflow_ids = enc.ids[self._max_length:]
                    enc.ids = enc.ids[:self._max_length]
                    overflow_enc = MockEncoding(0)
                    overflow_enc.ids = overflow_ids
                    enc.overflowing = [overflow_enc]
                encodings.append(enc)
            return encodings

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
        monkeypatch.delitem(sys.modules, "providers.embedding.onnx_provider", raising=False)

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
    @pytest.fixture(autouse=True)
    def _clear_onnx_module_cache(self, monkeypatch):
        """Force re-import of onnx_provider so it binds to freshly mocked modules."""
        monkeypatch.delitem(sys.modules, "providers.embedding.onnx_provider", raising=False)

    def _setup_mock_onnx(self, monkeypatch, *, dimensions: int = 384):
        """Set up mock ONNX modules and force re-import of onnx_provider."""
        mock_ort, mock_tokenizers, mock_hf = _make_mock_onnx_modules(dimensions=dimensions)
        monkeypatch.setitem(sys.modules, "onnxruntime", mock_ort)
        monkeypatch.setitem(sys.modules, "tokenizers", mock_tokenizers)
        monkeypatch.setitem(sys.modules, "huggingface_hub", mock_hf)
        # Force re-import so onnx_provider binds to the mocked modules
        monkeypatch.delitem(sys.modules, "providers.embedding.onnx_provider", raising=False)

    def test_embed_returns_correct_dimensions(self, monkeypatch):
        self._setup_mock_onnx(monkeypatch, dimensions=384)

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

    def test_long_text_truncated_not_crashed(self, monkeypatch):
        """Text exceeding max_tokens is truncated instead of crashing the model."""
        mock_ort, mock_tokenizers, mock_hf = _make_mock_onnx_modules(dimensions=384)
        monkeypatch.setitem(sys.modules, "onnxruntime", mock_ort)
        monkeypatch.setitem(sys.modules, "tokenizers", mock_tokenizers)
        monkeypatch.setitem(sys.modules, "huggingface_hub", mock_hf)

        from providers.embedding.onnx_provider import OnnxEmbeddingProvider

        provider = OnnxEmbeddingProvider(model="test-model", max_tokens=10)
        # Generate text that would produce more than 10 tokens (one per word in mock)
        long_text = " ".join(f"word{i}" for i in range(100))
        vecs = provider.embed([long_text])
        assert len(vecs) == 1
        assert len(vecs[0]) == 384

    def test_long_text_does_not_poison_batch(self, monkeypatch):
        """One oversized text in a batch must not prevent other texts from embedding."""
        mock_ort, mock_tokenizers, mock_hf = _make_mock_onnx_modules(dimensions=384)
        monkeypatch.setitem(sys.modules, "onnxruntime", mock_ort)
        monkeypatch.setitem(sys.modules, "tokenizers", mock_tokenizers)
        monkeypatch.setitem(sys.modules, "huggingface_hub", mock_hf)

        from providers.embedding.onnx_provider import OnnxEmbeddingProvider

        provider = OnnxEmbeddingProvider(model="test-model", max_tokens=10)
        short_text = "hello world"
        long_text = " ".join(f"word{i}" for i in range(100))
        vecs = provider.embed([short_text, long_text, "another short"])
        assert len(vecs) == 3

    def test_truncation_logs_warning(self, monkeypatch, caplog):
        """Truncation emits a warning so oversized content is detectable."""
        mock_ort, mock_tokenizers, mock_hf = _make_mock_onnx_modules(dimensions=384)
        monkeypatch.setitem(sys.modules, "onnxruntime", mock_ort)
        monkeypatch.setitem(sys.modules, "tokenizers", mock_tokenizers)
        monkeypatch.setitem(sys.modules, "huggingface_hub", mock_hf)

        from providers.embedding.onnx_provider import OnnxEmbeddingProvider

        provider = OnnxEmbeddingProvider(model="test-model", max_tokens=10)
        long_text = " ".join(f"word{i}" for i in range(100))

        import logging
        with caplog.at_level(logging.WARNING, logger="providers.embedding.onnx_provider"):
            provider.embed([long_text])
        assert any("truncated" in r.message.lower() for r in caplog.records)


# ---------------------------------------------------------------------------
# EmbedMode prefix injection tests
# ---------------------------------------------------------------------------

class TestOnnxPrefixInjection:
    """Verify that query/passage prefixes are correctly injected."""

    @pytest.fixture(autouse=True)
    def _clear_onnx_module_cache(self, monkeypatch):
        monkeypatch.delitem(sys.modules, "providers.embedding.onnx_provider", raising=False)

    def test_query_prefix_prepended(self, monkeypatch):
        mock_ort, mock_tokenizers, mock_hf = _make_mock_onnx_modules(dimensions=4)
        monkeypatch.setitem(sys.modules, "onnxruntime", mock_ort)
        monkeypatch.setitem(sys.modules, "tokenizers", mock_tokenizers)
        monkeypatch.setitem(sys.modules, "huggingface_hub", mock_hf)

        from providers.embedding.onnx_provider import OnnxEmbeddingProvider

        captured_texts: list[list[str]] = []
        provider = OnnxEmbeddingProvider(
            model="test-model",
            query_prefix="query: ",
            passage_prefix="passage: ",
        )

        # Monkey-patch encode_batch to capture what texts reach the tokenizer
        original_encode = provider._tokenizer.encode_batch
        def capturing_encode(texts):
            captured_texts.append(list(texts))
            return original_encode(texts)
        provider._tokenizer.encode_batch = capturing_encode

        provider.embed(["hello world"], mode="query")
        assert len(captured_texts) == 1
        assert captured_texts[0] == ["query: hello world"]

    def test_passage_prefix_prepended(self, monkeypatch):
        mock_ort, mock_tokenizers, mock_hf = _make_mock_onnx_modules(dimensions=4)
        monkeypatch.setitem(sys.modules, "onnxruntime", mock_ort)
        monkeypatch.setitem(sys.modules, "tokenizers", mock_tokenizers)
        monkeypatch.setitem(sys.modules, "huggingface_hub", mock_hf)

        from providers.embedding.onnx_provider import OnnxEmbeddingProvider

        captured_texts: list[list[str]] = []
        provider = OnnxEmbeddingProvider(
            model="test-model",
            query_prefix="query: ",
            passage_prefix="passage: ",
        )

        original_encode = provider._tokenizer.encode_batch
        def capturing_encode(texts):
            captured_texts.append(list(texts))
            return original_encode(texts)
        provider._tokenizer.encode_batch = capturing_encode

        provider.embed(["hello world"], mode="passage")
        assert len(captured_texts) == 1
        assert captured_texts[0] == ["passage: hello world"]

    def test_no_prefix_when_not_configured(self, monkeypatch):
        mock_ort, mock_tokenizers, mock_hf = _make_mock_onnx_modules(dimensions=4)
        monkeypatch.setitem(sys.modules, "onnxruntime", mock_ort)
        monkeypatch.setitem(sys.modules, "tokenizers", mock_tokenizers)
        monkeypatch.setitem(sys.modules, "huggingface_hub", mock_hf)

        from providers.embedding.onnx_provider import OnnxEmbeddingProvider

        captured_texts: list[list[str]] = []
        provider = OnnxEmbeddingProvider(model="test-model")  # no prefixes

        original_encode = provider._tokenizer.encode_batch
        def capturing_encode(texts):
            captured_texts.append(list(texts))
            return original_encode(texts)
        provider._tokenizer.encode_batch = capturing_encode

        provider.embed(["hello world"], mode="query")
        assert len(captured_texts) == 1
        assert captured_texts[0] == ["hello world"]  # no prefix added

    def test_known_model_auto_detects_prefix(self, monkeypatch):
        """E5 models should auto-detect prefixes without explicit config."""
        mock_ort, mock_tokenizers, mock_hf = _make_mock_onnx_modules(dimensions=4)
        monkeypatch.setitem(sys.modules, "onnxruntime", mock_ort)
        monkeypatch.setitem(sys.modules, "tokenizers", mock_tokenizers)
        monkeypatch.setitem(sys.modules, "huggingface_hub", mock_hf)

        from providers.embedding.onnx_provider import OnnxEmbeddingProvider

        captured_texts: list[list[str]] = []
        # No explicit prefixes — should auto-detect from model name
        provider = OnnxEmbeddingProvider(model="intfloat/multilingual-e5-small")

        original_encode = provider._tokenizer.encode_batch
        def capturing_encode(texts):
            captured_texts.append(list(texts))
            return original_encode(texts)
        provider._tokenizer.encode_batch = capturing_encode

        provider.embed(["hello world"], mode="query")
        assert captured_texts[0] == ["query: hello world"]

        captured_texts.clear()
        provider.embed(["hello world"], mode="passage")
        assert captured_texts[0] == ["passage: hello world"]

    def test_hebrew_with_prefix(self, monkeypatch):
        """Hebrew text with query prefix should work correctly."""
        mock_ort, mock_tokenizers, mock_hf = _make_mock_onnx_modules(dimensions=4)
        monkeypatch.setitem(sys.modules, "onnxruntime", mock_ort)
        monkeypatch.setitem(sys.modules, "tokenizers", mock_tokenizers)
        monkeypatch.setitem(sys.modules, "huggingface_hub", mock_hf)

        from providers.embedding.onnx_provider import OnnxEmbeddingProvider

        captured_texts: list[list[str]] = []
        provider = OnnxEmbeddingProvider(
            model="test-model",
            query_prefix="query: ",
            passage_prefix="passage: ",
        )

        original_encode = provider._tokenizer.encode_batch
        def capturing_encode(texts):
            captured_texts.append(list(texts))
            return original_encode(texts)
        provider._tokenizer.encode_batch = capturing_encode

        provider.embed(["שלום עולם"], mode="query")
        assert captured_texts[0] == ["query: שלום עולם"]

        captured_texts.clear()
        provider.embed(["שלום עולם"], mode="passage")
        assert captured_texts[0] == ["passage: שלום עולם"]
