from __future__ import annotations

import json

import pytest

from retail_agent.trace_transport import TraceChunkAssembler, encode_trace_message


def test_trace_chunks_round_trip_out_of_order() -> None:
    message = {"message_type": "session_report", "report": {"history": "x" * 50_000}}
    packets = encode_trace_message(message, message_id="report", chunk_bytes=100)
    assembler = TraceChunkAssembler()

    decoded = None
    for packet in reversed(packets):
        value = assembler.add(packet)
        if value is not None:
            decoded = value

    assert decoded == message


def test_trace_chunks_reject_changed_total() -> None:
    packets = encode_trace_message({"value": "x" * 1_000}, message_id="message", chunk_bytes=20)
    envelope = json.loads(packets[1])
    envelope["total"] += 1

    assembler = TraceChunkAssembler()
    assert assembler.add(packets[0]) is None
    with pytest.raises(ValueError, match="count changed"):
        assembler.add(json.dumps(envelope).encode())
