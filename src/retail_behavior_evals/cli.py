"""Command-line entry point for Module 3 behavior evals."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from dotenv import load_dotenv

from retail_behavior_evals.evaluator import evaluate_behavior_suite
from retail_eval.results import ResultsStore


def main() -> None:
    load_dotenv(".env.local")
    args = _parser().parse_args()
    result = evaluate_behavior_suite(args.database, args.experiments)
    report = json.dumps(result.as_dict(), indent=2)
    ResultsStore(args.database).save_analysis(result.suite_id, args.experiments, result.as_dict())
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(f"{report}\n", encoding="utf-8")
    print(report)
    if not result.passed:
        raise SystemExit(1)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="retail-behavior-eval")
    parser.add_argument("experiments", nargs="+")
    parser.add_argument(
        "--database", default=os.getenv("EVAL_DATABASE_URL", "eval-runs/results.sqlite3")
    )
    parser.add_argument("--output", type=Path)
    return parser


if __name__ == "__main__":
    main()
