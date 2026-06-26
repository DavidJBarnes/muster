"""Tests for heartbeat ingestion and TTL liveness."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from muster_contracts import AgentStatus, Capabilities, HeartbeatMessage
from muster_controlplane.heartbeat import ingest, is_live, live_records
from muster_controlplane.registry import Registry

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_ingest_applies_heartbeat() -> None:
    """Ingesting a heartbeat updates the agent's status in the registry."""
    registry = Registry()
    registry.register("atlas", Capabilities(), NOW)
    message = HeartbeatMessage(agent_name="atlas", status=AgentStatus.WORKING)
    record = ingest(registry, message, NOW + timedelta(seconds=1))
    assert record.status == AgentStatus.WORKING
    assert registry.get("atlas").status == AgentStatus.WORKING  # type: ignore[union-attr]


def test_is_live_boundary() -> None:
    """Liveness holds at exactly the TTL and fails just past it."""
    registry = Registry()
    record = registry.register("atlas", Capabilities(), NOW)
    assert is_live(record, NOW + timedelta(seconds=30), ttl_s=30) is True
    assert is_live(record, NOW + timedelta(seconds=31), ttl_s=30) is False


def test_live_records_filters_stale() -> None:
    """Only agents seen within the TTL are reported live."""
    registry = Registry()
    registry.register("fresh", Capabilities(), NOW + timedelta(seconds=25))
    registry.register("stale", Capabilities(), NOW)
    live = live_records(registry, NOW + timedelta(seconds=40), ttl_s=30)
    assert [r.name for r in live] == ["fresh"]
