"""Configuration owned by Module 1."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal

from retail_agent.model_providers import LLMProvider, parse_llm_provider

DEFAULT_STT_MODEL = "nova-3"
DEFAULT_STT_LANGUAGE = "en-US"
DEFAULT_LLM_MODEL = "google/gemma-4-31b-it"
DEFAULT_TTS_MODEL = "aura-2-andromeda-en"
DEFAULT_VAD_MODEL: Literal["silero"] = "silero"
DEFAULT_MIN_ENDPOINTING_DELAY = 0.5
DEFAULT_MAX_ENDPOINTING_DELAY = 3.0
DEFAULT_MAX_TOOL_STEPS = 8
DEFAULT_STT_MAX_RETRY = 5
DEFAULT_STT_RETRY_INTERVAL = 1.0
DEFAULT_STT_CONNECT_TIMEOUT = 10.0


def _read_float(name: str, default: float) -> float:
    value = os.getenv(name)
    return default if value is None else float(value)


def _read_int(name: str, default: int) -> int:
    value = os.getenv(name)
    return default if value is None else int(value)


@dataclass(frozen=True, slots=True)
class RetailAgentConfig:
    """Business-facing behavior that is independent of media providers."""

    greeting_instructions: str = (
        "Greet the customer briefly and ask how you can help. "
        "Do not claim that the customer is authenticated."
    )
    voice_instructions: str = (
        "This is a spoken customer-support conversation. Keep responses concise and use "
        "plain sentences that sound natural when spoken. Ask one focused question at a time. "
        "Read back critical order, item, address, and payment details before requesting "
        "confirmation. A database-changing tool may be called only after the customer gives "
        "an explicit yes to the exact action details. Never treat silence, a partial transcript, "
        "or an ambiguous acknowledgement as confirmation. Call at most one tool at a time; "
        "wait for its result before deciding what to do next."
    )


@dataclass(frozen=True, slots=True)
class VoicePipelineConfig:
    """LiveKit voice-pipeline settings.

    STT and TTS use the direct Deepgram provider. The LLM can use either a LiveKit Inference
    descriptor or the OpenRouter provider plugin via ``llm_provider``.
    """

    stt: str = DEFAULT_STT_MODEL
    stt_language: str = DEFAULT_STT_LANGUAGE
    llm: str = DEFAULT_LLM_MODEL
    tts: str = DEFAULT_TTS_MODEL
    vad_model: Literal["silero"] = DEFAULT_VAD_MODEL
    min_endpointing_delay: float = DEFAULT_MIN_ENDPOINTING_DELAY
    max_endpointing_delay: float = DEFAULT_MAX_ENDPOINTING_DELAY
    max_tool_steps: int = DEFAULT_MAX_TOOL_STEPS
    preemptive_generation: bool = False
    llm_provider: LLMProvider = "livekit"
    stt_max_retry: int = DEFAULT_STT_MAX_RETRY
    stt_retry_interval: float = DEFAULT_STT_RETRY_INTERVAL
    stt_connect_timeout: float = DEFAULT_STT_CONNECT_TIMEOUT

    def __post_init__(self) -> None:
        if (
            not self.stt
            or not self.stt_language
            or not self.llm
            or not self.tts
            or not self.vad_model
        ):
            raise ValueError("STT, STT language, LLM, TTS, and VAD values must be non-empty")
        if self.llm_provider not in {"livekit", "openrouter"}:
            raise ValueError("llm_provider must be 'livekit' or 'openrouter'")
        if self.min_endpointing_delay < 0:
            raise ValueError("min_endpointing_delay cannot be negative")
        if self.max_endpointing_delay < self.min_endpointing_delay:
            raise ValueError("max_endpointing_delay must be at least min_endpointing_delay")
        if self.max_tool_steps < 1:
            raise ValueError("max_tool_steps must be positive")
        if self.stt_max_retry < 0:
            raise ValueError("stt_max_retry cannot be negative")
        if self.stt_retry_interval < 0 or self.stt_connect_timeout <= 0:
            raise ValueError("STT retry interval cannot be negative and timeout must be positive")

    @classmethod
    def from_env(cls) -> VoicePipelineConfig:
        vad_model = os.getenv("RETAIL_VAD_MODEL", DEFAULT_VAD_MODEL)
        if vad_model != "silero":
            raise ValueError("RETAIL_VAD_MODEL must be 'silero'")
        return cls(
            stt=os.getenv("RETAIL_STT_MODEL", DEFAULT_STT_MODEL),
            stt_language=os.getenv("RETAIL_STT_LANGUAGE", DEFAULT_STT_LANGUAGE),
            llm=os.getenv("RETAIL_LLM_MODEL", DEFAULT_LLM_MODEL),
            llm_provider=parse_llm_provider(
                os.getenv("RETAIL_LLM_PROVIDER"), variable="RETAIL_LLM_PROVIDER"
            ),
            tts=os.getenv("RETAIL_TTS_MODEL", DEFAULT_TTS_MODEL),
            vad_model="silero",
            min_endpointing_delay=_read_float(
                "RETAIL_MIN_ENDPOINTING_DELAY", DEFAULT_MIN_ENDPOINTING_DELAY
            ),
            max_endpointing_delay=_read_float(
                "RETAIL_MAX_ENDPOINTING_DELAY", DEFAULT_MAX_ENDPOINTING_DELAY
            ),
            max_tool_steps=_read_int("RETAIL_MAX_TOOL_STEPS", DEFAULT_MAX_TOOL_STEPS),
            stt_max_retry=_read_int("RETAIL_STT_MAX_RETRY", DEFAULT_STT_MAX_RETRY),
            stt_retry_interval=_read_float("RETAIL_STT_RETRY_INTERVAL", DEFAULT_STT_RETRY_INTERVAL),
            stt_connect_timeout=_read_float(
                "RETAIL_STT_CONNECT_TIMEOUT", DEFAULT_STT_CONNECT_TIMEOUT
            ),
        )
