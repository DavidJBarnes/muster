"""In-memory registry of known agents: name → capabilities, status, last-seen.

This is the hub's authoritative view of the fleet. It is pure synchronous state
with no I/O, so it is trivially unit-testable; liveness (deriving DOWN/STALE from
``last_seen``) lives in :mod:`muster_controlplane.heartbeat`, and the WebSocket
plumbing that feeds it lives in :mod:`muster_controlplane.agent_ws`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from muster_contracts import AgentStatus, Capabilities


@dataclass
class AgentRecord:
    """The hub's record for one registered agent."""

    name: str
    capabilities: Capabilities
    status: AgentStatus
    last_seen: datetime
    current_job_id: UUID | None = None


class Registry:
    """Tracks registered agents by name.

    Registration is authoritative (a re-register replaces the prior record);
    heartbeats update status and freshness via :meth:`touch`.
    """

    def __init__(self) -> None:
        """Start with an empty fleet."""
        self._agents: dict[str, AgentRecord] = {}

    def register(
        self, name: str, capabilities: Capabilities, now: datetime
    ) -> AgentRecord:
        """Record (or replace) an agent as freshly connected and IDLE."""
        record = AgentRecord(
            name=name,
            capabilities=capabilities,
            status=AgentStatus.IDLE,
            last_seen=now,
        )
        self._agents[name] = record
        return record

    def touch(
        self,
        name: str,
        status: AgentStatus,
        current_job_id: UUID | None,
        now: datetime,
    ) -> AgentRecord:
        """Update a known agent's status, current job, and last-seen time.

        Raises ``KeyError`` if the agent was never registered — a heartbeat
        should only ever follow a registration on the same connection.
        """
        record = self._agents[name]
        record.status = status
        record.current_job_id = current_job_id
        record.last_seen = now
        return record

    def remove(self, name: str) -> None:
        """Forget an agent (e.g. on disconnect); a no-op if already gone."""
        self._agents.pop(name, None)

    def get(self, name: str) -> AgentRecord | None:
        """Return the record for ``name``, or ``None`` if unknown."""
        return self._agents.get(name)

    def all(self) -> list[AgentRecord]:
        """Return every current record."""
        return list(self._agents.values())

    def __contains__(self, name: object) -> bool:
        """Support ``name in registry``."""
        return name in self._agents

    def __len__(self) -> int:
        """Number of registered agents."""
        return len(self._agents)
