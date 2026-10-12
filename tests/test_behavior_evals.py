from __future__ import annotations

from pathlib import Path

from retail_behavior_evals import evaluate_behavior_suite
from retail_eval.results import ResultsStore, new_manifest

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


def _store(tmp_path: Path) -> ResultsStore:
    store = ResultsStore(tmp_path / "results.sqlite3")
    store.create_experiment(new_manifest("test", {}, [*EXPECTED_LOOKUPS, "27"], 1))
    return store


def test_behavior_suite_passes_exact_lookups_and_grounded_explanation(tmp_path: Path) -> None:
    store = _store(tmp_path)
    for task_id, (tool_name, arguments) in EXPECTED_LOOKUPS.items():
        _write_trial(store, task_id, tool_name, arguments, arguments)
    _write_rejection_trial(
        store, "The order now has return requested status, so it cannot be exchanged."
    )

    result = evaluate_behavior_suite(store.database, ["test"])

    assert result.passed
    assert all(behavior.passed for behavior in result.behaviors)


def test_behavior_suite_exposes_baseline_failures(tmp_path: Path) -> None:
    store = _store(tmp_path)
    for task_id, (tool_name, arguments) in EXPECTED_LOOKUPS.items():
        _write_trial(store, task_id, tool_name, arguments, {"incorrect": "value"})
    _write_rejection_trial(store, "The exchange failed due to an internal error.")

    result = evaluate_behavior_suite(store.database, ["test"])

    assert not result.passed
    assert [behavior.passed for behavior in result.behaviors] == [False, False, False]
    assert result.behaviors[1].as_dict()["total_cases"] == 3
    assert "internal error" in result.behaviors[2].cases[0].evidence


def test_behavior_suite_fails_when_a_task_is_missing(tmp_path: Path) -> None:
    store = _store(tmp_path)
    result = evaluate_behavior_suite(store.database, ["test"])

    assert not result.passed
    assert all(case.trial_id is None for behavior in result.behaviors for case in behavior.cases)


def _write_trial(
    store: ResultsStore,
    task_id: str,
    tool_name: str,
    expected_arguments: dict[str, str],
    observed_arguments: dict[str, str],
) -> None:
    store.create_trial(
        "test",
        task_id,
        1,
        {
            "task": {
                "id": task_id,
                "evaluation_criteria": {
                    "actions": [{"name": tool_name, "arguments": expected_arguments}]
                },
            }
        },
    )
    store.save_trial(
        "test",
        task_id,
        1,
        summary={"task_id": task_id, "trial": 1},
        documents={
            "simulation": {
                "task_id": task_id,
                "messages": [
                    {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [{"name": tool_name, "arguments": observed_arguments}],
                    }
                ],
            }
        },
        events=[],
        audio_paths={},
    )


def _write_rejection_trial(store: ResultsStore, response: str) -> None:
    store.create_trial(
        "test", "27", 1, {"task": {"id": "27", "evaluation_criteria": {"actions": []}}}
    )
    store.save_trial(
        "test",
        "27",
        1,
        summary={"task_id": "27", "trial": 1},
        documents={
            "simulation": {
                "task_id": "27",
                "messages": [
                    {"role": "tool", "content": "Error: Non-delivered order cannot be exchanged"},
                    {"role": "assistant", "content": response, "tool_calls": None},
                    {"role": "user", "content": "Okay."},
                ],
            }
        },
        events=[],
        audio_paths={},
    )
