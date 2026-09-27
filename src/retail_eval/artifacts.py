"""Durable artifacts for benchmark experiments and task trials."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4


def new_experiment_id() -> str:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{timestamp}-{uuid4().hex[:8]}"


@dataclass(frozen=True, slots=True)
class TrialPaths:
    root: Path
    input_audio: Path
    output_audio: Path


class ArtifactStore:
    def __init__(self, output_dir: Path, experiment_id: str) -> None:
        self.root = output_dir.resolve() / experiment_id
        self.root.mkdir(parents=True, exist_ok=False)

    def initialize(self, *, config: dict[str, Any], task_ids: list[str], trials: int) -> None:
        self.write_json(
            self.root / "experiment.json",
            {
                "experiment_id": self.root.name,
                "created_at": datetime.now(UTC).isoformat(),
                "task_ids": task_ids,
                "trials": trials,
                "config": config,
            },
        )

    def create_trial(
        self,
        *,
        task: Any,
        trial: int,
        policy: str,
        relevant_policy: dict[str, Any],
    ) -> TrialPaths:
        root = self.root / f"task_{task.id}" / f"trial_{trial}"
        root.mkdir(parents=True, exist_ok=False)
        self.write_json(root / "task.json", task.model_dump(mode="json"))
        self.write_json(root / "relevant_policy.json", relevant_policy)
        (root / "policy.md").write_text(policy, encoding="utf-8")
        return TrialPaths(
            root=root,
            input_audio=root / "input.wav",
            output_audio=root / "output.wav",
        )

    def write_json(self, path: Path, value: Any) -> None:
        temporary = path.with_suffix(f"{path.suffix}.tmp")
        temporary.write_text(
            json.dumps(value, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
        temporary.replace(path)

    def write_jsonl(self, path: Path, values: list[dict[str, Any]]) -> None:
        temporary = path.with_suffix(f"{path.suffix}.tmp")
        with temporary.open("w", encoding="utf-8") as output:
            for value in values:
                output.write(json.dumps(value, ensure_ascii=False, default=str))
                output.write("\n")
        temporary.replace(path)
