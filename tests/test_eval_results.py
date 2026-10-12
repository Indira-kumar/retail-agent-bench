from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from retail_eval import runner
from retail_eval.config import BenchmarkConfig
from retail_eval.livekit_runner import TrialResult
from retail_eval.migration import import_experiment
from retail_eval.results import AudioStore, ResultsStore, new_manifest


def test_results_store_preserves_trial_payloads_events_and_audio(tmp_path: Path) -> None:
    store = ResultsStore(tmp_path / "results.sqlite3")
    store.create_experiment(new_manifest("run-1", {"model": "test"}, ["5"], 1))
    store.create_trial(
        "run-1",
        "5",
        1,
        {
            "task": {"id": "5"},
            "policy": "# Policy",
            "relevant_policy": {"sections": []},
        },
    )
    audio = tmp_path / "input.wav"
    audio.write_bytes(b"RIFF12345678")
    events = [{"event": {"occurred_at": "2026-01-01T00:00:00Z", "kind": "tool.call.started"}}]
    summary = {"task_id": "5", "trial": 1, "reward": 1.0, "failure_labels": []}
    store.save_trial(
        "run-1",
        "5",
        1,
        summary=summary,
        documents={"simulation": {"messages": []}, "score": {"reward": 1}},
        events=events,
        audio_paths={"input": audio},
    )

    trial = store.trial("run-1", "5", 1)
    assert store.experiment("run-1")["config"] == {"model": "test"}
    assert store.summaries("run-1") == [summary]
    assert trial["documents"]["policy"] == "# Policy"
    assert trial["documents"]["simulation"] == {"messages": []}
    assert trial["events"] == events
    assert store.audio.read(trial["audio"]["input"]["uri"], 4, 7) == b"1234"
    assert trial["audio"]["input"]["byte_size"] == 12
    analysis_id = store.save_analysis("suite-v1", ["run-1"], {"passed": True})
    with sqlite3.connect(store.database) as connection:
        row = connection.execute(
            "SELECT suite_id, experiment_ids_json, report_json FROM analysis_runs WHERE id=?",
            (analysis_id,),
        ).fetchone()
    assert row == ("suite-v1", '["run-1"]', '{"passed": true}')


def test_s3_audio_store_uses_object_key_and_byte_range(tmp_path: Path, monkeypatch: Any) -> None:
    class Body:
        def iter_chunks(self, chunk_size: int) -> list[bytes]:
            assert chunk_size == 64 * 1024
            return [b"1234"]

        def close(self) -> None:
            return None

    class Client:
        def upload_file(self, path: str, bucket: str, key: str, ExtraArgs: object) -> None:
            assert Path(path).read_bytes() == b"RIFF12345678"
            assert (bucket, key, ExtraArgs) == (
                "test-bucket",
                "eval-audio/run-1/task_5/trial_1/input.wav",
                {"ContentType": "audio/wav"},
            )

        def get_object(self, *, Bucket: str, Key: str, Range: str) -> dict[str, Body]:
            assert (Bucket, Key, Range) == (
                "test-bucket",
                "eval-audio/run-1/task_5/trial_1/input.wav",
                "bytes=4-7",
            )
            return {"Body": Body()}

    store = AudioStore(tmp_path / "unused", bucket="test-bucket")
    monkeypatch.setattr(store, "_s3", Client)
    source = tmp_path / "input.wav"
    source.write_bytes(b"RIFF12345678")
    uri, size, checksum = store.put(source, "run-1/task_5/trial_1/input.wav")
    assert uri == "s3://test-bucket/eval-audio/run-1/task_5/trial_1/input.wav"
    assert size == 12
    assert checksum == hashlib.sha256(source.read_bytes()).hexdigest()
    assert store.read(uri, 4, 7) == b"1234"


def test_import_experiment_preserves_legacy_result(tmp_path: Path) -> None:
    root = tmp_path / "legacy"
    trial_root = root / "task_27" / "trial_1"
    trial_root.mkdir(parents=True)
    _write_json(root / "experiment.json", new_manifest("original", {"model": "old"}, ["27"], 1))
    _write_json(
        root / "summary.json",
        [
            {
                "task_id": "27",
                "trial": 1,
                "run_id": "abc",
                "reward": 0,
                "failure_labels": ["action_mismatch"],
                "artifact_path": "task_27/trial_1",
            }
        ],
    )
    _write_json(root / "failure_clusters.json", [{"labels": ["action_mismatch"], "count": 1}])
    _write_json(root / "behavior-report.json", {"passed": False})
    _write_json(trial_root / "task.json", {"id": "27"})
    _write_json(trial_root / "simulation.json", {"messages": [{"role": "tool"}]})
    _write_json(trial_root / "score.json", None)
    (trial_root / "policy.md").write_text("# Full policy", encoding="utf-8")
    (trial_root / "events.jsonl").write_text(
        json.dumps({"event": {"kind": "tool.call.completed"}}) + "\n", encoding="utf-8"
    )
    (trial_root / "output.wav").write_bytes(b"RIFF")
    store = ResultsStore(tmp_path / "results.sqlite3")

    assert import_experiment(store, root) == "legacy"
    trial = store.trial("legacy", "27", 1)
    assert trial["documents"]["score"] is None
    assert trial["documents"]["policy"] == "# Full policy"
    assert trial["events"][0]["event"]["kind"] == "tool.call.completed"
    assert trial["audio"]["output"]["byte_size"] == 4
    assert store.clusters("legacy")[0]["count"] == 1
    assert store.experiment("legacy")["source_experiment_id"] == "original"
    assert store.experiment_documents("legacy")["behavior-report"] == {"passed": False}
    assert store.summaries("legacy")[0]["artifact_path"] == "task_27/trial_1"
    with pytest.raises(sqlite3.IntegrityError):
        import_experiment(store, root)


async def test_benchmark_runner_persists_directly_to_database(
    tmp_path: Path, monkeypatch: Any
) -> None:
    class FakeSimulation:
        id = "run-5"
        reward_info = SimpleNamespace(reward=1.0, model_dump=lambda **_: {"reward": 1.0})
        termination_reason = SimpleNamespace(value="agent_stop")
        duration = 3.5
        provider_session_id = "room-5"

        def model_dump(self, **_: object) -> dict[str, object]:
            return {"id": self.id, "messages": []}

    class FakeTrialRunner:
        async def run(self, *, task: object, trial: int, paths: object, policy: str) -> TrialResult:
            del task, trial, policy
            paths.input_audio.write_bytes(b"RIFF")
            return TrialResult(FakeSimulation(), [{"event": {"kind": "stt"}}], [], {}, None)

    async def skip_score(*_: object, **__: object) -> None:
        return None

    monkeypatch.setattr(runner, "_score", skip_score)
    monkeypatch.setattr(runner, "_validate_scorer_credentials", lambda _: None)
    monkeypatch.setattr(runner, "classify_failure", lambda *_: [])
    monkeypatch.setattr(runner, "relevant_policy", lambda *_: {"sections": []})
    config = BenchmarkConfig(
        livekit_url="wss://example.test",
        livekit_api_key="key",
        livekit_api_secret="secret",
        output_dir=tmp_path,
    )
    task = SimpleNamespace(id="5", model_dump=lambda **_: {"id": "5"})

    store, experiment_id, summaries = await runner.BenchmarkRunner(
        config, trial_runner=FakeTrialRunner()
    ).run(tasks=[task], policy="# Policy", trials=1, experiment_id="test-run")

    assert experiment_id == "test-run"
    assert summaries[0]["reward"] == 1.0
    assert store.trial("test-run", "5", 1)["documents"]["simulation"]["id"] == "run-5"
    assert store.audio_record("test-run", "5", 1, "input")["byte_size"] == 4
    assert not await asyncio.to_thread(lambda: list(tmp_path.glob("test-run/**/*.json")))


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")
