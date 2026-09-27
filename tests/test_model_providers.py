from __future__ import annotations

import pytest

from retail_agent.model_providers import build_llm, parse_llm_provider


def test_livekit_llm_uses_inference_model_descriptor() -> None:
    assert build_llm(provider="livekit", model="provider/model") == "provider/model"


def test_parse_llm_provider_defaults_to_livekit() -> None:
    assert parse_llm_provider(None, variable="LLM_PROVIDER") == "livekit"
    assert parse_llm_provider(" OpenRouter ", variable="LLM_PROVIDER") == "openrouter"


def test_parse_llm_provider_rejects_unknown_provider() -> None:
    with pytest.raises(ValueError, match="LLM_PROVIDER must be 'livekit' or 'openrouter'"):
        parse_llm_provider("unknown", variable="LLM_PROVIDER")


def test_openrouter_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    with pytest.raises(ValueError, match="OPENROUTER_API_KEY is required"):
        build_llm(provider="openrouter", model="openrouter/auto")
