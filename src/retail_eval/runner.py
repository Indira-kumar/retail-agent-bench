"""Concurrent benchmark orchestration, tau scoring, and failure clustering."""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from retail_eval.artifacts import TrialPaths, new_experiment_id
from retail_eval.config import BenchmarkConfig
from retail_eval.failures import build_failure_clusters, classify_failure
from retail_eval.livekit_runner import LiveKitTrialRunner, TrialResult
from retail_eval.policy import relevant_policy
from retail_eval.results import ResultsStore, default_results_store, new_manifest

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class TrialSpec:
    task: Any
    trial: int
    paths: TrialPaths
    relevant_policy: dict[str, Any]


class BenchmarkRunner:
    def __init__(
        self,
        config: BenchmarkConfig,
        *,
        trial_runner: LiveKitTrialRunner | None = None,
    ) -> None:
        self._config = config
        self._trial_runner = trial_runner or LiveKitTrialRunner(config)

    async def run(
        self,
        *,
        tasks: list[Any],
        policy: str,
        trials: int,
        experiment_id: str | None = None,
    ) -> tuple[ResultsStore, str, list[dict[str, Any]]]:
        _validate_scorer_credentials(self._config.scorer_llm)
        if not 1 <= len(tasks) <= 30:
            raise ValueError("Select between 1 and 30 benchmark tasks")
        if trials < 1:
            raise ValueError("trials must be positive")

        store = default_results_store(self._config.output_dir)
        run_name = experiment_id or new_experiment_id()
        store.create_experiment(
            new_manifest(
                run_name, self._config.public_dict(), [str(task.id) for task in tasks], trials
            )
        )
        with tempfile.TemporaryDirectory(prefix="retail-eval-") as staging:
            specs = []
            for task in tasks:
                for trial in range(1, trials + 1):
                    root = Path(staging) / f"task_{task.id}" / f"trial_{trial}"
                    root.mkdir(parents=True)
                    spec = TrialSpec(
                        task=task,
                        trial=trial,
                        paths=TrialPaths(root, root / "input.wav", root / "output.wav"),
                        relevant_policy=relevant_policy(task, policy),
                    )
                    store.create_trial(
                        run_name,
                        str(task.id),
                        trial,
                        {
                            "task": task.model_dump(mode="json"),
                            "policy": policy,
                            "relevant_policy": spec.relevant_policy,
                        },
                    )
                    specs.append(spec)
            summaries = await run_bounded(
                specs,
                concurrency=self._config.concurrency,
                execute=lambda spec: self._run_trial(spec, store, run_name, policy),
            )
        store.save_experiment_document(run_name, "summary", summaries)
        store.finish_experiment(run_name, build_failure_clusters(summaries))
        return store, run_name, summaries

    async def _run_trial(
        self,
        spec: TrialSpec,
        store: ResultsStore,
        experiment_id: str,
        policy: str,
    ) -> dict[str, Any]:
        try:
            result = await self._trial_runner.run(
                task=spec.task,
                trial=spec.trial,
                paths=spec.paths,
                policy=policy,
            )
        except Exception as exc:
            logger.exception("Trial setup failed for task=%s trial=%s", spec.task.id, spec.trial)
            summary = {
                "run_id": None,
                "task_id": str(spec.task.id),
                "trial": spec.trial,
                "reward": None,
                "termination_reason": "infrastructure_error",
                "duration_seconds": None,
                "failure_labels": ["infrastructure_error"],
                "livekit_room": None,
            }
            await asyncio.to_thread(
                store.save_trial,
                experiment_id,
                str(spec.task.id),
                spec.trial,
                summary=summary,
                documents={
                    "runner_error": {
                        "error_type": type(exc).__name__,
                        "error_message": str(exc),
                    }
                },
                events=[],
                audio_paths={"input": spec.paths.input_audio, "output": spec.paths.output_audio},
            )
            return summary

        scoring_error: Exception | None = None
        try:
            await _score(
                result,
                spec.task,
                self._config.scorer_llm,
                max_attempts=self._config.scorer_max_attempts,
                retry_delay_seconds=self._config.scorer_retry_delay_seconds,
            )
        except Exception as exc:
            scoring_error = exc
            logger.exception("Scoring failed for task=%s trial=%s", spec.task.id, spec.trial)
            result.simulation.info = {
                **(result.simulation.info or {}),
                "scoring_error": {"type": type(exc).__name__, "message": str(exc)},
            }

        labels = classify_failure(result.simulation, result.trace_messages)
        if scoring_error is not None:
            labels.insert(0, "scoring_error")
        reward = result.simulation.reward_info.reward if result.simulation.reward_info else None
        summary = {
            "run_id": result.simulation.id,
            "task_id": str(spec.task.id),
            "trial": spec.trial,
            "reward": reward,
            "termination_reason": result.simulation.termination_reason.value,
            "duration_seconds": result.simulation.duration,
            "failure_labels": labels,
            "livekit_room": result.simulation.provider_session_id,
        }
        await asyncio.to_thread(
            store.save_trial,
            experiment_id,
            str(spec.task.id),
            spec.trial,
            summary=summary,
            documents={
                "evaluator_events": result.evaluator_events,
                "evaluator_history": result.evaluator_history,
                "session_report": result.session_report,
                "simulation": result.simulation.model_dump(mode="json", exclude={"reward_info"}),
                "score": result.simulation.reward_info.model_dump(mode="json")
                if result.simulation.reward_info is not None
                else None,
                "failure": {"labels": labels},
            },
            events=result.trace_messages,
            audio_paths={"input": spec.paths.input_audio, "output": spec.paths.output_audio},
        )
        logger.info(
            "Completed task=%s trial=%s reward=%s failures=%s",
            spec.task.id,
            spec.trial,
            reward,
            labels,
        )
        return summary


async def run_bounded[T, R](
    items: Iterable[T],
    *,
    concurrency: int,
    execute: Callable[[T], Awaitable[R]],
) -> list[R]:
    if concurrency < 1:
        raise ValueError("concurrency must be positive")
    semaphore = asyncio.Semaphore(concurrency)

    async def run_one(item: T) -> R:
        async with semaphore:
            return await execute(item)

    return await asyncio.gather(*(run_one(item) for item in items))


async def _score(
    result: TrialResult,
    task: Any,
    scorer_llm: str,
    *,
    max_attempts: int,
    retry_delay_seconds: float,
) -> None:
    from tau2.evaluator import evaluator_nl_assertions
    from tau2.evaluator.evaluator import EvaluationType, evaluate_simulation

    evaluator_nl_assertions.DEFAULT_LLM_NL_ASSERTIONS = scorer_llm
    evaluator_nl_assertions.DEFAULT_LLM_NL_ASSERTIONS_ARGS = {
        **evaluator_nl_assertions.DEFAULT_LLM_NL_ASSERTIONS_ARGS,
        "response_format": {"type": "json_object"},
    }

    for attempt in range(1, max_attempts + 1):
        try:
            reward = await asyncio.to_thread(
                evaluate_simulation,
                simulation=result.simulation,
                task=task,
                evaluation_type=EvaluationType.ALL,
                solo_mode=False,
                domain="retail",
            )
            result.simulation.reward_info = reward
            return
        except Exception:
            if attempt == max_attempts:
                raise
            logger.warning(
                "Scoring attempt %s/%s failed; retrying",
                attempt,
                max_attempts,
                exc_info=True,
            )
            await asyncio.sleep(retry_delay_seconds * attempt)


def _validate_scorer_credentials(scorer_llm: str) -> None:
    if not scorer_llm.startswith("openrouter/"):
        raise ValueError("EVAL_SCORER_LLM must use the openrouter/<model> format")
    if not os.getenv("OPENROUTER_API_KEY"):
        raise ValueError("OPENROUTER_API_KEY is required by EVAL_SCORER_LLM")
