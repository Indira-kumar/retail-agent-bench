"""Local trajectory visualizer for completed benchmark experiments."""

from __future__ import annotations

import json
import mimetypes
import re
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

from retail_eval.results import ResultsStore


class VisualizerServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True

    results: ResultsStore
    experiment_id: str
    static_root: Path


class VisualizerRequestHandler(BaseHTTPRequestHandler):
    server: VisualizerServer

    def do_GET(self) -> None:
        self._handle_request(include_body=True)

    def do_HEAD(self) -> None:
        self._handle_request(include_body=False)

    def _handle_request(self, *, include_body: bool) -> None:
        request_path = unquote(urlsplit(self.path).path)
        if request_path == "/":
            self._serve_file(self.server.static_root / "index.html", include_body=include_body)
            return
        if request_path.startswith("/assets/"):
            self._serve_file(
                resolve_request_path(
                    self.server.static_root, request_path.removeprefix("/assets/")
                ),
                include_body=include_body,
            )
            return
        if request_path == "/api/overview":
            self._serve_json(
                {
                    "experiment": self.server.results.experiment(self.server.experiment_id),
                    "summaries": self.server.results.summaries(self.server.experiment_id),
                },
                include_body=include_body,
            )
            return
        match = re.fullmatch(r"/api/trial/([^/]+)/(\d+)", request_path)
        if match:
            try:
                trial = self.server.results.trial(
                    self.server.experiment_id, match[1], int(match[2])
                )
            except ValueError:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            self._serve_json(trial, include_body=include_body)
            return
        match = re.fullmatch(r"/audio/([^/]+)/(\d+)/(input|output)", request_path)
        if match:
            self._serve_audio(match[1], int(match[2]), match[3], include_body=include_body)
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def _serve_json(self, value: object, *, include_body: bool) -> None:
        body = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if include_body:
            self.wfile.write(body)

    def _serve_audio(
        self, task_id: str, trial_number: int, channel: str, *, include_body: bool
    ) -> None:
        record = self.server.results.audio_record(
            self.server.experiment_id, task_id, trial_number, channel
        )
        if record is None:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        size = record["byte_size"]
        start, end = parse_range(self.headers.get("Range"), size)
        partial = self.headers.get("Range") is not None
        self.send_response(HTTPStatus.PARTIAL_CONTENT if partial else HTTPStatus.OK)
        self.send_header("Content-Type", "audio/wav")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(max(0, end - start + 1)))
        if partial:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        if include_body and size:
            try:
                for chunk in self.server.results.audio.stream(record["uri"], start, end):
                    self.wfile.write(chunk)
            except (BrokenPipeError, ConnectionResetError):
                return

    def _serve_file(self, path: Path | None, *, include_body: bool) -> None:
        if path is None or not path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        size = path.stat().st_size
        start, end = parse_range(self.headers.get("Range"), size)
        status = HTTPStatus.PARTIAL_CONTENT if start != 0 or end != size - 1 else HTTPStatus.OK
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"

        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cache-Control", "no-store")
        content_length = max(0, end - start + 1)
        self.send_header("Content-Length", str(content_length))
        if status == HTTPStatus.PARTIAL_CONTENT and size:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()

        if not include_body:
            return

        with path.open("rb") as source:
            source.seek(start)
            remaining = content_length
            try:
                while remaining:
                    chunk = source.read(min(64 * 1024, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
            except (BrokenPipeError, ConnectionResetError):
                return

    def log_message(self, format: str, *args: object) -> None:
        return


def resolve_request_path(root: Path, relative_path: str) -> Path | None:
    candidate = (root / relative_path).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        return None
    return candidate


def parse_range(value: str | None, size: int) -> tuple[int, int]:
    if size == 0:
        return 0, -1
    if value is None:
        return 0, size - 1
    match = re.fullmatch(r"bytes=(\d*)-(\d*)", value.strip())
    if match is None:
        return 0, size - 1
    start_text, end_text = match.groups()
    if not start_text:
        length = min(int(end_text or 0), size)
        return size - length, size - 1
    start = min(int(start_text), size - 1)
    end = min(int(end_text), size - 1) if end_text else size - 1
    return (start, end) if start <= end else (0, size - 1)


def serve_visualizer(
    *,
    database: Path | str,
    experiment_id: str,
    host: str = "127.0.0.1",
    port: int = 8765,
    open_browser: bool = True,
) -> None:
    if (
        not str(database).startswith(("postgresql://", "postgres://"))
        and not Path(database).is_file()
    ):
        raise ValueError(f"Results database does not exist: {database}")
    results = ResultsStore(database)
    results.experiment(experiment_id)
    server = VisualizerServer((host, port), VisualizerRequestHandler)
    server.results = results
    server.experiment_id = experiment_id
    server.static_root = Path(__file__).with_name("visualizer")
    display_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    url = f"http://{display_host}:{server.server_port}"
    print(f"Trajectory visualizer: {url}")
    print(f"Experiment: {experiment_id} in {results.location}")
    if open_browser:
        threading.Timer(0.15, webbrowser.open, args=(url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
