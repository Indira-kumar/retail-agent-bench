from __future__ import annotations

from types import SimpleNamespace
from typing import Any


class FakeSession:
    def __init__(self) -> None:
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


class FakeEmitter:
    def __init__(self) -> None:
        self.drained = False

    async def drain(self) -> None:
        self.drained = True


class FakePublisher:
    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []
        self.closed = False

    async def publish(self, message: dict[str, Any]) -> None:
        self.messages.append(message)

    def close(self) -> None:
        self.closed = True


class FakeReport:
    def to_dict(self) -> dict[str, str]:
        return {"report": "complete"}


class FakeContext:
    def __init__(self, room_name: str) -> None:
        self.room = SimpleNamespace(name=room_name)
        self.shutdown_reason: str | None = None

    def make_session_report(self, session: FakeSession) -> FakeReport:
        assert session.closed
        return FakeReport()

    def shutdown(self, *, reason: str) -> None:
        self.shutdown_reason = reason


async def test_evaluation_stop_publishes_report_before_job_shutdown() -> None:
    from retail_agent import server

    room_name = "evaluation-room"
    context = FakeContext(room_name)
    session = FakeSession()
    emitter = FakeEmitter()
    publisher = FakePublisher()
    active = server.ActiveSession(
        agent=SimpleNamespace(
            event_emitter=emitter,
            retail_state=SimpleNamespace(session_id="session-1"),
        ),
        session=session,
        publisher=publisher,
    )
    server._active_sessions[room_name] = active

    await server._stop_evaluation_session(context, active, "complete")

    assert room_name not in server._active_sessions
    assert session.closed
    assert emitter.drained
    assert publisher.messages == [
        {
            "message_type": "session_report",
            "session_id": "session-1",
            "report": {"report": "complete"},
        }
    ]
    assert publisher.closed
    assert context.shutdown_reason == "evaluation completed: complete"
