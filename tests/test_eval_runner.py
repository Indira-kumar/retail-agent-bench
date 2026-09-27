from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from retail_eval import livekit_runner
from retail_eval.config import BenchmarkConfig
from retail_eval.livekit_runner import _wait_for_trial_end, default_pipeline
from retail_eval.runner import run_bounded
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
