"""Trace collection and conversion into tau trajectories."""

from __future__ import annotations

import asyncio
import json
import logging
import zlib
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from livekit import rtc

from retail_agent.events import event_payload
from retail_agent.trace_transport import TRACE_TOPIC, TraceChunkAssembler

logger = logging.getLogger(__name__)


class RoomTraceCollector:
    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []
        self.session_report: dict[str, Any] | None = None
        self._assembler = TraceChunkAssembler()
        self.report_received = asyncio.Event()

    def attach(self, room: rtc.Room) -> None:
        @room.on("data_received")
        def on_data_received(packet: rtc.DataPacket) -> None:
            if packet.topic != TRACE_TOPIC:
                return
            try:
                message = self._assembler.add(packet.data)
            except (KeyError, TypeError, ValueError, zlib.error):
                logger.exception("Ignoring malformed retail trace packet")
                return
            if message is None:
                return
            self.messages.append(message)
            if message.get("message_type") == "session_report":
                report = message.get("report")
                if isinstance(report, dict):
                    self.session_report = report
                    self.report_received.set()


class EvaluatorEventCollector:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def attach(self, session: Any) -> None:
        event_names = (
            "user_input_transcribed",
            "conversation_item_added",
            "agent_state_changed",
            "user_state_changed",
            "session_usage_updated",
            "error",
            "close",
        )
        for event_name in event_names:

            def on_event(event: Any, *, name: str = event_name) -> None:
                self.events.append({"event_name": name, "event": event_payload(event)})

            session.on(event_name, on_event)


def build_tau_messages(trace_messages: list[dict[str, Any]]) -> list[Any]:
    from tau2.data_model.message import AssistantMessage, ToolCall, ToolMessage, UserMessage

    timeline: list[tuple[float, list[Any]]] = []
    for message in trace_messages:
        if message.get("message_type") != "structured_event":
            continue
        event = message.get("event")
        if not isinstance(event, Mapping):
            continue
        timestamp = _event_timestamp(event)
        kind = event.get("kind")
        payload = event.get("payload")
        if not isinstance(payload, Mapping):
            continue

        if kind == "session.event" and payload.get("event_name") == "conversation_item_added":
            item = _conversation_item(payload)
            if item is None:
                continue
            role, content, item_timestamp = item
            tau_timestamp = _iso_timestamp(item_timestamp or timestamp)
            if role == "user":
                timeline.append(
                    (
                        timestamp,
                        [UserMessage(role="user", content=content, timestamp=tau_timestamp)],
                    )
                )
            elif role == "assistant":
                timeline.append(
                    (
                        timestamp,
                        [
                            AssistantMessage(
                                role="assistant", content=content, timestamp=tau_timestamp
                            )
                        ],
                    )
                )
            continue

        if kind not in {"tool.call.completed", "tool.call.failed"}:
            continue
        call_id = str(payload.get("tool_call_id", ""))
        tool_name = str(payload.get("tool_name", ""))
        arguments = payload.get("arguments")
        if not call_id or not tool_name or not isinstance(arguments, Mapping):
            continue
        tool_call = ToolCall(
            id=call_id,
            name=tool_name,
            arguments=dict(arguments),
            requestor="assistant",
        )
        if kind == "tool.call.completed":
            serialized_result = payload.get("serialized_result")
            result_text = (
                serialized_result
                if isinstance(serialized_result, str)
                else json.dumps(payload.get("result"), ensure_ascii=False, default=str)
            )
        else:
            result_text = f"Error: {payload.get('error_message', '')}"
        timestamp_text = _iso_timestamp(timestamp)
        timeline.append(
            (
                timestamp,
                [
                    AssistantMessage(
                        role="assistant",
                        content=None,
                        tool_calls=[tool_call],
                        timestamp=timestamp_text,
                    ),
                    ToolMessage(
                        id=call_id,
                        role="tool",
                        content=result_text,
                        requestor="assistant",
                        error=kind == "tool.call.failed",
                        timestamp=timestamp_text,
                    ),
                ],
            )
        )

    timeline.sort(key=lambda item: item[0])
    return [message for _, group in timeline for message in group]


def _event_timestamp(event: Mapping[str, Any]) -> float:
    occurred_at = event.get("occurred_at")
    if isinstance(occurred_at, str):
        try:
            return datetime.fromisoformat(occurred_at).timestamp()
        except ValueError:
            pass
    monotonic = event.get("monotonic_seconds")
    return float(monotonic) if isinstance(monotonic, int | float) else 0.0


def _conversation_item(payload: Mapping[str, Any]) -> tuple[str, str, float | None] | None:
    raw_event = payload.get("event")
    if not isinstance(raw_event, Mapping):
        return None
    item = raw_event.get("item")
    if not isinstance(item, Mapping) or item.get("type") != "message":
        return None
    role = item.get("role")
    if role not in {"user", "assistant"}:
        return None
    content = item.get("content")
    if isinstance(content, list):
        text = "\n".join(value for value in content if isinstance(value, str))
    elif isinstance(content, str):
        text = content
    else:
        return None
    if not text.strip():
        return None
    created_at = item.get("created_at")
    item_timestamp = float(created_at) if isinstance(created_at, int | float) else None
    return str(role), text, item_timestamp


def _iso_timestamp(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, UTC).isoformat()
