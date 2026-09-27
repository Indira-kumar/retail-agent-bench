"""Model-provider selection for the LiveKit voice pipelines."""

from __future__ import annotations

import os
from typing import Any, Literal, cast

LLMProvider = Literal["livekit", "openrouter"]


def parse_llm_provider(value: str | None, *, variable: str) -> LLMProvider:
    provider = (value or "livekit").strip().lower()
    if provider not in {"livekit", "openrouter"}:
        raise ValueError(f"{variable} must be 'livekit' or 'openrouter'")
    return cast(LLMProvider, provider)


def build_llm(*, provider: LLMProvider, model: str) -> Any:
    if provider == "livekit":
        return model

    if not os.getenv("OPENROUTER_API_KEY"):
        raise ValueError("OPENROUTER_API_KEY is required when the LLM provider is openrouter")

    try:
        from livekit.plugins import openai  # type: ignore[import-untyped]
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "OpenRouter LLM support requires the LiveKit OpenAI plugin; "
            "install it with `uv sync --extra providers`"
        ) from exc

    return openai.LLM.with_openrouter(model=model)
