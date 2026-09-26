"""Optional loader for tau's default retail environment.

This module imports tau lazily so the core package remains importable without tau installed.
It does not use tau's orchestrator.
"""

from __future__ import annotations

from typing import Any

from retail_agent.runtime import RuntimeBindings


def bindings_from_environment(environment: Any) -> RuntimeBindings:
    """Extract policy and bound tools from a tau-compatible environment."""

    get_policy = getattr(environment, "get_policy", None)
    get_tools = getattr(environment, "get_tools", None)
    if not callable(get_policy) or not callable(get_tools):
        raise TypeError("Tau environment must provide get_policy() and get_tools()")

    toolkit = getattr(environment, "tools", None)
    db = getattr(toolkit, "db", None)
    return RuntimeBindings(
        policy=get_policy(),
        tools=toolkit if toolkit is not None else get_tools(),
        db=db,
        owner=environment,
    )


def load_default_retail_bindings() -> RuntimeBindings:
    """Create a fresh tau retail environment and return its runtime bindings."""

    try:
        from tau2.domains.retail.environment import get_environment
    except ImportError as exc:
        raise RuntimeError(
            "The optional tau runtime is not installed. Run `uv sync --extra tau`."
        ) from exc

    try:
        environment = get_environment()
    except FileNotFoundError as exc:
        raise RuntimeError(
            "Tau benchmark data was not found. Set TAU2_DATA_DIR to the data/ directory "
            "of the pinned tau2-bench checkout. See docs/manual-setup.md."
        ) from exc
    return bindings_from_environment(environment)
