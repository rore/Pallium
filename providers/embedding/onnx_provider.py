from __future__ import annotations

import logging
from pathlib import Path

from providers.embedding.base import EmbeddingProvider

logger = logging.getLogger(__name__)

# Default model — same as fastembed default
DEFAULT_MODEL_REPO = "BAAI/bge-small-en-v1.5"
DEFAULT_ONNX_FILE = "onnx/model.onnx"
DEFAULT_TOKENIZER_FILE = "tokenizer.json"


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
        logger.info("Initialising ONNX embedding model %s (may download on first use)", model)

        # Download model files from HuggingFace Hub
        model_path, tokenizer_path = self._download_model(
            model, onnx_file, tokenizer_file, cache_dir
        )

        # Load ONNX session and tokenizer
        self._session = ort.InferenceSession(
            model_path, providers=["CPUExecutionProvider"]
        )
        self._tokenizer = Tokenizer.from_file(tokenizer_path)

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

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        import numpy as np

        encodings = self._tokenizer.encode_batch(texts)
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
