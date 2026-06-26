"""Heartbeat ingestion and liveness (TTL) derivation.

Agents report ``IDLE``/``WORKING``/``BLOCKED`` explicitly; the hub derives whether
an agent is *live* purely from how recently it was last heard from, against a
configurable time-to-live. Keeping this separate from :mod:`registry` lets the
liveness policy evolve without touching the state store.
"""

from __future__ import annotations

from datetime import datetime

from muster_contracts import HeartbeatMessage

from muster_controlplane.registry import AgentRecord, Registry

DEFAULT_TTL_S = 30.0
"""Seconds since ``last_seen`` after which an agent is considered not live."""


def ingest(registry: Registry, message: HeartbeatMessage, now: datetime) -> AgentRecord:
    """Apply a heartbeat to the registry, refreshing status and freshness."""
    return registry.touch(
        message.agent_name, message.status, message.current_job_id, now
    )


def is_live(record: AgentRecord, now: datetime, ttl_s: float = DEFAULT_TTL_S) -> bool:
    """Return whether ``record`` was seen within ``ttl_s`` seconds of ``now``."""
    return (now - record.last_seen).total_seconds() <= ttl_s


def live_records(
    registry: Registry, now: datetime, ttl_s: float = DEFAULT_TTL_S
) -> list[AgentRecord]:
    """Return only the records currently considered live."""
    return [r for r in registry.all() if is_live(r, now, ttl_s)]
