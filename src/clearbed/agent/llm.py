"""LLM provider factory.

Groq is refused unless ``DATA_MODE`` is synthetic. Real patient data may use
only a local Ollama model or Bedrock. Temperature is 0. The mock provider
exists for tests and CI and is also refused on real data.
"""

from __future__ import annotations

from typing import Any, Protocol

from clearbed.config import Settings, get_settings


class PhiSafetyError(RuntimeError):
    """Raised when a provider is not allowed for the current data mode."""


class Chat(Protocol):
    """Minimal chat interface used by the copilot."""

    def invoke(self, messages: list[Any]) -> Any:
        """Return a message whose ``content`` is the model text."""


class MockChat:
    """Deterministic stand-in. It never invents citations that were not supplied."""

    def invoke(self, messages: list[Any]) -> Any:
        from types import SimpleNamespace

        text = ""
        if messages:
            last = messages[-1]
            text = str(getattr(last, "content", last))
        if "safety judge" in text.lower():
            return SimpleNamespace(content='{"unsupported": []}')
        cites = [
            line
            for line in text.splitlines()
            if "http" in line or line.strip().lower().startswith("source")
        ]
        body = "Summary (mock model): follow the grounded plan below.\n" + "\n".join(cites[:8])
        return SimpleNamespace(content=body)


def message_text(result: Any) -> str:
    """Read text from a LangChain message or a mock result."""
    content = getattr(result, "content", result)
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                parts.append(str(block.get("text", "")))
        return "\n".join(parts)
    return str(content)


def build_chat_model(settings: Settings | None = None) -> Any:
    """Return the configured chat model, enforcing the PHI rule first."""
    settings = settings or get_settings()
    provider = settings.llm_provider
    if provider == "groq" and settings.data_mode != "synthetic":
        raise PhiSafetyError(
            "Groq provider refuses to run when DATA_MODE != 'synthetic' (PHI safety). "
            "Use bedrock or ollama for real data."
        )
    if provider == "mock":
        if settings.data_mode != "synthetic":
            raise PhiSafetyError("The mock LLM is only available when DATA_MODE is synthetic.")
        return MockChat()
    if provider == "ollama":
        from langchain_ollama import ChatOllama

        return ChatOllama(
            model=settings.ollama_model, base_url=settings.ollama_base_url, temperature=0
        )
    if provider == "bedrock":
        from langchain_aws import ChatBedrock

        bedrock_kwargs: dict[str, Any] = {
            "model_id": settings.bedrock_model_id,
            "region_name": settings.aws_region,
            "model_kwargs": {"temperature": 0},
        }
        return ChatBedrock(**bedrock_kwargs)
    if provider == "groq":
        from langchain_groq import ChatGroq
        from pydantic import SecretStr

        return ChatGroq(
            model=settings.groq_model,
            api_key=SecretStr(settings.groq_api_key),
            temperature=0,
        )
    raise ValueError(f"Unknown LLM provider: {provider}")
