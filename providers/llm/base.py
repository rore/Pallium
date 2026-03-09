from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


FENCED_JSON_PATTERN = re.compile(r"^```(?:json)?\s*(?P<body>.*?)\s*```$", re.IGNORECASE | re.DOTALL)


class LLMProviderError(RuntimeError):
    pass


@dataclass(frozen=True)
class LLMJsonResponse:
    raw_text: str
    parsed_json: dict[str, Any]


class LLMProvider(ABC):
    @abstractmethod
    def generate_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        schema_description: str,
    ) -> LLMJsonResponse:
        raise NotImplementedError


def parse_json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if not cleaned:
        raise ValueError("LLM response was empty")

    fenced_match = FENCED_JSON_PATTERN.match(cleaned)
    if fenced_match:
        cleaned = fenced_match.group("body").strip()

    for candidate in (cleaned, _extract_braced_payload(cleaned)):
        if not candidate:
            continue
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if not isinstance(parsed, dict):
            raise ValueError("LLM response JSON must be an object")
        return parsed

    raise ValueError("Could not parse a JSON object from LLM response")


def _extract_braced_payload(text: str) -> str | None:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    return text[start : end + 1]
