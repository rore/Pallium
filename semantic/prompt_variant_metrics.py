from __future__ import annotations

import math


def prompt_text_metrics(text: str) -> dict[str, int]:
    normalized = str(text or '')
    return {
        'chars': len(normalized),
        'words': len(normalized.split()),
        'estimated_tokens': math.ceil(len(normalized) / 4) if normalized else 0,
    }


def describe_prompt_variants(variants: dict[str, str]) -> dict[str, dict[str, int]]:
    return {name: prompt_text_metrics(text) for name, text in variants.items()}
