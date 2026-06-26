"""Centralized structured (JSON) logging for the agent.

Every component logs through :func:`get_logger`; one line of JSON is emitted per
record so the agent's output is machine-parseable wherever it runs. Arbitrary
context is attached per call via the standard ``extra=`` mechanism and flows
straight into the JSON object. Self-contained on purpose — a likely candidate to
hoist into a shared ``muster-common`` package later.
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any

# Attributes present on every ``LogRecord`` that are not caller-supplied
# ``extra`` context; everything else on the record is treated as an extra field.
_STANDARD_ATTRS = frozenset(logging.makeLogRecord({}).__dict__) | {
    "message",
    "asctime",
    "taskName",
}


class JsonFormatter(logging.Formatter):
    """Format a log record as a single-line JSON object.

    Emits ``ts``, ``level``, ``logger`` and ``msg`` for every record, then folds
    in any caller-supplied ``extra`` keys (e.g. ``agent_name``, ``job_id``) so
    structured context survives to the log sink.
    """

    def format(self, record: logging.LogRecord) -> str:
        """Render ``record`` as a compact JSON line."""
        payload: dict[str, Any] = {
            "ts": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _STANDARD_ATTRS:
                payload[key] = value
        return json.dumps(payload, default=str)


def setup_logging(level: str) -> None:
    """Configure the root logger to emit JSON to stdout, idempotently.

    Safe to call more than once: an existing JSON handler is reused rather than
    stacked, so repeated calls only adjust the level instead of duplicating
    output.
    """
    root = logging.getLogger()
    root.setLevel(level)
    for handler in root.handlers:
        if isinstance(handler.formatter, JsonFormatter):
            handler.setLevel(level)
            return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    handler.setLevel(level)
    root.addHandler(handler)


def get_logger(name: str) -> logging.Logger:
    """Return the named logger; pair with :func:`setup_logging` for JSON output."""
    return logging.getLogger(name)
