from __future__ import annotations

from typing import Any

from retail_agent.events import event_payload


class FakeProviderError(Exception):
    status_code = 1006
    request_id = None
    retryable = True


class FakeModelError:
    def __init__(self, error: Exception) -> None:
        self.error = error


class FakeErrorEvent:
    def __init__(self, error: Exception) -> None:
        self.error = FakeModelError(error)

    def model_dump(self, *, mode: str) -> dict[str, Any]:
        assert mode == "json"
        return {
            "type": "error",
            "error": {"type": "stt_error", "recoverable": True},
        }


def test_event_payload_includes_provider_error_details() -> None:
    error = FakeProviderError("deepgram connection closed unexpectedly")

    payload = event_payload(FakeErrorEvent(error))

    assert payload["error"]["detail"] == {
        "type": "FakeProviderError",
        "message": "deepgram connection closed unexpectedly",
        "status_code": 1006,
        "retryable": True,
    }
