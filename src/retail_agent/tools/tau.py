"""Adapter from tau's runtime tool objects to LiveKit function tools."""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from time import monotonic
from typing import Any, cast

from livekit.agents import RunContext, function_tool, llm

from retail_agent.events import EventEmitter, EventKind, EventSource
from retail_agent.tools.contracts import TauTool, TauToolkit, ToolSource
from retail_agent.tools.serialization import serialize_tool_result, to_json_value

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ToolMetadata:
    name: str
    category: str | None
    mutates_state: bool | None


class TauToolAdapter:
    """Creates schema-faithful LiveKit tools from tau tools.

    Calls are serialized because tau's retail toolkit mutates an in-memory database and its
    domain policy permits only one tool call at a time. The adapter observes policy-relevant
    metadata but deliberately does not enforce policy in Module 1.
    """

    def __init__(
        self,
        source: ToolSource,
        *,
        emitter: EventEmitter,
        include: Iterable[str] | None = None,
    ) -> None:
        self._emitter = emitter
        self._source = source
        self._lock = asyncio.Lock()
        self._tau_tools = _collect_tools(source, include)
        if not self._tau_tools:
            raise ValueError("At least one tau tool is required")
        self._metadata = {name: _metadata_for(source, name) for name in sorted(self._tau_tools)}
        self._livekit_tools = [
            self._adapt(name, self._tau_tools[name]) for name in sorted(self._tau_tools)
        ]

    @property
    def tools(self) -> list[llm.Tool]:
        return list(self._livekit_tools)

    @property
    def metadata(self) -> Mapping[str, ToolMetadata]:
        return self._metadata

    def _adapt(self, name: str, tau_tool: TauTool) -> llm.Tool:
        raw_schema = _livekit_schema(name, tau_tool.openai_schema)

        async def invoke(raw_arguments: dict[str, object], context: RunContext[Any]) -> str:
            del context
            call_id = _call_id(name)
            started = monotonic()
            metadata = self._metadata[name]
            self._emitter.emit(
                EventKind.TOOL_CALL_STARTED,
                EventSource.TOOL_ADAPTER,
                tool_call_id=call_id,
                tool_name=name,
                arguments=raw_arguments,
                category=metadata.category,
                mutates_state=metadata.mutates_state,
            )
            try:
                async with self._lock:
                    result = tau_tool(**raw_arguments)
                    if inspect.isawaitable(result):
                        result = await result
                serialized = serialize_tool_result(result)
            except Exception as exc:
                self._emitter.emit(
                    EventKind.TOOL_CALL_FAILED,
                    EventSource.TOOL_ADAPTER,
                    tool_call_id=call_id,
                    tool_name=name,
                    arguments=raw_arguments,
                    error_type=type(exc).__name__,
                    error_message=str(exc),
                    duration_seconds=monotonic() - started,
                )
                logger.exception("Tau tool %s failed", name)
                raise

            self._emitter.emit(
                EventKind.TOOL_CALL_COMPLETED,
                EventSource.TOOL_ADAPTER,
                tool_call_id=call_id,
                tool_name=name,
                arguments=raw_arguments,
                result=to_json_value(result),
                duration_seconds=monotonic() - started,
            )
            return serialized

        invoke.__name__ = name
        return cast(llm.Tool, function_tool(invoke, raw_schema=raw_schema))


def adapt_tau_tools(
    source: ToolSource,
    *,
    emitter: EventEmitter,
    include: Iterable[str] | None = None,
) -> TauToolAdapter:
    return TauToolAdapter(source, emitter=emitter, include=include)


def _collect_tools(source: ToolSource, include: Iterable[str] | None) -> dict[str, TauTool]:
    selected = list(include) if include is not None else None
    if hasattr(source, "get_tools"):
        tools = source.get_tools(include=selected)
    elif isinstance(source, Mapping):
        tools = source
    else:
        tools = {tool.name: tool for tool in source}

    normalized = dict(tools)
    if selected is not None and not hasattr(source, "get_tools"):
        missing = set(selected) - set(normalized)
        if missing:
            raise ValueError(f"Tau tools not found: {sorted(missing)}")
        normalized = {name: normalized[name] for name in selected}

    for name, tool in normalized.items():
        if name != tool.name:
            raise ValueError(f"Tool mapping key {name!r} does not match tool name {tool.name!r}")
        _livekit_schema(name, tool.openai_schema)
    return normalized


def _metadata_for(source: ToolSource, name: str) -> ToolMetadata:
    if not hasattr(source, "tool_type"):
        return ToolMetadata(name=name, category=None, mutates_state=None)

    toolkit = cast(TauToolkit, source)
    category_value = toolkit.tool_type(name)
    category = getattr(category_value, "value", str(category_value))
    mutates_state = toolkit.tool_mutates_state(name)
    return ToolMetadata(name=name, category=category, mutates_state=mutates_state)


def _livekit_schema(name: str, schema: Mapping[str, Any]) -> dict[str, Any]:
    function_schema = schema.get("function", schema)
    if not isinstance(function_schema, Mapping):
        raise ValueError(f"Tool {name!r} has an invalid OpenAI schema")

    schema_name = function_schema.get("name")
    if schema_name != name:
        raise ValueError(f"Tool {name!r} schema declares name {schema_name!r}")
    parameters = function_schema.get("parameters")
    if not isinstance(parameters, Mapping):
        raise ValueError(f"Tool {name!r} schema has no parameter object")

    return {
        "type": "function",
        "name": name,
        "description": str(function_schema.get("description") or name),
        "parameters": dict(parameters),
    }


def _call_id(name: str) -> str:
    from uuid import uuid4

    return f"{name}-{uuid4()}"
