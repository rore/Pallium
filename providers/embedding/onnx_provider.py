from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from providers.embedding.base import EmbedMode, EmbeddingProvider

logger = logging.getLogger(__name__)

# Default model — same as fastembed default
DEFAULT_MODEL_REPO = "BAAI/bge-small-en-v1.5"
DEFAULT_ONNX_FILE = "onnx/model.onnx"
DEFAULT_TOKENIZER_FILE = "tokenizer.json"
DEFAULT_MAX_TOKENS = 512  # BERT-family position embedding limit (bge, e5, etc.)

# Known model prefix defaults.  E5-family models require "query: " / "passage: "
# prefixes for correct asymmetric retrieval.  Config values override these.
_KNOWN_MODEL_PREFIXES: dict[str, tuple[str, str]] = {
    "intfloat/multilingual-e5-small": ("query: ", "passage: "),
    "intfloat/multilingual-e5-base": ("query: ", "passage: "),
    "intfloat/multilingual-e5-large": ("query: ", "passage: "),
    "intfloat/e5-small-v2": ("query: ", "passage: "),
    "intfloat/e5-base-v2": ("query: ", "passage: "),
    "intfloat/e5-large-v2": ("query: ", "passage: "),
}

# Process-level cache: keyed by (model_path, tokenizer_path).
# ort.InferenceSession and Tokenizer are stateless after init — safe to share
# across provider instances within the same process.
_SESSION_CACHE: dict[tuple[str, str], tuple[Any, Any]] = {}


class OnnxEmbeddingProvider(EmbeddingProvider):
    """Embedding provider using onnxruntime + tokenizers directly.

    Bypasses fastembed entirely — for environments where fastembed is unavailable
    (fastembed requires Python 3.12/3.13 due to py-rust-stemmers). Uses the same ONNX models
    from HuggingFace Hub, producing identical embeddings.

    Model bootstrap policy: The constructor eagerly downloads (if needed)
    and loads the model.  Background processing never triggers a download.
    """

    def __init__(
        self,
        *,
        model: str = DEFAULT_MODEL_REPO,
        onnx_file: str = DEFAULT_ONNX_FILE,
        tokenizer_file: str = DEFAULT_TOKENIZER_FILE,
        dimensions: int | None = None,
        cache_dir: str | None = None,
        query_prefix: str = "",
        passage_prefix: str = "",
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> None:
        try:
            import onnxruntime as ort  # noqa: F811
        except ImportError as exc:
            raise ImportError(
                "onnxruntime is required for the ONNX embedding provider. "
                "Install it with: pip install onnxruntime"
            ) from exc

        try:
            from tokenizers import Tokenizer  # type: ignore[import-untyped]
        except ImportError as exc:
            raise ImportError(
                "tokenizers is required for the ONNX embedding provider. "
                "Install it with: pip install tokenizers"
            ) from exc

        self._model = model
        self._max_tokens = max_tokens
        # Resolve prefixes: explicit config wins, then known model defaults, then empty
        known = _KNOWN_MODEL_PREFIXES.get(model, ("", ""))
        self._query_prefix = query_prefix if query_prefix else known[0]
        self._passage_prefix = passage_prefix if passage_prefix else known[1]
        logger.info("Initialising ONNX embedding model %s (may download on first use)", model)

        # Download model files from HuggingFace Hub
        model_path, tokenizer_path = self._download_model(
            model, onnx_file, tokenizer_file, cache_dir
        )

        cache_key = (model_path, tokenizer_path)
        if cache_key in _SESSION_CACHE:
            self._session, self._tokenizer = _SESSION_CACHE[cache_key]
        else:
            # Load ONNX session and tokenizer
            self._session = ort.InferenceSession(
                model_path, providers=["CPUExecutionProvider"]
            )
            self._tokenizer = Tokenizer.from_file(tokenizer_path)
            _SESSION_CACHE[cache_key] = (self._session, self._tokenizer)

        # Truncate sequences to model's max position embedding length.
        # Without this, texts exceeding the limit crash the ONNX model.
        self._tokenizer.enable_truncation(max_length=max_tokens)

        # Determine dimensions
        if dimensions is not None:
            self._dimensions = dimensions
        else:
            probe = self.embed(["probe"])
            self._dimensions = len(probe[0])

    @staticmethod
    def _download_model(
        model: str, onnx_file: str, tokenizer_file: str, cache_dir: str | None
    ) -> tuple[str, str]:
        try:
            from huggingface_hub import hf_hub_download
        except ImportError as exc:
            raise ImportError(
                "huggingface_hub is required to download embedding models. "
                "Install it with: pip install huggingface-hub"
            ) from exc

        kwargs = {"repo_id": model}
        if cache_dir is not None:
            kwargs["cache_dir"] = cache_dir

        model_path = hf_hub_download(filename=onnx_file, **kwargs)
        tokenizer_path = hf_hub_download(filename=tokenizer_file, **kwargs)
        return model_path, tokenizer_path

    def embed(self, texts: list[str], *, mode: EmbedMode = "passage") -> list[list[float]]:
        if not texts:
            return []

        prefix = self._query_prefix if mode == "query" else self._passage_prefix
        if prefix:
            texts = [prefix + t for t in texts]

        import numpy as np

        encodings = self._tokenizer.encode_batch(texts)

        # Warn when truncation occurs so we can detect content being silently cut
        for i, enc in enumerate(encodings):
            if enc.overflowing:
                logger.warning(
                    "Embedding text truncated from %d to %d tokens (index %d in batch of %d)",
                    len(enc.ids) + sum(len(o.ids) for o in enc.overflowing),
                    len(enc.ids),
                    i,
                    len(texts),
                )

        max_len = max(len(e.ids) for e in encodings)

        input_ids = np.zeros((len(texts), max_len), dtype=np.int64)
        attention_mask = np.zeros((len(texts), max_len), dtype=np.int64)
        token_type_ids = np.zeros((len(texts), max_len), dtype=np.int64)

        for i, enc in enumerate(encodings):
            length = len(enc.ids)
            input_ids[i, :length] = enc.ids
            attention_mask[i, :length] = 1

        outputs = self._session.run(
            None,
            {
                "input_ids": input_ids,
                "attention_mask": attention_mask,
                "token_type_ids": token_type_ids,
            },
        )

        # CLS token pooling + L2 normalization
        embeddings = outputs[0][:, 0, :]
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        normalized = embeddings / np.maximum(norms, 1e-12)

        return [vec.tolist() for vec in normalized]

    def dimensions(self) -> int:
        return self._dimensions

    def model_name(self) -> str:
        return self._model
