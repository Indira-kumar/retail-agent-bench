from __future__ import annotations

import json
from pathlib import Path

from retail_behavior_evals import evaluate_behavior_suite

EXPECTED_LOOKUPS = {
    "40": ("find_user_id_by_email", {"email": "isabella.lopez3271@example.com"}),
    "49": (
        "find_user_id_by_name_zip",
        {"first_name": "Aarav", "last_name": "Anderson", "zip": "19031"},
    ),
    "51": (
        "find_user_id_by_name_zip",
        {"first_name": "Sofia", "last_name": "Li", "zip": "78260"},
    ),
    "53": (
        "find_user_id_by_name_zip",
        {"first_name": "Sofia", "last_name": "Li", "zip": "78260"},
    ),
}


def test_behavior_suite_passes_exact_lookups_and_grounded_explanation(tmp_path: Path) -> None:
    for task_id, (tool_name, arguments) in EXPECTED_LOOKUPS.items():
        _write_trial(tmp_path, task_id, tool_name, arguments, arguments)
    _write_rejection_trial(
        tmp_path,
        "The order now has return requested status, so it cannot be exchanged.",
    )

    result = evaluate_behavior_suite([tmp_path])

    assert result.passed
    assert all(behavior.passed for behavior in result.behaviors)


def test_behavior_suite_exposes_baseline_failures(tmp_path: Path) -> None:
    for task_id, (tool_name, arguments) in EXPECTED_LOOKUPS.items():
        _write_trial(tmp_path, task_id, tool_name, arguments, {"incorrect": "value"})
    _write_rejection_trial(tmp_path, "The exchange failed due to an internal error.")

    result = evaluate_behavior_suite([tmp_path])

    assert not result.passed
    assert [behavior.passed for behavior in result.behaviors] == [False, False, False]
    assert result.behaviors[1].as_dict()["total_cases"] == 3
    assert "internal error" in result.behaviors[2].cases[0].evidence


def test_behavior_suite_fails_when_a_task_is_missing(tmp_path: Path) -> None:
    result = evaluate_behavior_suite([tmp_path])

    assert not result.passed
    assert all(case.trial_id is None for behavior in result.behaviors for case in behavior.cases)


def _write_trial(
    root: Path,
    task_id: str,
    tool_name: str,
    expected_arguments: dict[str, str],
    observed_arguments: dict[str, str],
) -> None:
    trial_dir = root / f"task_{task_id}" / "trial_1"
    trial_dir.mkdir(parents=True)
    _write_json(
        trial_dir / "task.json",
        {
            "id": task_id,
            "evaluation_criteria": {
                "actions": [{"name": tool_name, "arguments": expected_arguments}]
            },
        },
    )
    _write_json(
        trial_dir / "simulation.json",
        {
            "task_id": task_id,
            "messages": [
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [{"name": tool_name, "arguments": observed_arguments}],
                }
            ],
        },
    )


def _write_rejection_trial(root: Path, response: str) -> None:
    trial_dir = root / "task_27" / "trial_1"
    trial_dir.mkdir(parents=True)
    _write_json(trial_dir / "task.json", {"id": "27", "evaluation_criteria": {"actions": []}})
    _write_json(
        trial_dir / "simulation.json",
        {
            "task_id": "27",
            "messages": [
                {
                    "role": "tool",
                    "content": "Error: Non-delivered order cannot be exchanged",
                },
                {"role": "assistant", "content": response, "tool_calls": None},
                {"role": "user", "content": "Okay."},
            ],
        },
    )


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")
