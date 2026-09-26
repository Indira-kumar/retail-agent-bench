from __future__ import annotations

from typing import Any

from retail_agent import VoicePipelineConfig, create_livekit_session, create_retail_agent
from retail_agent import runtime as runtime_module


class NoopTool:
    name = "noop"

    @property
    def openai_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": "Return a fixed value.",
                "parameters": {"type": "object", "properties": {}},
            },
        }

    def __call__(self, **kwargs: Any) -> str:
        del kwargs
        return "ok"


class CapturingSession:
    def __init__(self, **kwargs: Any) -> None:
        self.options = kwargs
        self.handlers: dict[str, Any] = {}

    def on(self, event_name: str, callback: Any) -> None:
        self.handlers[event_name] = callback


def test_session_uses_vad_only_turn_handling(monkeypatch: Any) -> None:
    monkeypatch.setattr(runtime_module, "AgentSession", CapturingSession)
    monkeypatch.setattr(runtime_module.inference, "VAD", lambda **kwargs: kwargs)
    agent = create_retail_agent(policy="Test policy", tools=[NoopTool()])

    session = create_livekit_session(agent=agent, config=VoicePipelineConfig())

    turn_handling = session.options["turn_handling"]
    assert turn_handling["turn_detection"] == "vad"
    assert turn_handling["interruption"]["mode"] == "vad"
    assert turn_handling["preemptive_generation"]["enabled"] is False
    assert session.options["max_tool_steps"] == 8
    assert session.options["vad"] == {"model": "silero"}
