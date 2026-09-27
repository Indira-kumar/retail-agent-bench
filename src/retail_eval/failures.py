"""Deterministic failure labels and cross-run clusters."""

from __future__ import annotations

from collections import defaultdict
from typing import Any


def classify_failure(simulation: Any, trace_messages: list[dict[str, Any]]) -> list[str]:
    labels: list[str] = []
    termination = str(
        getattr(simulation.termination_reason, "value", simulation.termination_reason)
    )
    if termination not in {"user_stop", "agent_stop"}:
        labels.append(termination)

    reward = simulation.reward_info
    if reward is not None:
        if reward.db_check is not None and not reward.db_check.db_match:
            labels.append("db_state_mismatch")
        if reward.nl_assertions and any(not check.met for check in reward.nl_assertions):
            labels.append("nl_assertion_failed")
        if reward.communicate_checks and any(not check.met for check in reward.communicate_checks):
            labels.append("communication_failed")
        if reward.action_checks and any(not check.action_match for check in reward.action_checks):
            labels.append("expected_action_missing")
        if reward.reward == 0 and not labels:
            labels.append("reward_failed")

    structured_events = [
        message.get("event", {})
        for message in trace_messages
        if message.get("message_type") == "structured_event"
    ]
    if any(event.get("kind") == "tool.call.failed" for event in structured_events):
        labels.append("tool_error")
    if any(
        _session_event_name(event) == "user_transcription_timeout" for event in structured_events
    ):
        labels.append("transcription_timeout")
    if any(_session_event_name(event) == "error" for event in structured_events):
        labels.append("session_error")

    return list(dict.fromkeys(labels))


def build_failure_clusters(summaries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: defaultdict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    for summary in summaries:
        labels = tuple(sorted(str(label) for label in summary.get("failure_labels", [])))
        if labels:
            grouped[labels].append(summary)

    clusters = [
        {
            "labels": list(labels),
            "count": len(items),
            "task_ids": sorted({str(item["task_id"]) for item in items}),
            "run_ids": [str(item["run_id"]) for item in items],
            "average_reward": sum(float(item.get("reward") or 0.0) for item in items) / len(items),
        }
        for labels, items in grouped.items()
    ]
    return sorted(clusters, key=lambda cluster: (-int(cluster["count"]), cluster["labels"]))


def _session_event_name(event: Any) -> str | None:
    if not isinstance(event, dict) or event.get("kind") != "session.event":
        return None
    payload = event.get("payload")
    return str(payload.get("event_name")) if isinstance(payload, dict) else None
