from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from tau2.data_model.message import AssistantMessage, ToolMessage, UserMessage

from retail_eval.trace import EvaluatorEventCollector, build_tau_messages


def _event(kind: str, payload: dict[str, object], offset: float) -> dict[str, object]:
    occurred_at = (datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=offset)).isoformat()
    return {
        "message_type": "structured_event",
        "event": {"kind": kind, "occurred_at": occurred_at, "payload": payload},
    }


def test_build_tau_messages_keeps_tool_call_and_result_adjacent() -> None:
    messages = build_tau_messages(
        [
            _event(
                "session.event",
                {
                    "event_name": "conversation_item_added",
                    "event": {
                        "item": {
                            "type": "message",
                            "role": "user",
                            "content": ["My order is W123"],
                            "created_at": 1.0,
                        }
                    },
                },
                1,
            ),
            _event(
                "tool.call.completed",
                {
                    "tool_call_id": "call-1",
                    "tool_name": "get_order_details",
                    "arguments": {"order_id": "W123"},
                    "result": {"status": "pending"},
                    "serialized_result": '{"status":"pending"}',
                },
                2,
            ),
            _event(
                "session.event",
                {
                    "event_name": "conversation_item_added",
                    "event": {
                        "item": {
                            "type": "message",
                            "role": "assistant",
                            "content": ["Your order is pending."],
                            "created_at": 3.0,
                        }
                    },
                },
                3,
            ),
        ]
    )

    assert isinstance(messages[0], UserMessage)
    assert isinstance(messages[1], AssistantMessage)
    assert messages[1].tool_calls is not None
    assert messages[1].tool_calls[0].name == "get_order_details"
    assert isinstance(messages[2], ToolMessage)
    assert messages[2].id == "call-1"
    assert messages[2].content == '{"status":"pending"}'
    assert isinstance(messages[3], AssistantMessage)


def test_build_tau_messages_preserves_tau_error_format() -> None:
    messages = build_tau_messages(
        [
            _event(
                "tool.call.failed",
                {
                    "tool_call_id": "call-2",
                    "tool_name": "cancel_pending_order",
                    "arguments": {"order_id": "W123", "reason": "ordered by mistake"},
                    "error_type": "ValueError",
                    "error_message": "Order not found",
                },
                1,
            )
        ]
    )

    assert isinstance(messages[1], ToolMessage)
    assert messages[1].content == "Error: Order not found"
    assert messages[1].error is True


def test_evaluator_event_collector_detects_customer_speech() -> None:
    class FakeSession:
        def __init__(self) -> None:
            self.handlers: dict[str, object] = {}

        def on(self, name: str, callback: object) -> None:
            self.handlers[name] = callback

    session = FakeSession()
    collector = EvaluatorEventCollector()
    collector.attach(session)

    callback = session.handlers["agent_state_changed"]
    assert callable(callback)
    callback(SimpleNamespace(old_state="listening", new_state="speaking"))

    assert collector.customer_speech_started.is_set()
