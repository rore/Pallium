from __future__ import annotations

from abc import ABC, abstractmethod


class EmbeddingProvider(ABC):
    """Abstract base for embedding providers. Batched by default."""

    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts. Returns one vector per input."""

    @abstractmethod
    def dimensions(self) -> int:
        """Return the dimensionality of the embedding vectors."""

    @abstractmethod
    def model_name(self) -> str:
        """Return the model identifier used by this provider."""
