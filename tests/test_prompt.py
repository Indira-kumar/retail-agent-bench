from retail_agent.config import RetailAgentConfig
from retail_agent.prompt import compose_instructions


def test_injected_policy_is_preserved_verbatim() -> None:
    policy = "# Retail policy\n\nAuthenticate the customer first."

    instructions = compose_instructions(policy, RetailAgentConfig())

    assert f"<domain_policy>\n{policy}\n</domain_policy>" in instructions
    assert "partial transcript" in instructions


def test_empty_policy_is_rejected() -> None:
    try:
        compose_instructions("  ", RetailAgentConfig())
    except ValueError as exc:
        assert "non-empty" in str(exc)
    else:
        raise AssertionError("Expected an empty policy to be rejected")
