"""Reliable in-room transport for optional evaluation trace events."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import zlib
from collections.abc import Mapping
from typing import Any
from uuid import uuid4

from livekit import rtc

from retail_agent.events import StructuredEvent

TRACE_TOPIC = "retail-agent.trace.v1"
CONTROL_TOPIC = "retail-agent.control.v1"
TRACE_PROTOCOL_VERSION = 1
TRACE_CHUNK_BYTES = 8_000

logger = logging.getLogger(__name__)


def encode_trace_message(
    message: Mapping[str, Any],
    *,
    message_id: str | None = None,
    chunk_bytes: int = TRACE_CHUNK_BYTES,
) -> list[bytes]:
    if chunk_bytes < 1:
        raise ValueError("chunk_bytes must be positive")

    raw = json.dumps(message, separators=(",", ":"), ensure_ascii=False).encode()
    compressed = zlib.compress(raw)
    chunks = [
        compressed[index : index + chunk_bytes] for index in range(0, len(compressed), chunk_bytes)
    ]
    trace_message_id = message_id or str(uuid4())
    return [
        json.dumps(
            {
                "version": TRACE_PROTOCOL_VERSION,
                "message_id": trace_message_id,
                "index": index,
                "total": len(chunks),
                "data": base64.b64encode(chunk).decode(),
            },
            separators=(",", ":"),
        ).encode()
        for index, chunk in enumerate(chunks)
    ]


class TraceChunkAssembler:
    def __init__(self) -> None:
        self._chunks: dict[str, dict[int, bytes]] = {}
        self._totals: dict[str, int] = {}

    def add(self, packet: bytes) -> dict[str, Any] | None:
        envelope = json.loads(packet)
        if envelope.get("version") != TRACE_PROTOCOL_VERSION:
            raise ValueError("Unsupported trace protocol version")

        message_id = str(envelope["message_id"])
        index = int(envelope["index"])
        total = int(envelope["total"])
        if total < 1 or index < 0 or index >= total:
            raise ValueError("Invalid trace chunk position")

        expected_total = self._totals.setdefault(message_id, total)
        if expected_total != total:
            raise ValueError("Trace chunk count changed during assembly")

        chunks = self._chunks.setdefault(message_id, {})
        chunks[index] = base64.b64decode(envelope["data"], validate=True)
        if len(chunks) != total:
            return None

        compressed = b"".join(chunks[part] for part in range(total))
        del self._chunks[message_id]
        del self._totals[message_id]
        decoded = json.loads(zlib.decompress(compressed))
        if not isinstance(decoded, dict):
            raise ValueError("Trace message must decode to an object")
        return decoded


class RoomEventPublisher:
    def __init__(self, room: rtc.Room) -> None:
        self._room = room
        self._ready = asyncio.Event()
        self._closed = False
        self._publish_lock = asyncio.Lock()

    def start(self) -> None:
        self._ready.set()

    def close(self) -> None:
        self._closed = True
        self._ready.set()

    async def __call__(self, event: StructuredEvent) -> None:
        await self.publish(
            {"message_type": "structured_event", "event": event.to_dict()},
            message_id=event.event_id,
        )

    async def publish(
        self,
        message: Mapping[str, Any],
        *,
        message_id: str | None = None,
    ) -> None:
        await self._ready.wait()
        if self._closed:
            return

        async with self._publish_lock:
            if self._closed or not self._room.isconnected():
                return
            try:
                for chunk in encode_trace_message(message, message_id=message_id):
                    await self._room.local_participant.publish_data(
                        chunk,
                        reliable=True,
                        topic=TRACE_TOPIC,
                    )
            except Exception:
                if self._closed or not self._room.isconnected():
                    return
                logger.exception("Failed to publish evaluation trace message")


def decode_control_message(packet: rtc.DataPacket) -> dict[str, Any] | None:
    if packet.topic != CONTROL_TOPIC:
        return None
    try:
        value = json.loads(packet.data)
    except (json.JSONDecodeError, UnicodeDecodeError):
        logger.warning("Ignoring malformed evaluation control packet")
        return None
    return value if isinstance(value, dict) else None
