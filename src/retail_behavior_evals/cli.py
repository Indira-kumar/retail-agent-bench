"""Command-line entry point for Module 3 behavior evals."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from retail_behavior_evals.evaluator import evaluate_behavior_suite


def main() -> None:
    args = _parser().parse_args()
    result = evaluate_behavior_suite(args.results)
    report = json.dumps(result.as_dict(), indent=2)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(f"{report}\n", encoding="utf-8")
    print(report)
    if not result.passed:
        raise SystemExit(1)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="retail-behavior-eval")
    parser.add_argument("results", type=Path, nargs="+")
    parser.add_argument("--output", type=Path)
    return parser


if __name__ == "__main__":
    main()
