from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from retail_eval import livekit_runner
from retail_eval.config import BenchmarkConfig
from retail_eval.livekit_runner import (
    _remove_spoken_stage_directions,
    _wait_for_trial_end,
    default_pipeline,
)
from retail_eval.runner import _score, _validate_scorer_credentials, run_bounded
from retail_eval.trace import EvaluatorEventCollector, RoomTraceCollector


async def test_run_bounded_limits_parallel_rooms() -> None:
    active = 0
    maximum = 0
    lock = asyncio.Lock()

    async def execute(value: int) -> int:
        nonlocal active, maximum
        async with lock:
            active += 1
            maximum = max(maximum, active)
        await asyncio.sleep(0.01)
        async with lock:
            active -= 1
        return value * 2

    results = await run_bounded(range(10), concurrency=3, execute=execute)

    assert results == [value * 2 for value in range(10)]
    assert maximum == 3


def test_default_eval_pipeline_uses_deepgram_for_speech(monkeypatch: Any) -> None:
    monkeypatch.setenv("DEEPGRAM_API_KEY", "test-key")
    monkeypatch.setattr(livekit_runner.inference, "VAD", lambda **kwargs: kwargs)
    config = BenchmarkConfig(
        livekit_url="wss://example.test",
        livekit_api_key="key",
        livekit_api_secret="secret",
        output_dir=Path("eval-runs"),
    )

    pipeline = default_pipeline(config)

    assert pipeline.stt.provider == "Deepgram"
    assert pipeline.stt.model == "nova-3"
    assert pipeline.tts.provider == "Deepgram"
    assert pipeline.tts.model == "aura-2-andromeda-en"


def test_tau_scorer_defaults_to_openrouter(monkeypatch: Any) -> None:
    monkeypatch.setenv("LIVEKIT_URL", "wss://example.test")
    monkeypatch.setenv("LIVEKIT_API_KEY", "key")
    monkeypatch.setenv("LIVEKIT_API_SECRET", "secret")
    monkeypatch.setenv("RETAIL_LLM_MODEL", "google/gemma-4-31b-it")
    monkeypatch.delenv("EVAL_SCORER_LLM", raising=False)

    config = BenchmarkConfig.from_env()

    assert config.scorer_llm == "openrouter/google/gemma-4-31b-it"
    assert config.scorer_max_attempts == 3
    assert config.scorer_retry_delay_seconds == 1.0


def test_openrouter_scorer_fails_before_run_without_credentials(monkeypatch: Any) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
        _validate_scorer_credentials("openrouter/google/gemma-4-31b-it")


def test_tau_scorer_rejects_non_openrouter_models() -> None:
    with pytest.raises(ValueError, match="openrouter/<model>"):
        _validate_scorer_credentials("gpt-4.1-2025-04-14")


async def test_scorer_requests_json_and_retries_invalid_responses(monkeypatch: Any) -> None:
    from tau2.evaluator import evaluator as tau_evaluator
    from tau2.evaluator import evaluator_nl_assertions

    attempts = 0
    expected_reward = object()

    def evaluate_simulation(**kwargs: object) -> object:
        del kwargs
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise json.JSONDecodeError("invalid scorer response", "", 0)
        return expected_reward

    monkeypatch.setattr(tau_evaluator, "evaluate_simulation", evaluate_simulation)
    simulation = SimpleNamespace(reward_info=None)
    result = SimpleNamespace(simulation=simulation)

    await _score(
        cast(Any, result),
        task=object(),
        scorer_llm="openrouter/test-model",
        max_attempts=3,
        retry_delay_seconds=0,
    )

    assert attempts == 3
    assert simulation.reward_info is expected_reward
    assert evaluator_nl_assertions.DEFAULT_LLM_NL_ASSERTIONS_ARGS["response_format"] == {
        "type": "json_object"
    }


async def test_scorer_raises_after_last_attempt(monkeypatch: Any) -> None:
    from tau2.evaluator import evaluator as tau_evaluator

    def evaluate_simulation(**kwargs: object) -> object:
        del kwargs
        raise json.JSONDecodeError("invalid scorer response", "", 0)

    monkeypatch.setattr(tau_evaluator, "evaluate_simulation", evaluate_simulation)
    result = SimpleNamespace(simulation=SimpleNamespace(reward_info=None))

    with pytest.raises(json.JSONDecodeError):
        await _score(
            cast(Any, result),
            task=object(),
            scorer_llm="openrouter/test-model",
            max_attempts=2,
            retry_delay_seconds=0,
        )


async def test_tts_stage_directions_are_removed_across_chunks() -> None:
    async def text_chunks() -> Any:
        for chunk in ("Let me think [pa", "use] about it (beat). Okay."):
            yield chunk

    spoken = "".join([chunk async for chunk in _remove_spoken_stage_directions(text_chunks())])

    assert spoken == "Let me think — about it —. Okay."
    assert "pause" not in spoken
    assert "beat" not in spoken


async def test_trial_ends_after_terminal_tool_response() -> None:
    room_trace = RoomTraceCollector()
    room_trace.terminal_reason = "transfer"
    room_trace.terminal_tool_completed.set()
    room_trace.terminal_response_received.set()

    reason = await _wait_for_trial_end(
        customer_completion=asyncio.Event(),
        room_trace=room_trace,
        evaluator_events=EvaluatorEventCollector(),
        timeout_seconds=1,
    )

    assert reason == "transfer"


async def test_trial_ends_when_evaluator_session_closes() -> None:
    evaluator_events = EvaluatorEventCollector()
    evaluator_events.session_closed.set()

    reason = await _wait_for_trial_end(
        customer_completion=asyncio.Event(),
        room_trace=RoomTraceCollector(),
        evaluator_events=evaluator_events,
        timeout_seconds=1,
    )

    assert reason == "infrastructure_error"
