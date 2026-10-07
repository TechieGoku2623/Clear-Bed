"""Tests for the PHI redaction filter."""

from __future__ import annotations

import json

import pytest

from clearbed.config import Settings
from clearbed.logging import configure_logging, log_event, redact


def test_redact_nested_keys() -> None:
    cleaned = redact({"name": "Ada Lovelace", "stay_id": "s1", "child": {"ssn": "000-00-0000"}})
    assert cleaned["name"] == "[REDACTED]"
    assert cleaned["stay_id"] == "s1"
    assert cleaned["child"]["ssn"] == "[REDACTED]"


def test_pretty_log_redacts_sensitive_fields(capsys: pytest.CaptureFixture[str]) -> None:
    settings = Settings(environment="dev", _env_file=None)  # type: ignore[call-arg]
    logger = configure_logging(settings)
    log_event(
        logger,
        "loaded stay",
        name="Ada Lovelace",
        ssn="123-45-6789",
        address="1 Main",
        birthdate="1950-01-01",
        phone="555-0100",
        stay_id="stay-1",
    )
    err = capsys.readouterr().err
    assert "Ada Lovelace" not in err
    assert "123-45-6789" not in err
    assert "stay-1" in err
    assert "[REDACTED]" in err


def test_json_formatter_redacts(capsys: pytest.CaptureFixture[str]) -> None:
    settings = Settings(environment="prod", log_level="INFO", _env_file=None)  # type: ignore[call-arg]
    logger = configure_logging(settings)
    log_event(
        logger,
        "loaded stay",
        name="Ada Lovelace",
        ssn="123-45-6789",
        address="1 Main St",
        birthdate="1950-01-01",
        phone="555-0100",
        stay_id="stay-1",
    )
    err = capsys.readouterr().err
    assert "Ada Lovelace" not in err
    assert "123-45-6789" not in err
    assert "1 Main St" not in err
    assert "1950-01-01" not in err
    assert "555-0100" not in err
    assert "stay-1" in err
    payload = json.loads(err.strip().splitlines()[-1])
    assert payload["fields"]["name"] == "[REDACTED]"
    assert payload["fields"]["phone"] == "[REDACTED]"
    assert payload["message"] == "loaded stay"


def test_dict_message_argument_is_redacted(capsys: pytest.CaptureFixture[str]) -> None:
    settings = Settings(environment="dev", _env_file=None)  # type: ignore[call-arg]
    logger = configure_logging(settings)
    logger.info("row %s", {"name": "Hidden Person", "stay_id": "s9"})
    err = capsys.readouterr().err
    assert "Hidden Person" not in err
    assert "[REDACTED]" in err
    assert "s9" in err
