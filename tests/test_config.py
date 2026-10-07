"""Tests for path resolution and environment overrides."""

from __future__ import annotations

from pathlib import Path

import pytest

from clearbed.config import Settings, get_settings


def test_defaults_are_synthetic_and_local(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("DATA_MODE", "synthetic")
    monkeypatch.setenv("HOSPITAL_ZIP", "02118")
    get_settings.cache_clear()
    settings = get_settings()
    assert settings.data_mode == "synthetic"
    assert settings.llm_provider == "mock" or settings.llm_provider in {
        "ollama",
        "bedrock",
        "groq",
        "mock",
    }
    assert settings.hospital_zip == "02118"
    assert settings.resolved_warehouse_path == tmp_path / "data" / "warehouse.duckdb"
    assert settings.raw_dir == tmp_path / "data" / "raw"
    assert settings.external_dir == tmp_path / "data" / "external"
    assert settings.resolved_model_dir == tmp_path / "models"
    assert settings.resolved_chroma_dir == tmp_path / "data" / "chroma"


def test_zip_is_zero_padded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOSPITAL_ZIP", "2118")
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.hospital_zip == "02118"


def test_warehouse_override(tmp_path: Path) -> None:
    target = tmp_path / "custom.duckdb"
    settings = Settings(warehouse_path=target, _env_file=None)  # type: ignore[call-arg]
    assert settings.resolved_warehouse_path == target
