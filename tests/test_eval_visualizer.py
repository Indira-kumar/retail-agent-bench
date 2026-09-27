from __future__ import annotations

from pathlib import Path

import pytest

from retail_eval.visualizer import parse_range, resolve_request_path, validate_results_dir


def test_validate_results_dir_accepts_experiment(tmp_path: Path) -> None:
    (tmp_path / "experiment.json").write_text("{}", encoding="utf-8")
    (tmp_path / "summary.json").write_text("[]", encoding="utf-8")

    assert validate_results_dir(tmp_path) == tmp_path.resolve()


def test_validate_results_dir_reports_missing_manifest(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match=r"experiment\.json, summary\.json"):
        validate_results_dir(tmp_path)


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
