from __future__ import annotations

import asyncio
from typing import Any

import pytest
from livekit.agents import ToolResult

from retail_agent.events import EventEmitter, StructuredEvent
from retail_agent.tools.serialization import serialize_tool_result
from retail_agent.tools.tau import TauToolAdapter


class FakeTauTool:
    name = "double"

    @property
    def openai_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": "Double an integer.",
                "parameters": {
                    "type": "object",
                    "properties": {"value": {"type": "integer"}},
                    "required": ["value"],
                },
            },
        }

    def __call__(self, **kwargs: Any) -> dict[str, int]:
        return {"answer": int(kwargs["value"]) * 2}


class FakeTransferTool:
    name = "transfer_to_human_agents"

    @property
    def openai_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": "Transfer the customer.",
                "parameters": {
                    "type": "object",
                    "properties": {"summary": {"type": "string"}},
                    "required": ["summary"],
                },
            },
        }

    def __call__(self, **kwargs: Any) -> str:
        del kwargs
        return "Transfer successful"


class FakeSpeech:
    async def wait_for_playout(self) -> None:
        return None


class FakeSession:
    def __init__(self) -> None:
        self.spoken: list[tuple[str, bool]] = []
        self.shutdown_called = asyncio.Event()

    async def wait_for_idle(self) -> None:
        return None

    def say(self, text: str, *, allow_interruptions: bool) -> FakeSpeech:
        self.spoken.append((text, allow_interruptions))
        return FakeSpeech()

    def shutdown(self, *, drain: bool) -> None:
        assert drain is False
        self.shutdown_called.set()


@pytest.mark.asyncio
async def test_tau_schema_and_execution_are_preserved() -> None:
    events: list[StructuredEvent] = []
    emitter = EventEmitter("test-session", events.append)
    adapter = TauToolAdapter([FakeTauTool()], emitter=emitter)

    tool = adapter.tools[0]
    assert tool.info.raw_schema["name"] == "double"
    assert tool.info.raw_schema["parameters"]["required"] == ["value"]

    result = await tool._func({"value": 4}, None)
    await emitter.drain()

    assert result == '{"answer":8}'
    assert [event.kind for event in events] == [
        "tool.call.started",
        "tool.call.completed",
    ]


def test_tool_results_have_stable_json() -> None:
    assert serialize_tool_result({"b": 2, "a": [1]}) == '{"a":[1],"b":2}'


@pytest.mark.asyncio
async def test_transfer_tool_closes_session_after_final_message() -> None:
    emitter = EventEmitter("test-session")
    adapter = TauToolAdapter([FakeTransferTool()], emitter=emitter)
    session = FakeSession()
    context = type(
        "Context",
        (),
        {
            "session": session,
            "function_call": type("FunctionCall", (), {"call_id": "call-1"})(),
        },
    )()

    result = await adapter.tools[0]._func({"summary": "Customer needs help"}, context)
    await asyncio.wait_for(session.shutdown_called.wait(), timeout=1)

    assert isinstance(result, ToolResult)
    assert result.output == "Transfer successful"
    assert result.reply_required is False
    assert session.spoken == [("I'm transferring you to a human agent now. Please hold.", False)]
