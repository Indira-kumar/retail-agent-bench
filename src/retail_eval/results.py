"""Results database and pluggable audio object storage."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

SCHEMA_VERSION = 1
DOCUMENT_NAMES = (
    "task",
    "relevant_policy",
    "evaluator_events",
    "evaluator_history",
    "session_report",
    "simulation",
    "score",
    "failure",
    "runner_error",
)


def _encode(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _decode(value: str | None) -> Any:
    return json.loads(value) if value is not None else None


class AudioStore:
    def __init__(self, root: Path, bucket: str | None = None, prefix: str = "eval-audio") -> None:
        self.root = root.resolve()
        self.bucket = bucket
        self.prefix = prefix.strip("/")
        if bucket is None:
            self.root.mkdir(parents=True, exist_ok=True)

    def put(self, path: Path, key: str) -> tuple[str, int, str]:
        if not re.fullmatch(r"[A-Za-z0-9._/-]+", key) or ".." in Path(key).parts:
            raise ValueError(f"Invalid audio key: {key}")
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        size = path.stat().st_size
        if self.bucket is None:
            destination = self.root / key
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = destination.with_suffix(".tmp")
            with path.open("rb") as source, temporary.open("wb") as target:
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    target.write(chunk)
            temporary.replace(destination)
            return f"local://{key}", size, digest.hexdigest()
        object_key = f"{self.prefix}/{key}" if self.prefix else key
        self._s3().upload_file(
            str(path), self.bucket, object_key, ExtraArgs={"ContentType": "audio/wav"}
        )
        return f"s3://{self.bucket}/{object_key}", size, digest.hexdigest()

    def read(self, uri: str, start: int, end: int) -> bytes:
        return b"".join(self.stream(uri, start, end))

    def stream(self, uri: str, start: int, end: int) -> Iterator[bytes]:
        if uri.startswith("local://"):
            path = (self.root / uri.removeprefix("local://")).resolve()
            path.relative_to(self.root)
            with path.open("rb") as source:
                source.seek(start)
                remaining = end - start + 1
                while remaining:
                    chunk = source.read(min(64 * 1024, remaining))
                    if not chunk:
                        break
                    yield chunk
                    remaining -= len(chunk)
            return
        if uri.startswith("s3://"):
            bucket, _, key = uri.removeprefix("s3://").partition("/")
            response = self._s3().get_object(Bucket=bucket, Key=key, Range=f"bytes={start}-{end}")
            body = response["Body"]
            try:
                for chunk in body.iter_chunks(chunk_size=64 * 1024):
                    if chunk:
                        yield bytes(chunk)
            finally:
                body.close()
            return
        raise ValueError(f"Unsupported audio URI: {uri}")

    def _s3(self) -> Any:
        try:
            import boto3
        except ImportError as exc:
            raise RuntimeError("Install the 's3' extra to use S3 audio storage") from exc
        return boto3.client("s3", endpoint_url=os.getenv("EVAL_AUDIO_S3_ENDPOINT_URL"))


class _PostgresConnection:
    def __init__(self, connection: Any) -> None:
        self._connection = connection

    def execute(self, query: str, values: Any = ()) -> Any:
        return self._connection.execute(query.replace("?", "%s"), values)

    def executemany(self, query: str, values: Any) -> None:
        with self._connection.cursor() as cursor:
            cursor.executemany(query.replace("?", "%s"), values)

    def commit(self) -> None:
        self._connection.commit()

    def rollback(self) -> None:
        self._connection.rollback()

    def close(self) -> None:
        self._connection.close()


class ResultsStore:
    def __init__(self, database: Path | str, audio: AudioStore | None = None) -> None:
        self._postgres = str(database).startswith(("postgresql://", "postgres://"))
        self.database: Path | str = (
            str(database) if self._postgres else Path(database).expanduser().resolve()
        )
        if isinstance(self.database, Path):
            self.database.parent.mkdir(parents=True, exist_ok=True)
        audio_root = (
            self.database.parent / "audio"
            if isinstance(self.database, Path)
            else Path(os.getenv("EVAL_OUTPUT_DIR", "eval-runs")) / "audio"
        )
        self.audio = audio or AudioStore(
            audio_root,
            bucket=os.getenv("EVAL_AUDIO_S3_BUCKET") or None,
            prefix=os.getenv("EVAL_AUDIO_S3_PREFIX", "eval-audio"),
        )
        self._initialize()

    @property
    def location(self) -> str:
        return "PostgreSQL" if self._postgres else str(self.database)

    @contextmanager
    def _connection(self) -> Iterator[Any]:
        if self._postgres:
            try:
                import psycopg
                from psycopg.rows import dict_row
            except ImportError as exc:
                raise RuntimeError("Install the 'postgres' extra to use PostgreSQL") from exc
            connection: Any = _PostgresConnection(
                psycopg.connect(str(self.database), row_factory=dict_row)
            )
        else:
            connection = sqlite3.connect(self.database, timeout=30)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA busy_timeout = 30000")
        try:
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connection() as db:
            if not self._postgres:
                db.execute("PRAGMA journal_mode = WAL")
            schema = """
                CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS experiments (
                    id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    config_json TEXT NOT NULL,
                    task_ids_json TEXT NOT NULL,
                    planned_trials INTEGER NOT NULL CHECK (planned_trials > 0),
                    failure_clusters_json TEXT,
                    manifest_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS experiment_documents (
                    experiment_id TEXT NOT NULL REFERENCES experiments(id) ON DELETE CASCADE,
                    name TEXT NOT NULL,
                    body_json TEXT NOT NULL,
                    PRIMARY KEY(experiment_id, name)
                );
                CREATE TABLE IF NOT EXISTS trials (
                    id INTEGER PRIMARY KEY,
                    experiment_id TEXT NOT NULL REFERENCES experiments(id),
                    task_id TEXT NOT NULL,
                    trial_number INTEGER NOT NULL CHECK (trial_number > 0),
                    run_id TEXT,
                    reward REAL,
                    termination_reason TEXT,
                    duration_seconds REAL,
                    livekit_room TEXT,
                    failure_labels_json TEXT NOT NULL DEFAULT '[]',
                    summary_json TEXT,
                    UNIQUE(experiment_id, task_id, trial_number)
                );
                CREATE INDEX IF NOT EXISTS trials_task ON trials(task_id);
                CREATE TABLE IF NOT EXISTS trial_documents (
                    trial_id INTEGER NOT NULL REFERENCES trials(id) ON DELETE CASCADE,
                    name TEXT NOT NULL,
                    body_json TEXT NOT NULL,
                    PRIMARY KEY(trial_id, name)
                );
                CREATE TABLE IF NOT EXISTS trace_events (
                    trial_id INTEGER NOT NULL REFERENCES trials(id) ON DELETE CASCADE,
                    sequence INTEGER NOT NULL,
                    occurred_at TEXT,
                    kind TEXT,
                    body_json TEXT NOT NULL,
                    PRIMARY KEY(trial_id, sequence)
                );
                CREATE INDEX IF NOT EXISTS trace_events_kind ON trace_events(kind);
                CREATE TABLE IF NOT EXISTS trial_audio (
                    trial_id INTEGER NOT NULL REFERENCES trials(id) ON DELETE CASCADE,
                    channel TEXT NOT NULL CHECK (channel IN ('input', 'output')),
                    uri TEXT NOT NULL,
                    content_type TEXT NOT NULL,
                    byte_size INTEGER NOT NULL,
                    sha256 TEXT NOT NULL,
                    PRIMARY KEY(trial_id, channel)
                );
                CREATE TABLE IF NOT EXISTS analysis_runs (
                    id INTEGER PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    suite_id TEXT NOT NULL,
                    experiment_ids_json TEXT NOT NULL,
                    report_json TEXT NOT NULL
                );
            """
            if self._postgres:
                schema = schema.replace(
                    "id INTEGER PRIMARY KEY,",
                    "id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,",
                ).replace("trial_id INTEGER NOT NULL", "trial_id BIGINT NOT NULL")
                for statement in schema.split(";"):
                    if statement.strip():
                        db.execute(statement)
            else:
                db.executescript(schema)
            row = db.execute("SELECT version FROM schema_version").fetchone()
            if row is None:
                db.execute("INSERT INTO schema_version VALUES (?)", (SCHEMA_VERSION,))
            elif row["version"] != SCHEMA_VERSION:
                raise RuntimeError(f"Unsupported results schema version: {row['version']}")

    def create_experiment(
        self, manifest: dict[str, Any], *, experiment_id: str | None = None
    ) -> None:
        identifier = experiment_id or str(manifest["experiment_id"])
        with self._connection() as db:
            db.execute(
                "INSERT INTO experiments VALUES (?, ?, ?, ?, ?, NULL, ?)",
                (
                    identifier,
                    manifest["created_at"],
                    _encode(manifest["config"]),
                    _encode(manifest["task_ids"]),
                    manifest["trials"],
                    _encode(manifest),
                ),
            )
            db.execute(
                "INSERT INTO experiment_documents VALUES (?, 'experiment', ?)",
                (identifier, _encode(manifest)),
            )

    def delete_experiment(self, experiment_id: str) -> None:
        with self._connection() as db:
            db.execute("DELETE FROM trials WHERE experiment_id=?", (experiment_id,))
            db.execute("DELETE FROM experiments WHERE id=?", (experiment_id,))

    def save_experiment_document(self, experiment_id: str, name: str, value: Any) -> None:
        with self._connection() as db:
            db.execute(
                """INSERT INTO experiment_documents VALUES (?, ?, ?)
                   ON CONFLICT(experiment_id, name) DO UPDATE SET body_json=excluded.body_json""",
                (experiment_id, name, _encode(value)),
            )

    def experiment_documents(self, experiment_id: str) -> dict[str, Any]:
        with self._connection() as db:
            rows = db.execute(
                "SELECT name, body_json FROM experiment_documents WHERE experiment_id=?",
                (experiment_id,),
            ).fetchall()
        return {row["name"]: _decode(row["body_json"]) for row in rows}

    def create_trial(
        self, experiment_id: str, task_id: str, trial: int, documents: dict[str, Any]
    ) -> None:
        with self._connection() as db:
            row = db.execute(
                """INSERT INTO trials (experiment_id, task_id, trial_number)
                   VALUES (?, ?, ?) RETURNING id""",
                (experiment_id, task_id, trial),
            ).fetchone()
            if row is None:
                raise RuntimeError("Failed to create trial")
            self._write_documents(db, row["id"], documents)

    def save_trial(
        self,
        experiment_id: str,
        task_id: str,
        trial: int,
        *,
        summary: dict[str, Any] | None,
        documents: dict[str, Any],
        events: list[dict[str, Any]],
        audio_paths: dict[str, Path],
    ) -> None:
        audio_records = {}
        for channel, path in audio_paths.items():
            if path.is_file():
                key = f"{experiment_id}/task_{task_id}/trial_{trial}/{channel}.wav"
                audio_records[channel] = self.audio.put(path, key)
        with self._connection() as db:
            row = db.execute(
                """SELECT id FROM trials WHERE experiment_id = ? AND task_id = ?
                   AND trial_number = ?""",
                (experiment_id, task_id, trial),
            ).fetchone()
            if row is None:
                raise ValueError(f"Unknown trial: {experiment_id}/{task_id}/{trial}")
            trial_id = row["id"]
            db.execute(
                """UPDATE trials SET run_id=?, reward=?, termination_reason=?, duration_seconds=?,
                   livekit_room=?, failure_labels_json=?, summary_json=? WHERE id=?""",
                (
                    summary.get("run_id") if summary else None,
                    summary.get("reward") if summary else None,
                    summary.get("termination_reason") if summary else None,
                    summary.get("duration_seconds") if summary else None,
                    summary.get("livekit_room") if summary else None,
                    _encode(summary.get("failure_labels", []) if summary else []),
                    _encode(summary) if summary else None,
                    trial_id,
                ),
            )
            self._write_documents(db, trial_id, documents)
            db.execute("DELETE FROM trace_events WHERE trial_id = ?", (trial_id,))
            db.executemany(
                "INSERT INTO trace_events VALUES (?, ?, ?, ?, ?)",
                (
                    (
                        trial_id,
                        index,
                        (record.get("event") or {}).get("occurred_at"),
                        (record.get("event") or {}).get("kind"),
                        _encode(record),
                    )
                    for index, record in enumerate(events)
                ),
            )
            db.executemany(
                """INSERT INTO trial_audio VALUES (?, ?, ?, 'audio/wav', ?, ?)
                   ON CONFLICT(trial_id, channel) DO UPDATE SET uri=excluded.uri,
                   byte_size=excluded.byte_size, sha256=excluded.sha256""",
                ((trial_id, channel, *record) for channel, record in audio_records.items()),
            )

    def _write_documents(self, db: Any, trial_id: int, documents: dict[str, Any]) -> None:
        unknown = set(documents) - set(DOCUMENT_NAMES) - {"policy"}
        if unknown:
            raise ValueError(f"Unknown trial documents: {sorted(unknown)}")
        db.executemany(
            """INSERT INTO trial_documents VALUES (?, ?, ?)
               ON CONFLICT(trial_id, name) DO UPDATE SET body_json=excluded.body_json""",
            ((trial_id, name, _encode(value)) for name, value in documents.items()),
        )

    def finish_experiment(self, experiment_id: str, clusters: list[dict[str, Any]]) -> None:
        with self._connection() as db:
            db.execute(
                "UPDATE experiments SET failure_clusters_json=? WHERE id=?",
                (_encode(clusters), experiment_id),
            )
            db.execute(
                """INSERT INTO experiment_documents VALUES (?, 'failure_clusters', ?)
                   ON CONFLICT(experiment_id, name) DO UPDATE SET body_json=excluded.body_json""",
                (experiment_id, _encode(clusters)),
            )

    def experiment(self, experiment_id: str) -> dict[str, Any]:
        with self._connection() as db:
            row = db.execute("SELECT * FROM experiments WHERE id=?", (experiment_id,)).fetchone()
        if row is None:
            raise ValueError(f"Unknown experiment: {experiment_id}")
        manifest = cast(dict[str, Any], _decode(row["manifest_json"]))
        if manifest["experiment_id"] != row["id"]:
            manifest["source_experiment_id"] = manifest["experiment_id"]
            manifest["experiment_id"] = row["id"]
        return manifest

    def summaries(self, experiment_id: str) -> list[dict[str, Any]]:
        with self._connection() as db:
            rows = db.execute(
                """SELECT summary_json FROM trials WHERE experiment_id=?
                   AND summary_json IS NOT NULL
                   ORDER BY task_id, trial_number""",
                (experiment_id,),
            ).fetchall()
        return [_decode(row["summary_json"]) for row in rows]

    def trial(self, experiment_id: str, task_id: str, trial: int) -> dict[str, Any]:
        with self._connection() as db:
            row = db.execute(
                """SELECT id, summary_json FROM trials WHERE experiment_id=? AND task_id=?
                   AND trial_number=?""",
                (experiment_id, task_id, trial),
            ).fetchone()
            if row is None:
                raise ValueError(f"Unknown trial: {experiment_id}/{task_id}/{trial}")
            documents = db.execute(
                "SELECT name, body_json FROM trial_documents WHERE trial_id=?",
                (row["id"],),
            ).fetchall()
            events = db.execute(
                "SELECT body_json FROM trace_events WHERE trial_id=? ORDER BY sequence",
                (row["id"],),
            ).fetchall()
            audio = db.execute(
                "SELECT channel, uri, byte_size FROM trial_audio WHERE trial_id=?",
                (row["id"],),
            ).fetchall()
        return {
            "summary": _decode(row["summary_json"]),
            "documents": {item["name"]: _decode(item["body_json"]) for item in documents},
            "events": [_decode(item["body_json"]) for item in events],
            "audio": {
                item["channel"]: {"uri": item["uri"], "byte_size": item["byte_size"]}
                for item in audio
            },
        }

    def audio_record(
        self, experiment_id: str, task_id: str, trial: int, channel: str
    ) -> dict[str, Any] | None:
        with self._connection() as db:
            row = db.execute(
                """SELECT a.uri, a.byte_size FROM trial_audio a
                   JOIN trials t ON t.id=a.trial_id
                   WHERE t.experiment_id=? AND t.task_id=? AND t.trial_number=?
                   AND a.channel=?""",
                (experiment_id, task_id, trial, channel),
            ).fetchone()
        return {"uri": row["uri"], "byte_size": row["byte_size"]} if row else None

    def behavior_trials(self, experiment_ids: list[str]) -> list[dict[str, Any]]:
        if not experiment_ids:
            return []
        placeholders = ",".join("?" for _ in experiment_ids)
        with self._connection() as db:
            rows = db.execute(
                f"""SELECT t.experiment_id, t.task_id, t.trial_number,
                   task.body_json AS task_json, simulation.body_json AS simulation_json
                   FROM trials t
                   JOIN trial_documents task ON task.trial_id=t.id AND task.name='task'
                   JOIN trial_documents simulation ON simulation.trial_id=t.id
                       AND simulation.name='simulation'
                   WHERE t.experiment_id IN ({placeholders})
                   ORDER BY t.experiment_id, t.task_id, t.trial_number""",
                experiment_ids,
            ).fetchall()
        return [
            {
                "experiment_id": row["experiment_id"],
                "task_id": row["task_id"],
                "trial": row["trial_number"],
                "task": _decode(row["task_json"]),
                "simulation": _decode(row["simulation_json"]),
            }
            for row in rows
        ]

    def clusters(self, experiment_id: str) -> list[dict[str, Any]]:
        with self._connection() as db:
            row = db.execute(
                "SELECT failure_clusters_json FROM experiments WHERE id=?", (experiment_id,)
            ).fetchone()
        if row is None:
            raise ValueError(f"Unknown experiment: {experiment_id}")
        return _decode(row["failure_clusters_json"]) or []

    def save_analysis(
        self, suite_id: str, experiment_ids: list[str], report: dict[str, Any]
    ) -> int:
        with self._connection() as db:
            row = db.execute(
                """INSERT INTO analysis_runs
                   (created_at, suite_id, experiment_ids_json, report_json)
                   VALUES (?, ?, ?, ?) RETURNING id""",
                (datetime.now(UTC).isoformat(), suite_id, _encode(experiment_ids), _encode(report)),
            ).fetchone()
            if row is None:
                raise RuntimeError("Failed to save analysis")
            return int(row["id"])


def default_results_store(output_dir: Path) -> ResultsStore:
    bucket = os.getenv("EVAL_AUDIO_S3_BUCKET") or None
    return ResultsStore(
        os.getenv("EVAL_DATABASE_URL") or output_dir / "results.sqlite3",
        AudioStore(
            output_dir / "audio",
            bucket=bucket,
            prefix=os.getenv("EVAL_AUDIO_S3_PREFIX", "eval-audio"),
        ),
    )


def new_manifest(
    experiment_id: str, config: dict[str, Any], task_ids: list[str], trials: int
) -> dict[str, Any]:
    return {
        "experiment_id": experiment_id,
        "created_at": datetime.now(UTC).isoformat(),
        "config": config,
        "task_ids": task_ids,
        "trials": trials,
    }
