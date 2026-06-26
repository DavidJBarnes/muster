"""Tests for the in-memory agent registry."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from muster_contracts import AgentStatus, Capabilities
from muster_controlplane.registry import Registry

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_register_records_idle_agent() -> None:
    """A freshly registered agent is IDLE with its capabilities and last_seen."""
    registry = Registry()
    record = registry.register(
        "atlas", Capabilities(tools=["claude"]), NOW
    )
    assert record.status == AgentStatus.IDLE
    assert record.capabilities.tools == ["claude"]
    assert record.last_seen == NOW
    assert "atlas" in registry
    assert len(registry) == 1


def test_touch_updates_status_and_freshness() -> None:
    """touch advances status, current job and last_seen for a known agent."""
    registry = Registry()
    registry.register("atlas", Capabilities(), NOW)
    later = NOW + timedelta(seconds=5)
    job_id = uuid4()
    record = registry.touch("atlas", AgentStatus.WORKING, job_id, later)
    assert record.status == AgentStatus.WORKING
    assert record.current_job_id == job_id
    assert record.last_seen == later


def test_touch_unknown_agent_raises() -> None:
    """A heartbeat for an unregistered agent is a programmer error."""
    with pytest.raises(KeyError):
        Registry().touch("ghost", AgentStatus.IDLE, None, NOW)


def test_remove_and_get() -> None:
    """remove forgets an agent; get returns None for the unknown."""
    registry = Registry()
    registry.register("atlas", Capabilities(), NOW)
    assert registry.get("atlas") is not None
    registry.remove("atlas")
    registry.remove("atlas")  # idempotent
    assert registry.get("atlas") is None
    assert registry.all() == []
