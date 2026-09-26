"""The importable retail support agent."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, cast
from uuid import uuid4

from livekit.agents import Agent, llm

from retail_agent.config import RetailAgentConfig
from retail_agent.events import EventEmitter, EventKind, EventSink, EventSource
from retail_agent.prompt import compose_instructions
from retail_agent.tools.contracts import ToolSource
from retail_agent.tools.tau import TauToolAdapter, adapt_tau_tools


@dataclass(frozen=True, slots=True)
class RetailAgentState:
    """Stable run metadata; policy decisions remain prompt-driven for Module 1."""

    session_id: str
    policy_sha256: str
    tool_names: tuple[str, ...]


class RetailSupportAgent(Agent):
    """LiveKit agent containing retail instructions and adapted tau tools."""

    def __init__(
        self,
        *,
        domain_policy: str,
        tool_adapter: TauToolAdapter,
        emitter: EventEmitter,
        config: RetailAgentConfig,
    ) -> None:
        self.event_emitter = emitter
        self.tool_adapter = tool_adapter
        self.retail_state = RetailAgentState(
            session_id=emitter.session_id,
            policy_sha256=hashlib.sha256(domain_policy.encode()).hexdigest(),
            tool_names=tuple(tool_adapter.metadata),
        )
        super().__init__(
            instructions=compose_instructions(domain_policy, config),
            tools=cast(list[llm.Tool | llm.Toolset], tool_adapter.tools),
        )


def create_retail_agent(
    *,
    policy: str,
    tools: ToolSource,
    config: RetailAgentConfig | None = None,
    event_sink: EventSink | None = None,
    session_id: str | None = None,
    include_tools: list[str] | None = None,
) -> RetailSupportAgent:
    """Create Module 1 from runtime-injected policy and DB-bound tau tools."""

    agent_config = config or RetailAgentConfig()
    emitter = EventEmitter(session_id or str(uuid4()), event_sink)
    adapter = adapt_tau_tools(tools, emitter=emitter, include=include_tools)
    agent = RetailSupportAgent(
        domain_policy=policy,
        tool_adapter=adapter,
        emitter=emitter,
        config=agent_config,
    )
    emitter.emit(
        EventKind.AGENT_CREATED,
        EventSource.AGENT,
        policy_sha256=agent.retail_state.policy_sha256,
        tool_names=agent.retail_state.tool_names,
    )
    return agent


def agent_metadata(agent: RetailSupportAgent) -> dict[str, Any]:
    """Return evaluator-safe metadata without the policy text itself."""

    return {
        "session_id": agent.retail_state.session_id,
        "policy_sha256": agent.retail_state.policy_sha256,
        "tool_names": list(agent.retail_state.tool_names),
    }
