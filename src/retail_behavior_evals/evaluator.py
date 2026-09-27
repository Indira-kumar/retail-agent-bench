"""Artifact evaluator for the versioned retail prompt behaviors."""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import cast

from retail_behavior_evals.catalog import BEHAVIORS, SUITE_ID, BehaviorCase, CheckKind
from retail_behavior_evals.models import BehaviorResult, CaseResult, SuiteResult, TrialArtifacts


def evaluate_behavior_suite(result_roots: Sequence[Path]) -> SuiteResult:
    trials = _load_trials(result_roots)
    behavior_results = tuple(
        _evaluate_behavior(
            behavior.behavior_id, behavior.title, behavior.prompt_target, behavior.cases, trials
        )
        for behavior in BEHAVIORS
    )
    return SuiteResult(
        suite_id=SUITE_ID,
        passed=all(result.passed for result in behavior_results),
        behaviors=behavior_results,
    )


def _evaluate_behavior(
    behavior_id: str,
    title: str,
    prompt_target: str,
    cases: tuple[BehaviorCase, ...],
    trials: dict[str, list[TrialArtifacts]],
) -> BehaviorResult:
    case_results = tuple(
        result for case in cases for result in _evaluate_case(case, trials.get(case.task_id, []))
    )
    return BehaviorResult(
        behavior_id=behavior_id,
        title=title,
        prompt_target=prompt_target,
        passed=all(result.passed for result in case_results),
        cases=case_results,
    )


def _evaluate_case(case: BehaviorCase, trials: list[TrialArtifacts]) -> tuple[CaseResult, ...]:
    if not trials:
        return (
            CaseResult(
                case_id=case.case_id,
                task_id=case.task_id,
                trial_id=None,
                source=None,
                passed=False,
                evidence="No matching task artifact was supplied.",
            ),
        )
    return tuple(_evaluate_trial(case, trial) for trial in trials)


def _evaluate_trial(case: BehaviorCase, trial: TrialArtifacts) -> CaseResult:
    if case.check is CheckKind.EXPECTED_ACTION:
        passed, evidence = _evaluate_expected_action(trial, _required(case.tool_name))
    else:
        passed, evidence = _evaluate_tool_error_explanation(
            trial,
            _required(case.tool_error),
            case.required_phrase_groups,
            case.forbidden_phrases,
        )
    return CaseResult(
        case_id=case.case_id,
        task_id=case.task_id,
        trial_id=trial.trial_id,
        source=str(trial.source),
        passed=passed,
        evidence=evidence,
    )


def _evaluate_expected_action(trial: TrialArtifacts, tool_name: str) -> tuple[bool, str]:
    expected = _expected_action(trial.task, tool_name)
    if expected is None:
        return False, f"Task has no expected {tool_name} action."

    attempts = [arguments for name, arguments in _tool_calls(trial.simulation) if name == tool_name]
    passed = expected in attempts
    return passed, f"Expected {expected}; observed {attempts or 'no attempts'}."


def _evaluate_tool_error_explanation(
    trial: TrialArtifacts,
    tool_error: str,
    required_phrase_groups: tuple[tuple[str, ...], ...],
    forbidden_phrases: tuple[str, ...],
) -> tuple[bool, str]:
    messages = _messages(trial.simulation)
    error_index = next(
        (
            index
            for index, message in enumerate(messages)
            if message.get("role") == "tool"
            and tool_error.casefold() in str(message.get("content", "")).casefold()
        ),
        None,
    )
    if error_index is None:
        return False, f"Tool error {tool_error!r} was not observed."

    response = " ".join(_assistant_responses_until_user(messages[error_index + 1 :])).casefold()
    missing_groups = [
        group for group in required_phrase_groups if not any(phrase in response for phrase in group)
    ]
    present_forbidden = [phrase for phrase in forbidden_phrases if phrase in response]
    passed = bool(response) and not missing_groups and not present_forbidden
    evidence = (
        f"Response after rejection: {response!r}; missing phrase groups: {missing_groups}; "
        f"forbidden phrases present: {present_forbidden}."
    )
    return passed, evidence


def _load_trials(result_roots: Sequence[Path]) -> dict[str, list[TrialArtifacts]]:
    trials: defaultdict[str, list[TrialArtifacts]] = defaultdict(list)
    for root in result_roots:
        if not root.is_dir():
            raise ValueError(f"Result directory does not exist: {root}")
        for simulation_path in sorted(root.glob("task_*/trial_*/simulation.json")):
            trial_dir = simulation_path.parent
            task_path = trial_dir / "task.json"
            if not task_path.is_file():
                raise ValueError(f"Missing task artifact beside {simulation_path}")
            task = _load_object(task_path)
            simulation = _load_object(simulation_path)
            task_id = str(task.get("id", simulation.get("task_id", "")))
            trials[task_id].append(
                TrialArtifacts(
                    task_id=task_id,
                    trial_id=trial_dir.name,
                    source=trial_dir,
                    task=task,
                    simulation=simulation,
                )
            )
    return dict(trials)


def _load_object(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object in {path}")
    return cast(dict[str, object], value)


def _expected_action(task: dict[str, object], tool_name: str) -> dict[str, object] | None:
    criteria = task.get("evaluation_criteria")
    if not isinstance(criteria, dict):
        return None
    actions = criteria.get("actions")
    if not isinstance(actions, list):
        return None
    for action in actions:
        if not isinstance(action, dict) or action.get("name") != tool_name:
            continue
        arguments = action.get("arguments")
        if isinstance(arguments, dict):
            return cast(dict[str, object], arguments)
    return None


def _tool_calls(simulation: dict[str, object]) -> Iterable[tuple[str, dict[str, object]]]:
    for message in _messages(simulation):
        calls = message.get("tool_calls")
        if not isinstance(calls, list):
            continue
        for call in calls:
            if not isinstance(call, dict):
                continue
            arguments = call.get("arguments")
            if isinstance(arguments, dict):
                yield str(call.get("name", "")), cast(dict[str, object], arguments)


def _messages(simulation: dict[str, object]) -> list[dict[str, object]]:
    messages = simulation.get("messages")
    if not isinstance(messages, list):
        return []
    return [cast(dict[str, object], message) for message in messages if isinstance(message, dict)]


def _assistant_responses_until_user(messages: list[dict[str, object]]) -> Iterable[str]:
    for message in messages:
        if message.get("role") == "user":
            return
        content = message.get("content")
        if message.get("role") == "assistant" and isinstance(content, str):
            yield content


def _required(value: str | None) -> str:
    if value is None:
        raise ValueError("Behavior case is missing required configuration")
    return value
