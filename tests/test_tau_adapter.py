from __future__ import annotations

from typing import Any

import pytest

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
