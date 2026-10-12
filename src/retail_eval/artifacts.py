"""Temporary audio paths for a benchmark trial."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4


def new_experiment_id() -> str:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{timestamp}-{uuid4().hex[:8]}"


@dataclass(frozen=True, slots=True)
class TrialPaths:
    root: Path
    input_audio: Path
    output_audio: Path
