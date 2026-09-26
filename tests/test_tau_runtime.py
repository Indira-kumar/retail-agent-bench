from __future__ import annotations

import os
from pathlib import Path

import pytest

from retail_agent import create_retail_agent
from retail_agent.integrations.tau import load_default_retail_bindings


@pytest.mark.skipif(
    not os.getenv("TAU2_DATA_DIR") or not Path(os.getenv("TAU2_DATA_DIR", "")).exists(),
    reason="TAU2_DATA_DIR is required for the real tau integration check",
)
def test_real_tau_retail_tools_adapt_to_livekit() -> None:
    bindings = load_default_retail_bindings()
    agent = create_retail_agent(
        policy=bindings.policy,
        tools=bindings.tools,
        session_id="tau-integration",
    )

    assert len(agent.tools) == 16
    assert "cancel_pending_order" in agent.retail_state.tool_names
    assert "transfer_to_human_agents" in agent.retail_state.tool_names
    assert agent.tool_adapter.metadata["cancel_pending_order"].category == "write"
    assert agent.tool_adapter.metadata["cancel_pending_order"].mutates_state is True
    assert bindings.db is not None
