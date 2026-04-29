"""Structured JSON logging formatter with request-id correlation.

Binding it from a service provider or test bootstrap is one line:

    from pylar.observability import install_json_logging
    install_json_logging(level="INFO")

Every emitted record becomes a single line of JSON with the well-known
fields used by log shippers (Loki, Elasticsearch, Datadog):

    {"timestamp": "...", "level": "INFO", "logger": "...",
     "message": "...", "request_id": "a1b2", ...extras...}

The formatter reads the request id from the same
:class:`contextvars.ContextVar` that :class:`RequestIdMiddleware`
installs — no global state, no coupling to the HTTP layer.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

from pylar.http.middlewares.request_id import current_request_id

#: Fields baked in by stdlib ``LogRecord.__init__`` — we skip them when
#: serialising ``record.__dict__`` so the JSON output stays clean.
_RESERVED_RECORD_ATTRS = frozenset({
    "args", "asctime", "created", "exc_info", "exc_text", "filename",
    "funcName", "levelname", "levelno", "lineno", "message", "module",
    "msecs", "msg", "name", "pathname", "process", "processName",
    "relativeCreated", "stack_info", "thread", "threadName", "taskName",
})


class JsonFormatter(logging.Formatter):
    """Format :class:`LogRecord`s as single-line JSON objects.

    Extra attributes passed via ``logger.info("msg", extra={"k": v})``
    are merged into the output at the top level so log shippers can
    index them without nesting.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        request_id = current_request_id()
        if request_id:
            payload["request_id"] = request_id

        # Unhandled exception — attach formatted traceback.
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        # Pull any ``extra={...}`` caller fields into the top level.
        for key, value in record.__dict__.items():
            if key in _RESERVED_RECORD_ATTRS or key.startswith("_"):
                continue
            if key in payload:
                continue
            try:
                json.dumps(value)
            except (TypeError, ValueError):
                value = repr(value)
            payload[key] = value

        return json.dumps(payload, ensure_ascii=False)


def install_json_logging(
    *,
    level: str | int = "INFO",
    stream: Any = None,
    reset_handlers: bool = True,
) -> None:
    """Configure the root logger with a single :class:`JsonFormatter` handler.

    *reset_handlers* removes any pre-existing root handlers so the
    output isn't mixed with pytest or uvicorn's defaults. Pass
    ``False`` to keep them. *stream* defaults to ``sys.stderr`` to
    mirror the stdlib ``basicConfig`` behaviour.
    """
    root = logging.getLogger()
    if reset_handlers:
        for handler in list(root.handlers):
            root.removeHandler(handler)

    handler = logging.StreamHandler(stream or sys.stderr)
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
    root.setLevel(level)
