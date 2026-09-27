"""Deterministic policy-section selection for retail tasks."""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

_ACTION_SECTIONS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("cancel", ("Generic action rules", "Cancel pending order")),
    (
        "modify_pending_order_payment",
        ("Generic action rules", "Modify pending order", "Modify payment"),
    ),
    (
        "modify_pending_order_items",
        ("Generic action rules", "Modify pending order", "Modify items"),
    ),
    ("modify", ("Generic action rules", "Modify pending order")),
    ("return", ("Generic action rules", "Return delivered order")),
    ("exchange", ("Generic action rules", "Exchange delivered order")),
)


def split_policy_sections(policy: str) -> dict[str, str]:
    headings = list(re.finditer(r"(?m)^(#{1,3})\s+(.+?)\s*$", policy))
    sections: dict[str, str] = {}
    for index, heading in enumerate(headings):
        start = heading.start()
        end = headings[index + 1].start() if index + 1 < len(headings) else len(policy)
        sections[heading.group(2)] = policy[start:end].strip()
    return sections


def relevant_policy(task: Any, policy: str) -> dict[str, Any]:
    sections = split_policy_sections(policy)
    selected = ["Retail agent policy"]
    tool_names = _expected_tool_names(task)

    for tool_name in tool_names:
        for marker, headings in _ACTION_SECTIONS:
            if marker in tool_name:
                selected.extend(headings)
                break
        if "user" in tool_name:
            selected.append("User")
        if "product" in tool_name or "item" in tool_name:
            selected.append("Product")
        if "order" in tool_name:
            selected.append("Order")

    unique_headings = list(dict.fromkeys(selected))
    return {
        "task_id": str(task.id),
        "expected_tools": tool_names,
        "sections": [
            {"heading": heading, "content": sections[heading]}
            for heading in unique_headings
            if heading in sections
        ],
    }


def _expected_tool_names(task: Any) -> list[str]:
    criteria = getattr(task, "evaluation_criteria", None)
    actions: Iterable[Any] = getattr(criteria, "actions", None) or []
    return list(dict.fromkeys(str(action.name) for action in actions))
