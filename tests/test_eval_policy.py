from __future__ import annotations

from types import SimpleNamespace

from retail_eval.policy import relevant_policy, split_policy_sections

POLICY = """# Retail agent policy

Authenticate and confirm mutations.

## Generic action rules

Call mutation tools once.

## Modify pending order

Only pending orders can change.

### Modify payment

Use a different payment method.

### Order

Orders have a status.
"""


def test_policy_sections_preserve_heading_content() -> None:
    sections = split_policy_sections(POLICY)

    assert sections["Retail agent policy"].startswith("# Retail agent policy")
    assert "Call mutation tools once" in sections["Generic action rules"]


def test_relevant_policy_uses_expected_tools() -> None:
    task = SimpleNamespace(
        id="12",
        evaluation_criteria=SimpleNamespace(
            actions=[SimpleNamespace(name="modify_pending_order_payment")]
        ),
    )

    selected = relevant_policy(task, POLICY)

    assert selected["expected_tools"] == ["modify_pending_order_payment"]
    assert [section["heading"] for section in selected["sections"]] == [
        "Retail agent policy",
        "Generic action rules",
        "Modify pending order",
        "Modify payment",
        "Order",
    ]
