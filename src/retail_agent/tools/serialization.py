"""Stable serialization for tool results and trace payloads."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any


def serialize_tool_result(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(
        to_json_value(value),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def to_json_value(value: Any) -> Any:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if hasattr(value, "model_dump"):
        return to_json_value(value.model_dump(mode="json"))
    if is_dataclass(value) and not isinstance(value, type):
        return to_json_value(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): to_json_value(item) for key, item in value.items()}
    if isinstance(value, list | tuple | set):
        return [to_json_value(item) for item in value]
    if isinstance(value, Enum):
        return to_json_value(value.value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Decimal | Path):
        return str(value)
    raise TypeError(f"Unsupported tool result type: {type(value).__name__}")
