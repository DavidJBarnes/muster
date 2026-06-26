"""Tests for the structured JSON logger."""

from __future__ import annotations

import json
import logging

import pytest

from muster_agent.log import JsonFormatter, get_logger, setup_logging


def test_format_emits_json_with_extra() -> None:
    """A record renders as one JSON line carrying core fields plus extras."""
    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="muster_agent.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="hello %s",
        args=("world",),
        exc_info=None,
    )
    record.agent_name = "atlas"
    payload = json.loads(formatter.format(record))
    assert payload["level"] == "INFO"
    assert payload["logger"] == "muster_agent.test"
    assert payload["msg"] == "hello world"
    assert payload["agent_name"] == "atlas"
    assert "ts" in payload


def test_setup_logging_is_idempotent() -> None:
    """Repeated setup reuses the JSON handler instead of stacking handlers."""
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
    setup_logging("INFO")
    setup_logging("DEBUG")
    json_handlers = [
        h for h in root.handlers if isinstance(h.formatter, JsonFormatter)
    ]
    assert len(json_handlers) == 1
    assert json_handlers[0].level == logging.DEBUG
    assert root.level == logging.DEBUG


def test_setup_logging_adds_handler_when_other_present() -> None:
    """A non-JSON handler already on root does not block adding the JSON one."""
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
    root.addHandler(logging.NullHandler())
    setup_logging("INFO")
    json_handlers = [
        h for h in root.handlers if isinstance(h.formatter, JsonFormatter)
    ]
    assert len(json_handlers) == 1


def test_get_logger_returns_named_logger() -> None:
    """The accessor returns the standard logger for the given name."""
    assert get_logger("muster_agent.x").name == "muster_agent.x"
