"""Structured logging with a redaction filter for identifier-like fields.

Production logs are JSON. Development logs are plain text. Fields named
``name``, ``ssn``, ``address``, ``birthdate``, or ``phone`` are replaced
before the record is formatted. Never log a full patient record.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from clearbed.config import Settings, get_settings

SENSITIVE_FIELDS = frozenset({"name", "ssn", "address", "birthdate", "phone"})
REDACTED = "[REDACTED]"


def redact(value: Any) -> Any:
    """Return ``value`` with sensitive dictionary keys replaced."""
    if isinstance(value, dict):
        cleaned: dict[Any, Any] = {}
        for key, item in value.items():
            if str(key).lower() in SENSITIVE_FIELDS:
                cleaned[key] = REDACTED
            else:
                cleaned[key] = redact(item)
        return cleaned
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact(item) for item in value)
    return value


class RedactionFilter(logging.Filter):
    """Replace sensitive mapping keys on a log record before it is formatted."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, dict):
            record.msg = redact(record.msg)
        if isinstance(record.args, dict):
            record.args = redact(record.args)
        elif isinstance(record.args, tuple):
            record.args = tuple(
                redact(item) if isinstance(item, (dict, list, tuple)) else item
                for item in record.args
            )
        fields = getattr(record, "fields", None)
        if isinstance(fields, dict):
            record.fields = redact(fields)
        return True


class JsonFormatter(logging.Formatter):
    """Emit one JSON object per log line."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        fields = getattr(record, "fields", None)
        if fields is not None:
            payload["fields"] = fields
        return json.dumps(payload, default=str)


class PrettyFormatter(logging.Formatter):
    """Emit a single readable line, with structured fields appended."""

    def format(self, record: logging.LogRecord) -> str:
        base = f"{record.levelname} {record.name} {record.getMessage()}"
        fields = getattr(record, "fields", None)
        if fields:
            return f"{base} fields={fields}"
        return base


def configure_logging(settings: Settings | None = None) -> logging.Logger:
    """Attach a redacting handler to the ``clearbed`` logger and return it."""
    settings = settings or get_settings()
    logger = logging.getLogger("clearbed")
    logger.handlers.clear()
    logger.setLevel(settings.log_level.upper())
    logger.propagate = False
    handler = logging.StreamHandler()
    handler.addFilter(RedactionFilter())
    if settings.environment == "prod":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(PrettyFormatter())
    logger.addHandler(handler)
    logger.addFilter(RedactionFilter())
    return logger


def get_logger(name: str | None = None) -> logging.Logger:
    """Return a child of the ClearBed logger. Configure it first in entry points."""
    if name:
        return logging.getLogger("clearbed").getChild(name)
    return logging.getLogger("clearbed")


def log_event(logger: logging.Logger, message: str, **fields: Any) -> None:
    """Log ``message`` with structured fields that pass through redaction.

    Do not pass a patient record. Pass identifiers such as ``stay_id`` only.
    """
    logger.info(message, extra={"fields": fields})
