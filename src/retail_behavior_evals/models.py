"""Results returned by the retail prompt-behavior suite."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class TrialArtifacts:
    task_id: str
    trial_id: str
    source: Path
    task: dict[str, object]
    simulation: dict[str, object]


@dataclass(frozen=True)
class CaseResult:
    case_id: str
    task_id: str
    trial_id: str | None
    source: str | None
    passed: bool
    evidence: str

    def as_dict(self) -> dict[str, object]:
        return {
            "case_id": self.case_id,
            "task_id": self.task_id,
            "trial_id": self.trial_id,
            "source": self.source,
            "passed": self.passed,
            "evidence": self.evidence,
        }


@dataclass(frozen=True)
class BehaviorResult:
    behavior_id: str
    title: str
    prompt_target: str
    passed: bool
    cases: tuple[CaseResult, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "behavior_id": self.behavior_id,
            "title": self.title,
            "prompt_target": self.prompt_target,
            "passed": self.passed,
            "passed_cases": sum(case.passed for case in self.cases),
            "total_cases": len(self.cases),
            "cases": [case.as_dict() for case in self.cases],
        }


@dataclass(frozen=True)
class SuiteResult:
    suite_id: str
    passed: bool
    behaviors: tuple[BehaviorResult, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "suite_id": self.suite_id,
            "passed": self.passed,
            "passed_behaviors": sum(behavior.passed for behavior in self.behaviors),
            "total_behaviors": len(self.behaviors),
            "behaviors": [behavior.as_dict() for behavior in self.behaviors],
        }
