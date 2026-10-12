"""Import legacy experiment folders into the results database."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from retail_eval.results import DOCUMENT_NAMES, ResultsStore


def import_experiment(store: ResultsStore, root: Path) -> str:
    root = root.expanduser().resolve()
    manifest = _read_json(root / "experiment.json")
    summary_path = root / "summary.json"
    summaries = _read_json(summary_path) if summary_path.is_file() else []
    if not isinstance(manifest, dict) or not isinstance(summaries, list):
        raise ValueError(f"Invalid experiment manifest or summary: {root}")
    experiment_id = root.name
    store.create_experiment(manifest, experiment_id=experiment_id)
    try:
        _import_experiment_contents(store, root, experiment_id, summaries)
    except BaseException:
        store.delete_experiment(experiment_id)
        raise
    return experiment_id


def _import_experiment_contents(
    store: ResultsStore, root: Path, experiment_id: str, summaries: list[dict[str, Any]]
) -> None:
    for document_path in root.glob("*.json"):
        store.save_experiment_document(experiment_id, document_path.stem, _read_json(document_path))
    summary_by_trial = {
        (str(summary["task_id"]), int(summary["trial"])): summary for summary in summaries
    }
    trial_keys = set(summary_by_trial)
    for trial_root in root.glob("task_*/trial_*"):
        if trial_root.is_dir():
            trial_keys.add(
                (
                    trial_root.parent.name.removeprefix("task_"),
                    int(trial_root.name.removeprefix("trial_")),
                )
            )
    for task_id, trial_number in sorted(trial_keys):
        summary = summary_by_trial.get((task_id, trial_number))
        trial_root = root / f"task_{task_id}" / f"trial_{trial_number}"
        documents: dict[str, Any] = {}
        for name in DOCUMENT_NAMES:
            path = trial_root / f"{name}.json"
            if path.is_file():
                documents[name] = _read_json(path)
        policy_path = trial_root / "policy.md"
        if policy_path.is_file():
            documents["policy"] = policy_path.read_text(encoding="utf-8")
        store.create_trial(experiment_id, task_id, trial_number, documents)
        events_path = trial_root / "events.jsonl"
        events = (
            [
                json.loads(line)
                for line in events_path.read_text(encoding="utf-8").splitlines()
                if line
            ]
            if events_path.is_file()
            else []
        )
        store.save_trial(
            experiment_id,
            task_id,
            trial_number,
            summary=summary,
            documents={},
            events=events,
            audio_paths={"input": trial_root / "input.wav", "output": trial_root / "output.wav"},
        )
    clusters_path = root / "failure_clusters.json"
    if clusters_path.is_file():
        store.finish_experiment(experiment_id, _read_json(clusters_path))


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))
