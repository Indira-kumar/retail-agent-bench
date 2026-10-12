from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest

from retail_eval.results import ResultsStore, new_manifest
from retail_eval.visualizer import (
    VisualizerRequestHandler,
    parse_range,
    resolve_request_path,
)


def test_visualizer_reads_trial_and_audio_from_database(tmp_path: Path) -> None:
    store = ResultsStore(tmp_path / "results.sqlite3")
    store.create_experiment(new_manifest("test", {}, ["5"], 1))
    store.create_trial("test", "5", 1, {"task": {"id": "5"}})
    audio = tmp_path / "input.wav"
    audio.write_bytes(b"RIFF12345678")
    store.save_trial(
        "test",
        "5",
        1,
        summary={"task_id": "5", "trial": 1},
        documents={"simulation": {"messages": []}},
        events=[],
        audio_paths={"input": audio},
    )
    overview = json.loads(_response(store, "/api/overview"))
    trial = json.loads(_response(store, "/api/trial/5/1"))
    audio_body = _response(store, "/audio/5/1/input", range_header="bytes=4-7")
    assert overview["experiment"]["experiment_id"] == "test"
    assert trial["documents"]["simulation"] == {"messages": []}
    assert audio_body == b"1234"


def _response(store: ResultsStore, path: str, range_header: str | None = None) -> bytes:
    handler = object.__new__(VisualizerRequestHandler)
    handler.server = SimpleNamespace(results=store, experiment_id="test")  # type: ignore[assignment]
    handler.path = path
    handler.command = "GET"
    handler.requestline = f"GET {path} HTTP/1.1"
    handler.request_version = "HTTP/1.1"
    handler.headers = {"Range": range_header} if range_header else {}
    handler.wfile = BytesIO()
    handler._handle_request(include_body=True)
    return handler.wfile.getvalue().split(b"\r\n\r\n", 1)[1]


def test_resolve_request_path_rejects_parent_traversal(tmp_path: Path) -> None:
    assert resolve_request_path(tmp_path, "../private.json") is None
    assert (
        resolve_request_path(tmp_path, "task_5/trial_1/task.json")
        == (tmp_path / "task_5/trial_1/task.json").resolve()
    )


@pytest.mark.parametrize(
    ("header", "size", "expected"),
    [
        (None, 100, (0, 99)),
        ("bytes=10-19", 100, (10, 19)),
        ("bytes=90-", 100, (90, 99)),
        ("bytes=-10", 100, (90, 99)),
        ("invalid", 100, (0, 99)),
        (None, 0, (0, -1)),
    ],
)
def test_parse_range(header: str | None, size: int, expected: tuple[int, int]) -> None:
    assert parse_range(header, size) == expected
