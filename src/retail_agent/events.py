"""Non-blocking structured events consumed by Module 2."""

from __future__ import annotations

import asyncio
import inspect
import logging
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol, cast
from uuid import uuid4

logger = logging.getLogger(__name__)


class EventSource(StrEnum):
    SESSION = "livekit_agent_session"
    AGENT = "retail_support_agent"
    TOOL_ADAPTER = "tau_tool_adapter"


class EventKind(StrEnum):
    AGENT_CREATED = "agent.created"
    SESSION_CREATED = "session.created"
    SESSION_EVENT = "session.event"
    TOOL_CALL_STARTED = "tool.call.started"
    TOOL_CALL_COMPLETED = "tool.call.completed"
    TOOL_CALL_FAILED = "tool.call.failed"


@dataclass(frozen=True, slots=True)
class StructuredEvent:
    """Serializable event emitted at a Module 1 boundary."""

    kind: str
    source: str
    session_id: str
    payload: Mapping[str, Any] = field(default_factory=dict)
    event_id: str = field(default_factory=lambda: str(uuid4()))
    occurred_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    monotonic_seconds: float = field(default_factory=time.monotonic)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "kind": self.kind,
            "source": self.source,
            "session_id": self.session_id,
            "occurred_at": self.occurred_at,
            "monotonic_seconds": self.monotonic_seconds,
            "payload": dict(self.payload),
        }


class AsyncEventSink(Protocol):
    def __call__(self, event: StructuredEvent) -> Awaitable[None]: ...


class SyncEventSink(Protocol):
    def __call__(self, event: StructuredEvent) -> None: ...


type EventSink = AsyncEventSink | SyncEventSink


class EventEmitter:
    """Schedules delivery without delaying the agent or tool call."""

    def __init__(self, session_id: str, sink: EventSink | None = None) -> None:
        self.session_id = session_id
        self._sink = sink
        self._pending: set[asyncio.Task[None]] = set()

    def emit(self, kind: EventKind | str, source: EventSource | str, **payload: Any) -> None:
        if self._sink is None:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.warning("Dropping event %s because no event loop is running", kind)
            return

        event = StructuredEvent(
            kind=str(kind),
            source=str(source),
            session_id=self.session_id,
            payload=_json_safe(payload),
        )
        task = loop.create_task(self._deliver(event), name=f"emit-{event.event_id}")
        self._pending.add(task)
        task.add_done_callback(self._pending.discard)

    async def _deliver(self, event: StructuredEvent) -> None:
        assert self._sink is not None
        try:
            if inspect.iscoroutinefunction(self._sink):
                await cast(AsyncEventSink, self._sink)(event)
                return

            sync_sink = cast(Callable[[StructuredEvent], Any], self._sink)
            result = sync_sink(event)
            if inspect.isawaitable(result):
                await cast(Awaitable[None], result)
        except Exception:
            logger.exception("Structured event sink failed for event %s", event.event_id)

    async def drain(self) -> None:
        if self._pending:
            await asyncio.gather(*tuple(self._pending), return_exceptions=True)


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list | tuple | set):
        return [_json_safe(item) for item in value]
    if hasattr(value, "model_dump"):
        return _json_safe(value.model_dump(mode="json"))
    if is_dataclass(value) and not isinstance(value, type):
        return _json_safe(asdict(value))
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def event_payload(event: Any) -> dict[str, Any]:
    if hasattr(event, "to_dict"):
        value = event.to_dict()
    elif hasattr(event, "model_dump"):
        value = event.model_dump(mode="json")
    elif is_dataclass(event) and not isinstance(event, type):
        value = asdict(event)
    elif hasattr(event, "__dict__"):
        value = vars(event)
    else:
        value = {"value": str(event)}
    safe_value = _json_safe(value)
    payload = safe_value if isinstance(safe_value, dict) else {"value": safe_value}
    hidden_error = getattr(getattr(event, "error", None), "error", None)
    if isinstance(hidden_error, BaseException):
        serialized_error = payload.get("error")
        if isinstance(serialized_error, dict):
            serialized_error["detail"] = _exception_payload(hidden_error)
    return payload


def _exception_payload(error: BaseException) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "type": type(error).__name__,
        "message": str(error),
    }
    for attribute in ("status_code", "request_id", "retryable"):
        value = getattr(error, attribute, None)
        if value is not None:
            payload[attribute] = _json_safe(value)
    cause = error.__cause__
    if cause is not None:
        payload["cause_type"] = type(cause).__name__
        payload["cause_message"] = str(cause)
    return payload
