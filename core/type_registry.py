"""Type registry for multi-package routing.

Packages register their memory types at startup. The routing system reads
from the registry instead of hardcoded constants — no imports from the
semantic layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class TypeRegistration:
    """A single memory type registered by a semantic package."""

    type_name: str  # e.g., "decision", "atomic_fact"
    layer_name: str  # routing layer name (typically == type_name)
    weight_by_intent: dict[str, int]  # {"recall": 150, "structured_recall": 220, ...}
    default_weight: int  # fallback weight for unknown intents
    block_title: str  # e.g., "Decision", "Known Fact"
    block_text_field: str  # payload field for block text, e.g., "rationale"
    high_value: bool = False  # whether type is high-value for injection gating


class TypeRegistry:
    """Registry of memory types contributed by semantic packages.

    Populated at startup, read-only afterwards. Not thread-safe — callers
    must finish all ``register`` calls before any reads.
    """

    def __init__(self) -> None:
        self._types: dict[str, TypeRegistration] = {}

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, registration: TypeRegistration) -> None:
        """Register a memory type. Raises on duplicate type_name."""
        if registration.type_name in self._types:
            raise ValueError(
                f"Duplicate type registration: {registration.type_name!r}"
            )
        self._types[registration.type_name] = registration

    # ------------------------------------------------------------------
    # Single-type lookups
    # ------------------------------------------------------------------

    def get(self, type_name: str) -> TypeRegistration | None:
        """Return the registration for *type_name*, or ``None``."""
        return self._types.get(type_name)

    def get_weight(self, type_name: str, intent: str) -> int:
        """Return the routing weight for *type_name* under *intent*.

        Falls back to ``default_weight`` when the intent is not listed.
        Returns ``0`` if the type is not registered.
        """
        reg = self._types.get(type_name)
        if reg is None:
            return 0
        return reg.weight_by_intent.get(intent, reg.default_weight)

    def get_layer_name(self, type_name: str) -> str:
        """Return the routing layer name for *type_name*.

        Returns *type_name* itself if not registered (safe fallback).
        """
        reg = self._types.get(type_name)
        if reg is None:
            return type_name
        return reg.layer_name

    def get_block_title(self, type_name: str) -> str | None:
        """Return the block title for *type_name*, or ``None``."""
        reg = self._types.get(type_name)
        if reg is None:
            return None
        return reg.block_title

    def get_block_text_field(self, type_name: str) -> str | None:
        """Return the payload field name used as block text, or ``None``."""
        reg = self._types.get(type_name)
        if reg is None:
            return None
        return reg.block_text_field

    # ------------------------------------------------------------------
    # Aggregate queries
    # ------------------------------------------------------------------

    def all_types(self) -> list[TypeRegistration]:
        """Return all registrations in insertion order."""
        return list(self._types.values())

    def all_type_names(self) -> frozenset[str]:
        """Return the set of all registered type names."""
        return frozenset(self._types.keys())

    def all_layer_names(self) -> frozenset[str]:
        """Return the set of all registered layer names."""
        return frozenset(r.layer_name for r in self._types.values())

    def high_value_types(self) -> frozenset[str]:
        """Return type names where ``high_value`` is ``True``."""
        return frozenset(
            name for name, reg in self._types.items() if reg.high_value
        )

    def __len__(self) -> int:
        return len(self._types)

    def __contains__(self, type_name: str) -> bool:
        return type_name in self._types
