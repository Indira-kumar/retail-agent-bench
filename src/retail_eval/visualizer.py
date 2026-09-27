"""Local trajectory visualizer for completed benchmark experiments."""

from __future__ import annotations

import mimetypes
import re
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit


class VisualizerServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True

    results_root: Path
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
        if request_path.startswith("/data/"):
            self._serve_file(
                resolve_request_path(self.server.results_root, request_path.removeprefix("/data/")),
                include_body=include_body,
            )
            return
        self.send_error(HTTPStatus.NOT_FOUND)

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


def validate_results_dir(results_dir: Path) -> Path:
    root = results_dir.expanduser().resolve()
    required_files = (root / "experiment.json", root / "summary.json")
    missing = [path.name for path in required_files if not path.is_file()]
    if missing:
        names = ", ".join(missing)
        raise ValueError(f"Not a benchmark experiment directory; missing {names}: {root}")
    return root


def serve_visualizer(
    *,
    results_dir: Path,
    host: str = "127.0.0.1",
    port: int = 8765,
    open_browser: bool = True,
) -> None:
    root = validate_results_dir(results_dir)
    server = VisualizerServer((host, port), VisualizerRequestHandler)
    server.results_root = root
    server.static_root = Path(__file__).with_name("visualizer")
    display_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    url = f"http://{display_host}:{server.server_port}"
    print(f"Trajectory visualizer: {url}")
    print(f"Experiment: {root}")
    if open_browser:
        threading.Timer(0.15, webbrowser.open, args=(url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
