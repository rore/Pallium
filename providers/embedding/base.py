from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Literal

EmbedMode = Literal["query", "passage"]


class EmbeddingProvider(ABC):
    """Abstract base for embedding providers. Batched by default."""

    @abstractmethod
    def embed(self, texts: list[str], *, mode: EmbedMode = "passage") -> list[list[float]]:
        """Embed a batch of texts. Returns one vector per input.

        mode controls prefix injection for models that require it
        (e.g., "query: " / "passage: " for E5 models).
        """

    @abstractmethod
    def dimensions(self) -> int:
        """Return the dimensionality of the embedding vectors."""

    @abstractmethod
    def model_name(self) -> str:
        """Return the model identifier used by this provider."""
