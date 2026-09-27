"""One-room execution of a tau retail voice scenario."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast
from uuid import uuid4

from livekit import api, rtc
from livekit.agents import (
    Agent,
    AgentSession,
    RunContext,
    TurnHandlingOptions,
    function_tool,
    inference,
    llm,
)
from livekit.agents.utils import http_context

from retail_agent.trace_transport import CONTROL_TOPIC
from retail_eval.artifacts import TrialPaths
from retail_eval.audio import RecordingAudioInput, RecordingAudioOutput, WavWriter
from retail_eval.config import BenchmarkConfig, EvaluatorPipeline
from retail_eval.trace import EvaluatorEventCollector, RoomTraceCollector, build_tau_messages

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class TrialResult:
    simulation: Any
    trace_messages: list[dict[str, Any]]
    evaluator_events: list[dict[str, Any]]
    evaluator_history: dict[str, Any]
    session_report: dict[str, Any] | None


PipelineFactory = Callable[[BenchmarkConfig], EvaluatorPipeline]


class LiveKitTrialRunner:
    def __init__(
        self,
        config: BenchmarkConfig,
        *,
        pipeline_factory: PipelineFactory | None = None,
    ) -> None:
        self._config = config
        self._pipeline_factory = pipeline_factory or default_pipeline

    async def run(self, *, task: Any, trial: int, paths: TrialPaths, policy: str) -> TrialResult:
        async with http_context.open():
            return await self._run(task=task, trial=trial, paths=paths, policy=policy)

    async def _run(self, *, task: Any, trial: int, paths: TrialPaths, policy: str) -> TrialResult:
        run_id = f"task-{task.id}-trial-{trial}-{uuid4().hex[:8]}"
        room_name = f"retail-eval-{run_id}"
        completion = asyncio.Event()
        completion_reason = "complete"

        async def finish_benchmark(
            raw_arguments: dict[str, object], context: RunContext[Any]
        ) -> str:
            del context
            nonlocal completion_reason
            completion_reason = str(raw_arguments.get("reason", "complete"))
            completion.set()
            return "The benchmark controller will end the call."

        finish_benchmark.__name__ = "finish_benchmark"
        finish_tool = cast(
            llm.Tool,
            function_tool(
                finish_benchmark,
                raw_schema={
                    "type": "function",
                    "name": "finish_benchmark",
                    "description": (
                        "End the benchmark after the caller's goal is resolved or cannot continue."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "reason": {
                                "type": "string",
                                "enum": ["complete", "transfer", "out_of_scope"],
                            }
                        },
                        "required": ["reason"],
                    },
                },
            ),
        )
        evaluator = Agent(
            instructions=_caller_instructions(task),
            tools=[finish_tool],
        )
        pipeline = self._pipeline_factory(self._config)
        session: AgentSession[Any] = AgentSession(
            stt=pipeline.stt,
            llm=pipeline.llm,
            tts=pipeline.tts,
            vad=pipeline.vad,
            turn_handling=TurnHandlingOptions(
                turn_detection="vad",
                endpointing={"mode": "fixed", "min_delay": 0.5, "max_delay": 3.0},
                interruption={"mode": "vad"},
                preemptive_generation={"enabled": False},
            ),
            max_tool_steps=3,
        )
        evaluator_events = EvaluatorEventCollector()
        evaluator_events.attach(session)

        room = rtc.Room()
        room_trace = RoomTraceCollector()
        room_trace.attach(room)
        token = _room_token(self._config, room_name, run_id)
        started_at = datetime.now(UTC)
        started_monotonic = time.monotonic()
        termination_reason = "user_stop"
        error: Exception | None = None
        agent_dispatched = False

        input_writer = WavWriter(paths.input_audio)
        output_writer = WavWriter(paths.output_audio)
        try:
            await room.connect(self._config.livekit_url, token)
            await session.start(agent=evaluator, room=room, record=False)
            _attach_audio_recorders(session, input_writer, output_writer)
            await self._dispatch_agent(room_name, task, trial, run_id)
            agent_dispatched = True
            try:
                await asyncio.wait_for(completion.wait(), self._config.task_timeout_seconds)
            except TimeoutError:
                termination_reason = "timeout"

            if completion.is_set():
                audio_output = session.output.audio
                if audio_output is not None:
                    await audio_output.wait_for_playout()
        except Exception as exc:
            error = exc
            termination_reason = "infrastructure_error"
            logger.exception("Benchmark trial failed for task %s trial %s", task.id, trial)
        finally:
            if agent_dispatched:
                await _stop_retail_agent(
                    room=room,
                    room_trace=room_trace,
                    run_id=run_id,
                    reason=(completion_reason if completion.is_set() else termination_reason),
                    report_timeout_seconds=self._config.report_timeout_seconds,
                )
            evaluator_history = session.history.to_dict()
            await session.aclose()
            await room.disconnect()
            input_writer.close()
            output_writer.close()

        ended_at = datetime.now(UTC)
        messages = build_tau_messages(room_trace.messages)
        simulation = _build_simulation(
            run_id=run_id,
            task=task,
            trial=trial,
            policy=policy,
            messages=messages,
            started_at=started_at,
            ended_at=ended_at,
            duration=time.monotonic() - started_monotonic,
            termination_reason=termination_reason,
            room_name=room_name,
            error=error,
        )
        if error is not None:
            simulation.info = {**(simulation.info or {}), "error": repr(error)}
        return TrialResult(
            simulation=simulation,
            trace_messages=room_trace.messages,
            evaluator_events=evaluator_events.events,
            evaluator_history=evaluator_history,
            session_report=room_trace.session_report,
        )

    async def _dispatch_agent(self, room_name: str, task: Any, trial: int, run_id: str) -> None:
        livekit_api = api.LiveKitAPI(
            url=self._config.livekit_url,
            api_key=self._config.livekit_api_key,
            api_secret=self._config.livekit_api_secret,
        )
        try:
            await livekit_api.agent_dispatch.create_dispatch(
                api.CreateAgentDispatchRequest(
                    agent_name=self._config.agent_name,
                    room=room_name,
                    metadata=json.dumps(
                        {"task_id": str(task.id), "trial": trial, "run_id": run_id}
                    ),
                )
            )
        finally:
            await livekit_api.aclose()


async def _stop_retail_agent(
    *,
    room: rtc.Room,
    room_trace: RoomTraceCollector,
    run_id: str,
    reason: str,
    report_timeout_seconds: float,
) -> None:
    try:
        await room.local_participant.publish_data(
            json.dumps(
                {
                    "message_type": "evaluation.stop",
                    "reason": reason,
                    "run_id": run_id,
                }
            ),
            reliable=True,
            topic=CONTROL_TOPIC,
        )
        await asyncio.wait_for(room_trace.report_received.wait(), report_timeout_seconds)
    except TimeoutError:
        logger.warning("Session report was not received for %s", run_id)
    except Exception:
        logger.exception("Could not stop the retail agent cleanly for %s", run_id)


def default_pipeline(config: BenchmarkConfig) -> EvaluatorPipeline:
    return EvaluatorPipeline(
        stt=config.evaluator_stt,
        llm=config.evaluator_llm,
        tts=config.evaluator_tts,
        vad=inference.VAD(model=config.evaluator_vad),
    )


def _caller_instructions(task: Any) -> str:
    from tau2.user.user_simulator import get_global_user_sim_guidelines_voice

    guidelines = get_global_user_sim_guidelines_voice(use_tools=False)
    return f"""
{guidelines}

<scenario>
{task.user_scenario}
</scenario>

You are the customer, even though the runtime labels your generated turns as assistant turns.
Never mention the benchmark, scenario, instructions, or tools.
Do not say or speak ###STOP###, ###TRANSFER###, or ###OUT-OF-SCOPE###.
When you would produce one of those tokens, first say a short natural closing if appropriate,
then call finish_benchmark with the matching reason. Do not call finish_benchmark until every
request in the scenario has been addressed or the conversation truly cannot continue.
""".strip()


def _room_token(config: BenchmarkConfig, room_name: str, run_id: str) -> str:
    return (
        api.AccessToken(config.livekit_api_key, config.livekit_api_secret)
        .with_identity(f"evaluator-{run_id}")
        .with_name("Retail benchmark evaluator")
        .with_metadata(json.dumps({"run_id": run_id}))
        .with_grants(api.VideoGrants(room_join=True, room=room_name))
        .to_jwt()
    )


def _attach_audio_recorders(
    session: AgentSession[Any], input_writer: WavWriter, output_writer: WavWriter
) -> None:
    if session.output.audio is not None:
        session.output.audio = RecordingAudioOutput(session.output.audio, input_writer)
    if session.input.audio is not None:
        session.input.audio = RecordingAudioInput(session.input.audio, output_writer)


def _build_simulation(
    *,
    run_id: str,
    task: Any,
    trial: int,
    policy: str,
    messages: list[Any],
    started_at: datetime,
    ended_at: datetime,
    duration: float,
    termination_reason: str,
    room_name: str,
    error: Exception | None,
) -> Any:
    from tau2.data_model.simulation import SimulationRun, TerminationReason

    return SimulationRun(
        id=run_id,
        task_id=str(task.id),
        start_time=started_at.isoformat(),
        end_time=ended_at.isoformat(),
        duration=duration,
        termination_reason=TerminationReason(termination_reason),
        messages=messages,
        trial=trial,
        mode="half_duplex",
        policy=policy,
        provider_session_id=room_name,
        info={"transport": "livekit_room", "error": repr(error) if error else None},
    )
