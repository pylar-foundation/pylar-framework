"""Structured JSON logging preset.

Call :func:`configure_logging` from a service provider's ``boot()``
to switch the entire application to JSON-structured log output —
one JSON object per line, compatible with Datadog, CloudWatch, ELK,
and every other modern log aggregation pipeline.

Usage::

    from pylar.support.logging import configure_logging
    configure_logging(level="INFO", json=True)
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any


class JsonFormatter(logging.Formatter):
    """Render every log record as a single-line JSON object.

    Fields: ``timestamp``, ``level``, ``logger``, ``message``, and
    any ``extra`` keys the caller passed. Tracebacks are included
    under ``exception`` when present.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        # Include extra fields set via logger.info("...", extra={...})
        for key in ("method", "path", "status", "duration_ms",
                     "request_id", "client"):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        if record.exc_info and record.exc_info[1] is not None:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(
    *,
    level: str = "INFO",
    json_format: bool = False,
) -> None:
    """Apply a logging configuration to the root logger.

    With ``json_format=True`` every log line is a JSON object.
    With ``json_format=False`` (default) the stdlib's standard
    format is used.

    Call once during application boot::

        class AppServiceProvider(ServiceProvider):
            async def boot(self, container: Container) -> None:
                configure_logging(level="INFO", json_format=not app.config.debug)
    """
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Remove existing handlers to avoid duplicate output.
    for handler in root.handlers[:]:
        root.removeHandler(handler)

    handler = logging.StreamHandler(sys.stderr)
    if json_format:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)-8s %(name)s  %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
    root.addHandler(handler)
