"""Thin LiveKit worker entry point for manual voice runs."""

from __future__ import annotations

import importlib
import os
from collections.abc import Callable
from typing import cast

from dotenv import load_dotenv
from livekit import agents
from livekit.agents import AgentServer

from retail_agent.agent import create_retail_agent
from retail_agent.config import RetailAgentConfig, VoicePipelineConfig
from retail_agent.runtime import RuntimeBindings, create_livekit_session

load_dotenv(".env.local")

server = AgentServer()


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


@server.rtc_session()
async def retail_voice_agent(ctx: agents.JobContext) -> None:
    bindings = load_runtime_bindings()
    behavior = RetailAgentConfig()
    agent = create_retail_agent(
        policy=bindings.policy,
        tools=bindings.tools,
        config=behavior,
        session_id=ctx.room.name,
    )
    session = create_livekit_session(
        agent=agent,
        config=VoicePipelineConfig.from_env(),
    )
    await session.start(room=ctx.room, agent=agent)
    await session.generate_reply(instructions=behavior.greeting_instructions)


def main() -> None:
    agents.cli.run_app(server)


if __name__ == "__main__":
    main()
