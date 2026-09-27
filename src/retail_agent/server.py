"""Thin LiveKit worker entry point for manual voice runs."""

from __future__ import annotations

import asyncio
import importlib
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

from dotenv import load_dotenv
from livekit import agents, rtc
from livekit.agents import AgentServer, AgentSession

from retail_agent.agent import create_retail_agent
from retail_agent.config import RetailAgentConfig, VoicePipelineConfig
from retail_agent.runtime import RuntimeBindings, create_livekit_session
from retail_agent.trace_transport import RoomEventPublisher, decode_control_message

if TYPE_CHECKING:
    from retail_agent.agent import RetailSupportAgent

load_dotenv(".env.local")

logger = logging.getLogger(__name__)
server = AgentServer()


@dataclass(slots=True)
class ActiveSession:
    agent: RetailSupportAgent
    session: AgentSession[Any]
    publisher: RoomEventPublisher | None
    stop_task: asyncio.Task[None] | None = None


_active_sessions: dict[str, ActiveSession] = {}


def _trace_events_enabled() -> bool:
    return os.getenv("RETAIL_TRACE_EVENTS", "1").lower() not in {"0", "false", "no"}


async def _on_session_end(ctx: agents.JobContext) -> None:
    active = _active_sessions.pop(ctx.room.name, None)
    if active is None:
        return
    await _finalize_session(ctx, active)


async def _finalize_session(ctx: agents.JobContext, active: ActiveSession) -> None:
    agent = active.agent
    session = active.session
    await session.aclose()
    await agent.event_emitter.drain()
    if active.publisher is not None:
        try:
            report = ctx.make_session_report(session).to_dict()
            await active.publisher.publish(
                {
                    "message_type": "session_report",
                    "session_id": agent.retail_state.session_id,
                    "report": report,
                }
            )
        except Exception:
            logger.exception("Could not publish the final session report for %s", ctx.room.name)
        finally:
            active.publisher.close()


async def _stop_evaluation_session(
    ctx: agents.JobContext,
    active: ActiveSession,
    reason: str,
) -> None:
    _active_sessions.pop(ctx.room.name, None)
    try:
        await _finalize_session(ctx, active)
    finally:
        ctx.shutdown(reason=f"evaluation completed: {reason}")


def load_runtime_bindings() -> RuntimeBindings:
    path = os.getenv(
        "RETAIL_BINDINGS_FACTORY",
        "retail_agent.integrations.tau:load_default_retail_bindings",
    )
    module_name, separator, attribute_name = path.partition(":")
    if not separator or not module_name or not attribute_name:
        raise ValueError("RETAIL_BINDINGS_FACTORY must use the form 'module.path:callable'")
    module = importlib.import_module(module_name)
    factory = cast(Callable[[], RuntimeBindings], getattr(module, attribute_name))
    bindings = factory()
    if not isinstance(bindings, RuntimeBindings):
        raise TypeError("Runtime bindings factory must return RuntimeBindings")
    return bindings


@server.rtc_session(
    agent_name=os.getenv("LIVEKIT_AGENT_NAME", "retail-support-agent"),
    on_session_end=_on_session_end,
)
async def retail_voice_agent(ctx: agents.JobContext) -> None:
    bindings = await asyncio.to_thread(load_runtime_bindings)
    behavior = RetailAgentConfig()
    publisher = RoomEventPublisher(ctx.room) if _trace_events_enabled() else None
    agent = create_retail_agent(
        policy=bindings.policy,
        tools=bindings.tools,
        config=behavior,
        event_sink=publisher,
        session_id=ctx.room.name,
    )
    session = create_livekit_session(
        agent=agent,
        config=VoicePipelineConfig.from_env(),
    )
    _active_sessions[ctx.room.name] = ActiveSession(
        agent=agent,
        session=session,
        publisher=publisher,
    )

    @ctx.room.on("data_received")
    def on_data_received(packet: rtc.DataPacket) -> None:
        message = decode_control_message(packet)
        if message is not None and message.get("message_type") == "evaluation.stop":
            active = _active_sessions.get(ctx.room.name)
            if active is None or active.stop_task is not None:
                return
            reason = str(message.get("reason", "complete"))
            active.stop_task = asyncio.create_task(
                _stop_evaluation_session(ctx, active, reason),
                name=f"stop-{ctx.room.name}",
            )

    try:
        await session.start(room=ctx.room, agent=agent)
        if publisher is not None:
            publisher.start()
        await session.generate_reply(instructions=behavior.greeting_instructions)
    except BaseException:
        _active_sessions.pop(ctx.room.name, None)
        if publisher is not None:
            publisher.close()
        await agent.event_emitter.drain()
        raise


def main() -> None:
    agents.cli.run_app(server)


if __name__ == "__main__":
    main()
