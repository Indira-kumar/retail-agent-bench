"""Structural contracts for tau-owned runtime tools."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, Protocol


class TauTool(Protocol):
    """Subset of ``tau2.environment.tool.Tool`` consumed by Module 1."""

    name: str

    @property
    def openai_schema(self) -> Mapping[str, Any]: ...

    def __call__(self, **kwargs: Any) -> Any: ...


class TauToolkit(Protocol):
    """Subset of ``ToolKitBase`` used for runtime adaptation."""

    def get_tools(self, include: list[str] | None = None) -> Mapping[str, TauTool]: ...

    def tool_type(self, tool_name: str) -> Any: ...

    def tool_mutates_state(self, tool_name: str) -> bool: ...


ToolSource = Mapping[str, TauTool] | list[TauTool] | tuple[TauTool, ...] | TauToolkit
ToolCallable = Callable[..., Any]
