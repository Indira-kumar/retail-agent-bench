"""Model-provider selection for the LiveKit voice pipelines."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Literal, cast

LLMProvider = Literal["livekit", "openrouter"]


@dataclass(frozen=True, slots=True)
class SpeechModels:
    stt: Any
    tts: Any


@dataclass(frozen=True, slots=True)
class DeepgramSpeechProvider:
    api_key: str | None = None

    def build(
        self,
        *,
        stt_model: str,
        tts_model: str,
        language: str,
    ) -> SpeechModels:
        api_key = self.api_key or os.getenv("DEEPGRAM_API_KEY")
        if not api_key:
            raise ValueError("DEEPGRAM_API_KEY is required for Deepgram STT and TTS")

        try:
            from livekit.plugins import deepgram
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "Deepgram speech support requires the LiveKit Deepgram plugin; "
                "install project dependencies with `uv sync`"
            ) from exc

        return SpeechModels(
            stt=deepgram.STT(model=stt_model, language=language, api_key=api_key),
            tts=deepgram.TTS(model=tts_model, api_key=api_key),
        )


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
        from livekit.plugins import openai
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "OpenRouter LLM support requires the LiveKit OpenAI plugin; "
            "install it with `uv sync --extra providers`"
        ) from exc

    return openai.LLM.with_openrouter(model=model)
