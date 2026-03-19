from __future__ import annotations

import logging

from providers.embedding.base import EmbeddingProvider

logger = logging.getLogger(__name__)


class FastEmbedProvider(EmbeddingProvider):
    """Embedding provider backed by fastembed.TextEmbedding.

    The fastembed import is lazy/guarded — when the package is not installed,
    instantiation raises a clear ImportError.

    Model bootstrap policy: The constructor eagerly initialises TextEmbedding
    so that the model is downloaded/verified at startup.  Background processing
    never triggers a model download — if the provider was not successfully
    initialised at startup, vector embedding is simply disabled.
    """

    def __init__(self, *, model: str, dimensions: int | None = None) -> None:
        try:
            from fastembed import TextEmbedding  # type: ignore[import-untyped]
        except ImportError as exc:
            raise ImportError(
                "fastembed is required for the FastEmbed embedding provider. "
                "Install it with: pip install fastembed"
            ) from exc

        self._model = model
        logger.info("Initialising FastEmbed model %s (this may download on first use)", model)
        self._engine: TextEmbedding = TextEmbedding(model_name=model)

        # Determine dimensions: use the explicit override, or probe by embedding
        # a single token so the value is always available.
        if dimensions is not None:
            self._dimensions = dimensions
        else:
            probe = list(self._engine.embed(["probe"]))
            self._dimensions = len(probe[0])

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        # fastembed.TextEmbedding.embed returns a generator of numpy arrays
        return [vec.tolist() for vec in self._engine.embed(texts)]

    def dimensions(self) -> int:
        return self._dimensions

    def model_name(self) -> str:
        return self._model
