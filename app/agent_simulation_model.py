from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.config import AppConfig
from app.dependencies import build_llm_provider
from providers.llm.base import LLMProviderError


THIN_AGENT_SYSTEM_PROMPT = """You are a thin downstream assistant using approved carry-forward context from Pallium.\nUse only the approved carry-forward blocks when they are present.\nDo not mention Pallium, retrieval traces, ranked candidates, or hidden system state.\nAnswer the user directly and briefly.\nReturn exactly one JSON object with a single string field named answer."""
ANSWER_SCHEMA_DESCRIPTION = '{"answer": "string"}'


@dataclass(frozen=True)
class ModelResolution:
    available: bool
    provider_name: str | None
    provider_kind: str | None
    model: str | None
    failure_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "provider_name": self.provider_name,
            "provider_kind": self.provider_kind,
            "model": self.model,
            "failure_reason": self.failure_reason,
        }


@dataclass(frozen=True)
class DraftResult:
    answer: str
    model_request: dict[str, Any]
    model_response: dict[str, Any]
    resolution: ModelResolution


class ModelUnavailableError(RuntimeError):
    pass


class ThinAgentModel:
    def __init__(
        self,
        *,
        config: AppConfig | None = None,
        provider_override: str | None = None,
        model_override: str | None = None,
        provider_factory=build_llm_provider,
    ) -> None:
        self._config = config
        self._provider_override = provider_override
        self._model_override = model_override
        self._provider_factory = provider_factory
        self._resolved_provider = None
        self._resolution: ModelResolution | None = None

    def resolution(self) -> ModelResolution:
        if self._resolution is not None:
            return self._resolution
        config = self._config or AppConfig.from_env()
        package = config.package_config(config.default_use_case)
        provider_name = self._provider_override or package.llm_provider
        model = self._model_override or package.model
        if not provider_name or not model:
            self._resolution = ModelResolution(
                available=False,
                provider_name=provider_name,
                provider_kind=None,
                model=model,
                failure_reason="No configured provider/model for the default use case",
            )
            return self._resolution
        try:
            provider_config = config.provider_config(provider_name)
        except KeyError:
            self._resolution = ModelResolution(
                available=False,
                provider_name=provider_name,
                provider_kind=None,
                model=model,
                failure_reason=f"Unknown provider config: {provider_name}",
            )
            return self._resolution
        try:
            self._resolved_provider = self._provider_factory(config, provider_name=provider_name, model=model)
        except Exception as exc:
            self._resolution = ModelResolution(
                available=False,
                provider_name=provider_name,
                provider_kind=provider_config.kind,
                model=model,
                failure_reason=str(exc),
            )
            return self._resolution
        self._resolution = ModelResolution(
            available=True,
            provider_name=provider_name,
            provider_kind=provider_config.kind,
            model=model,
        )
        return self._resolution

    def draft_answer(self, *, user_message: str, injectable_blocks: list[dict[str, Any]]) -> DraftResult:
        resolution = self.resolution()
        if not resolution.available or self._resolved_provider is None:
            raise ModelUnavailableError(resolution.failure_reason or "model unavailable")
        model_request = {
            "system_prompt": THIN_AGENT_SYSTEM_PROMPT,
            "user_prompt": build_user_prompt(user_message=user_message, injectable_blocks=injectable_blocks),
            "schema_description": ANSWER_SCHEMA_DESCRIPTION,
        }
        try:
            response = self._resolved_provider.generate_json(**model_request)
        except LLMProviderError:
            raise
        parsed = response.parsed_json
        answer = parsed.get("answer") if isinstance(parsed, dict) else None
        if not isinstance(answer, str) or not answer.strip():
            raise ModelUnavailableError("model response did not include a non-empty answer")
        metadata = response.metadata
        return DraftResult(
            answer=answer.strip(),
            model_request=model_request,
            model_response={
                "raw_text": response.raw_text,
                "parsed_json": parsed,
                "metadata": metadata.__dict__ if metadata is not None else None,
            },
            resolution=resolution,
        )


def build_user_prompt(*, user_message: str, injectable_blocks: list[dict[str, Any]]) -> str:
    lines = ["User message:", user_message.strip()]
    if injectable_blocks:
        lines.extend(["", "Approved carry-forward:"])
        for index, block in enumerate(injectable_blocks, start=1):
            title = block.get("title") or block.get("memory_type") or f"block-{index}"
            lines.append(f"{index}. {title}: {block.get('text', '').strip()}")
    else:
        lines.extend(["", "Approved carry-forward:", "(none)"])
    return "\n".join(lines)
