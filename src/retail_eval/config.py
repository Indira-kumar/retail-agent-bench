"""Configuration for Module 2 benchmark runs."""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from retail_agent.config import DEFAULT_LLM_MODEL, DEFAULT_STT_MODEL, DEFAULT_TTS_MODEL
from retail_agent.model_providers import LLMProvider, parse_llm_provider


@dataclass(frozen=True, slots=True)
class EvaluatorPipeline:
    stt: Any
    llm: Any
    tts: Any
    vad: Any


@dataclass(frozen=True, slots=True)
class BenchmarkConfig:
    livekit_url: str
    livekit_api_key: str
    livekit_api_secret: str
    agent_name: str = "retail-support-agent"
    output_dir: Path = Path("eval-runs")
    concurrency: int = 3
    task_timeout_seconds: float = 360.0
    report_timeout_seconds: float = 20.0
    evaluator_stt: str = DEFAULT_STT_MODEL
    evaluator_llm: str = DEFAULT_LLM_MODEL
    evaluator_tts: str = DEFAULT_TTS_MODEL
    evaluator_vad: Literal["silero"] = "silero"
    evaluator_llm_provider: LLMProvider = "livekit"

    def __post_init__(self) -> None:
        if not self.livekit_url or not self.livekit_api_key or not self.livekit_api_secret:
            raise ValueError("LIVEKIT_URL, LIVEKIT_API_KEY, and LIVEKIT_API_SECRET are required")
        if self.evaluator_llm_provider not in {"livekit", "openrouter"}:
            raise ValueError("evaluator_llm_provider must be 'livekit' or 'openrouter'")
        if not 1 <= self.concurrency <= 5:
            raise ValueError("concurrency must be between 1 and 5")
        if self.task_timeout_seconds <= 0 or self.report_timeout_seconds <= 0:
            raise ValueError("timeouts must be positive")

    @classmethod
    def from_env(
        cls,
        *,
        output_dir: Path | None = None,
        concurrency: int | None = None,
        task_timeout_seconds: float | None = None,
    ) -> BenchmarkConfig:
        return cls(
            livekit_url=os.getenv("LIVEKIT_URL", ""),
            livekit_api_key=os.getenv("LIVEKIT_API_KEY", ""),
            livekit_api_secret=os.getenv("LIVEKIT_API_SECRET", ""),
            agent_name=os.getenv("LIVEKIT_AGENT_NAME", "retail-support-agent"),
            output_dir=output_dir or Path(os.getenv("EVAL_OUTPUT_DIR", "eval-runs")),
            concurrency=concurrency or int(os.getenv("EVAL_CONCURRENCY", "3")),
            task_timeout_seconds=task_timeout_seconds
            or float(os.getenv("EVAL_TASK_TIMEOUT_SECONDS", "360")),
            report_timeout_seconds=float(os.getenv("EVAL_REPORT_TIMEOUT_SECONDS", "20")),
            evaluator_stt=os.getenv(
                "EVAL_STT_MODEL", os.getenv("RETAIL_STT_MODEL", DEFAULT_STT_MODEL)
            ),
            evaluator_llm=os.getenv(
                "EVAL_LLM_MODEL", os.getenv("RETAIL_LLM_MODEL", DEFAULT_LLM_MODEL)
            ),
            evaluator_llm_provider=parse_llm_provider(
                os.getenv("EVAL_LLM_PROVIDER", os.getenv("RETAIL_LLM_PROVIDER")),
                variable="EVAL_LLM_PROVIDER",
            ),
            evaluator_tts=os.getenv(
                "EVAL_TTS_MODEL", os.getenv("RETAIL_TTS_MODEL", DEFAULT_TTS_MODEL)
            ),
            evaluator_vad=_evaluator_vad(),
        )

    def public_dict(self) -> dict[str, Any]:
        values = asdict(self)
        values.pop("livekit_api_key")
        values.pop("livekit_api_secret")
        values["output_dir"] = str(self.output_dir)
        return values


def _evaluator_vad() -> Literal["silero"]:
    value = os.getenv("EVAL_VAD_MODEL", "silero")
    if value != "silero":
        raise ValueError("EVAL_VAD_MODEL must be 'silero'")
    return "silero"
