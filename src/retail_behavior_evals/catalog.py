"""Versioned behavior suite derived from the baseline voice runs."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class CheckKind(StrEnum):
    EXPECTED_ACTION = "expected_action"
    TOOL_ERROR_EXPLANATION = "tool_error_explanation"


@dataclass(frozen=True)
class BehaviorCase:
    case_id: str
    task_id: str
    check: CheckKind
    tool_name: str | None = None
    tool_error: str | None = None
    required_phrase_groups: tuple[tuple[str, ...], ...] = ()
    forbidden_phrases: tuple[str, ...] = ()


@dataclass(frozen=True)
class Behavior:
    behavior_id: str
    title: str
    prompt_target: str
    cases: tuple[BehaviorCase, ...]


SUITE_ID = "retail_prompt_behaviors_v1"

BEHAVIORS = (
    Behavior(
        behavior_id="spoken_email_canonicalization",
        title="Canonicalize spoken email addresses",
        prompt_target=(
            "Convert spoken punctuation and digits into one lowercase email address without "
            "inventing separators before account lookup."
        ),
        cases=(
            BehaviorCase(
                case_id="task_40_email_lookup",
                task_id="40",
                check=CheckKind.EXPECTED_ACTION,
                tool_name="find_user_id_by_email",
            ),
        ),
    ),
    Behavior(
        behavior_id="spoken_name_authentication",
        title="Recover exact names for authentication",
        prompt_target=(
            "After an uncertain or failed name lookup, collect and read back the first and last "
            "names separately instead of repeating a guess or transferring immediately."
        ),
        cases=(
            BehaviorCase(
                case_id="task_49_name_lookup",
                task_id="49",
                check=CheckKind.EXPECTED_ACTION,
                tool_name="find_user_id_by_name_zip",
            ),
            BehaviorCase(
                case_id="task_51_name_lookup",
                task_id="51",
                check=CheckKind.EXPECTED_ACTION,
                tool_name="find_user_id_by_name_zip",
            ),
            BehaviorCase(
                case_id="task_53_name_lookup",
                task_id="53",
                check=CheckKind.EXPECTED_ACTION,
                tool_name="find_user_id_by_name_zip",
            ),
        ),
    ),
    Behavior(
        behavior_id="tool_rejection_grounding",
        title="Explain tool rejections truthfully",
        prompt_target=(
            "Tell the customer the concrete business reason returned by a tool instead of "
            "calling an expected policy or state rejection an internal error."
        ),
        cases=(
            BehaviorCase(
                case_id="task_27_exchange_rejection",
                task_id="27",
                check=CheckKind.TOOL_ERROR_EXPLANATION,
                tool_error="Non-delivered order cannot be exchanged",
                required_phrase_groups=(
                    (
                        "non-delivered",
                        "not delivered",
                        "no longer delivered",
                        "return requested",
                        "return status",
                    ),
                    ("exchange", "exchanged"),
                ),
                forbidden_phrases=("internal error",),
            ),
        ),
    ),
)
