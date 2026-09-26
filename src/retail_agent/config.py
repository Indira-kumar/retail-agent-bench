"""Configuration owned by Module 1."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal

DEFAULT_STT_MODEL = "assemblyai/universal-3-5-pro:en"
DEFAULT_LLM_MODEL = "google/gemma-4-31b-it"
DEFAULT_TTS_MODEL = "fishaudio/s2.1-pro:fa4c9eb3dccc4806b382b40d61c6b10a"
DEFAULT_VAD_MODEL: Literal["silero"] = "silero"
DEFAULT_MIN_ENDPOINTING_DELAY = 0.5
DEFAULT_MAX_ENDPOINTING_DELAY = 3.0
DEFAULT_MAX_TOOL_STEPS = 8


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

    Model strings are LiveKit Inference descriptors. Callers that use provider plugins can
    instantiate ``AgentSession`` themselves while reusing ``RetailSupportAgent``.
    """

    stt: str = DEFAULT_STT_MODEL
    llm: str = DEFAULT_LLM_MODEL
    tts: str = DEFAULT_TTS_MODEL
    vad_model: Literal["silero"] = DEFAULT_VAD_MODEL
    min_endpointing_delay: float = DEFAULT_MIN_ENDPOINTING_DELAY
    max_endpointing_delay: float = DEFAULT_MAX_ENDPOINTING_DELAY
    max_tool_steps: int = DEFAULT_MAX_TOOL_STEPS
    preemptive_generation: bool = False

    def __post_init__(self) -> None:
        if not self.stt or not self.llm or not self.tts or not self.vad_model:
            raise ValueError("STT, LLM, TTS, and VAD model identifiers must be non-empty")
        if self.min_endpointing_delay < 0:
            raise ValueError("min_endpointing_delay cannot be negative")
        if self.max_endpointing_delay < self.min_endpointing_delay:
            raise ValueError("max_endpointing_delay must be at least min_endpointing_delay")
        if self.max_tool_steps < 1:
            raise ValueError("max_tool_steps must be positive")

    @classmethod
    def from_env(cls) -> VoicePipelineConfig:
        """Load the documented LiveKit Inference configuration from the environment."""

        vad_model = os.getenv("RETAIL_VAD_MODEL", DEFAULT_VAD_MODEL)
        if vad_model != "silero":
            raise ValueError("RETAIL_VAD_MODEL must be 'silero'")
        return cls(
            stt=os.getenv("RETAIL_STT_MODEL", DEFAULT_STT_MODEL),
            llm=os.getenv("RETAIL_LLM_MODEL", DEFAULT_LLM_MODEL),
            tts=os.getenv("RETAIL_TTS_MODEL", DEFAULT_TTS_MODEL),
            vad_model="silero",
            min_endpointing_delay=_read_float(
                "RETAIL_MIN_ENDPOINTING_DELAY", DEFAULT_MIN_ENDPOINTING_DELAY
            ),
            max_endpointing_delay=_read_float(
                "RETAIL_MAX_ENDPOINTING_DELAY", DEFAULT_MAX_ENDPOINTING_DELAY
            ),
            max_tool_steps=_read_int("RETAIL_MAX_TOOL_STEPS", DEFAULT_MAX_TOOL_STEPS),
        )
