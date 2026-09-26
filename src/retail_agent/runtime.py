"""LiveKit AgentSession composition and runtime binding contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from livekit.agents import AgentSession, TurnHandlingOptions, inference
from livekit.agents.voice.events import EventTypes

from retail_agent.agent import RetailSupportAgent
from retail_agent.config import VoicePipelineConfig
from retail_agent.events import EventKind, EventSource, event_payload
from retail_agent.tools.contracts import ToolSource


@dataclass(frozen=True, slots=True)
class RuntimeBindings:
    """Tau-owned objects injected into Module 1 for one isolated run."""

    policy: str
    tools: ToolSource
    db: Any | None = None
    owner: Any | None = None


def create_livekit_session(
    *,
    agent: RetailSupportAgent,
    config: VoicePipelineConfig | None = None,
) -> AgentSession[Any]:
    pipeline = config or VoicePipelineConfig()
    session: AgentSession[Any] = AgentSession(
        stt=pipeline.stt,
        llm=pipeline.llm,
        tts=pipeline.tts,
        vad=inference.VAD(model=pipeline.vad_model),
        turn_handling=TurnHandlingOptions(
            turn_detection="vad",
            endpointing={
                "mode": "fixed",
                "min_delay": pipeline.min_endpointing_delay,
                "max_delay": pipeline.max_endpointing_delay,
            },
            interruption={"mode": "vad"},
            preemptive_generation={"enabled": pipeline.preemptive_generation},
        ),
        max_tool_steps=pipeline.max_tool_steps,
    )
    _attach_session_events(session, agent)
    agent.event_emitter.emit(
        EventKind.SESSION_CREATED,
        EventSource.SESSION,
        stt=str(pipeline.stt),
        llm=str(pipeline.llm),
        tts=str(pipeline.tts),
        vad=str(pipeline.vad_model),
        turn_detection="vad",
        max_tool_steps=pipeline.max_tool_steps,
        preemptive_generation=pipeline.preemptive_generation,
    )
    return session


def _attach_session_events(session: AgentSession[Any], agent: RetailSupportAgent) -> None:
    event_names: tuple[EventTypes, ...] = (
        "user_input_transcribed",
        "user_transcription_timeout",
        "conversation_item_added",
        "speech_created",
        "function_tools_executed",
        "tool_execution_updated",
        "agent_state_changed",
        "user_state_changed",
        "session_usage_updated",
        "error",
        "close",
    )

    for event_name in event_names:

        def on_event(event: Any, *, name: str = event_name) -> None:
            agent.event_emitter.emit(
                EventKind.SESSION_EVENT,
                EventSource.SESSION,
                event_name=name,
                event=event_payload(event),
            )

        session.on(event_name, on_event)
