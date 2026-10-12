"""Command-line entry point for Module 2."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
from pathlib import Path

from dotenv import load_dotenv

from retail_eval.config import BenchmarkConfig
from retail_eval.migration import import_experiment
from retail_eval.results import default_results_store
from retail_eval.runner import BenchmarkRunner
from retail_eval.tasks import list_retail_tasks, load_retail_policy, load_retail_tasks
from retail_eval.visualizer import serve_visualizer


def main() -> None:
    load_dotenv(".env.local")
    args = _parser().parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    if args.command == "list-tasks":
        _list_tasks(args.split)
        return
    if args.command == "visualize":
        serve_visualizer(
            database=args.database,
            experiment_id=args.experiment_id,
            host=args.host,
            port=args.port,
            open_browser=not args.no_open,
        )
        return
    if args.command == "import":
        store = default_results_store(args.output)
        for root in args.results:
            print(f"Imported {import_experiment(store, root)} into {store.location}")
        return
    asyncio.run(_run(args))


async def _run(args: argparse.Namespace) -> None:
    task_ids = _parse_task_ids(args.task_ids, args.selection_file)
    tasks = load_retail_tasks(split=args.split, task_ids=task_ids)
    policy = load_retail_policy()
    config = BenchmarkConfig.from_env(
        output_dir=args.output,
        concurrency=args.concurrency,
        task_timeout_seconds=args.timeout,
    )
    store, experiment_id, summaries = await BenchmarkRunner(config).run(
        tasks=tasks,
        policy=policy,
        trials=args.trials,
        experiment_id=args.experiment_id,
    )
    passed = sum(1 for summary in summaries if summary["reward"] == 1.0)
    print(f"Experiment: {experiment_id}")
    print(f"Passed: {passed}/{len(summaries)}")
    print(f"Results database: {store.location}")
    invalid = sum(
        summary["termination_reason"] == "infrastructure_error"
        or "scoring_error" in summary["failure_labels"]
        for summary in summaries
    )
    if invalid:
        raise SystemExit(f"{invalid} trial(s) could not be evaluated reliably")


def _list_tasks(split: str) -> None:
    for task in list_retail_tasks(split=split):
        instructions = task.user_scenario.instructions
        reason = getattr(instructions, "reason_for_call", str(instructions))
        print(f"{task.id}\t{reason}")


def _parse_task_ids(value: str | None, selection_file: Path | None) -> list[str]:
    if value is not None and selection_file is not None:
        raise ValueError("Use either --task-ids or --selection-file, not both")
    if selection_file is not None:
        data = json.loads(selection_file.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            data = data.get("task_ids")
        if not isinstance(data, list):
            raise ValueError("Selection file must be a list or contain a task_ids list")
        task_ids = [str(task_id) for task_id in data]
    elif value is not None:
        task_ids = [task_id.strip() for task_id in value.split(",") if task_id.strip()]
    else:
        raise ValueError("Provide --task-ids or --selection-file")
    if not 1 <= len(task_ids) <= 30:
        raise ValueError("Select between 1 and 30 unique tasks")
    if len(set(task_ids)) != len(task_ids):
        raise ValueError("Task selection contains duplicates")
    return task_ids


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="retail-eval")
    parser.add_argument("--log-level", default="INFO")
    commands = parser.add_subparsers(dest="command", required=True)

    list_parser = commands.add_parser("list-tasks")
    list_parser.add_argument("--split", default="test")

    run_parser = commands.add_parser("run")
    run_parser.add_argument("--task-ids")
    run_parser.add_argument("--selection-file", type=Path)
    run_parser.add_argument("--split", default="test")
    run_parser.add_argument("--trials", type=int, default=1)
    run_parser.add_argument("--concurrency", type=int, choices=range(1, 6), default=3)
    run_parser.add_argument("--timeout", type=float)
    run_parser.add_argument("--output", type=Path, default=Path("eval-runs"))
    run_parser.add_argument("--experiment-id")

    visualize_parser = commands.add_parser("visualize")
    visualize_parser.add_argument("experiment_id")
    visualize_parser.add_argument(
        "--database", default=os.getenv("EVAL_DATABASE_URL", "eval-runs/results.sqlite3")
    )
    visualize_parser.add_argument("--host", default="127.0.0.1")
    visualize_parser.add_argument("--port", type=int, default=8765)
    visualize_parser.add_argument("--no-open", action="store_true")
    import_parser = commands.add_parser("import")
    import_parser.add_argument("results", type=Path, nargs="+")
    import_parser.add_argument("--output", type=Path, default=Path("eval-runs"))
    return parser


if __name__ == "__main__":
    main()
