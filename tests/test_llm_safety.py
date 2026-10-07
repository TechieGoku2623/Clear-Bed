"""Groq and the mock model are refused unless the data mode is synthetic."""

from __future__ import annotations

import pytest

from clearbed.agent.llm import PhiSafetyError, build_chat_model
from clearbed.config import Settings


def test_groq_refuses_real_data() -> None:
    settings = Settings(data_mode="real", llm_provider="groq", environment="dev")
    with pytest.raises(PhiSafetyError):
        build_chat_model(settings)


def test_mock_refuses_real_data() -> None:
    settings = Settings(data_mode="real", llm_provider="mock", environment="dev")
    with pytest.raises(PhiSafetyError):
        build_chat_model(settings)


def test_mock_echoes_citations() -> None:
    settings = Settings(data_mode="synthetic", llm_provider="mock", environment="dev")
    text = str(
        build_chat_model(settings)
        .invoke([type("M", (), {"content": "Source: https://www.medicare.gov/coverage"})()])
        .content
    )
    assert "https://www.medicare.gov/coverage" in text
