"""Tau retail task loading and selection."""

from __future__ import annotations

from typing import Any


def load_retail_tasks(*, split: str, task_ids: list[str]) -> list[Any]:
    from tau2.domains.retail.environment import get_tasks

    available = {str(task.id): task for task in get_tasks(split)}
    missing = [task_id for task_id in task_ids if task_id not in available]
    if missing:
        raise ValueError(f"Retail tasks not found in split {split!r}: {missing}")
    return [available[task_id] for task_id in task_ids]


def list_retail_tasks(*, split: str) -> list[Any]:
    from tau2.domains.retail.environment import get_tasks

    return list(get_tasks(split))


def load_retail_policy() -> str:
    from tau2.domains.retail.environment import get_environment

    return str(get_environment().get_policy())
