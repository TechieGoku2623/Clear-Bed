"""Shared pytest setup.

Environment defaults are applied before test modules import ClearBed so the
suite never points at a real-data mode or a live external LLM.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

os.environ.setdefault("DATA_MODE", "synthetic")
os.environ.setdefault("LLM_PROVIDER", "mock")
os.environ.setdefault("API_KEY", "test-key")
os.environ.setdefault("ENVIRONMENT", "dev")

import pytest

from clearbed.config import get_settings


@pytest.fixture(autouse=True)
def _reset_settings_cache() -> Iterator[None]:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
