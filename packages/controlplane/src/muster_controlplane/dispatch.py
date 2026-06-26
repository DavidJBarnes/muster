"""Job dispatch (stub) and the in-memory result store.

In this pass dispatch is deliberately dumb: a job goes to *any* live agent, since
capability matching belongs to a later iteration. Results streamed back by agents
are collected per job so a caller (a connector, or a test) can read them.
"""

from __future__ import annotations

from collections import defaultdict
from uuid import UUID

from muster_contracts import JobMessage, Origin, ResultMessage

from muster_controlplane.agent_ws import ConnectionManager


class NoAvailableAgent(Exception):
    """Raised when a job is submitted but no agent is connected to take it."""


async def dispatch_job(
    connections: ConnectionManager, instruction: str, origin: Origin
) -> JobMessage:
    """Send ``instruction`` to any one live agent and return the created job.

    The first available connection is chosen (no capability matching yet). Raises
    :class:`NoAvailableAgent` when the fleet is empty.
    """
    live = connections.all()
    if not live:
        raise NoAvailableAgent("no live agents")
    job = JobMessage(instruction=instruction, origin=origin)
    await live[0].send(job)
    return job


class ResultStore:
    """Collects job results streamed back from agents, keyed by job id."""

    def __init__(self) -> None:
        """Start with no results recorded."""
        self._by_job: dict[UUID, list[ResultMessage]] = defaultdict(list)

    def add(self, result: ResultMessage) -> None:
        """Record one result frame for its job."""
        self._by_job[result.job_id].append(result)

    def results(self, job_id: UUID) -> list[ResultMessage]:
        """Return all results recorded for ``job_id`` (possibly empty)."""
        return list(self._by_job.get(job_id, []))

    def final(self, job_id: UUID) -> ResultMessage | None:
        """Return the terminal result for ``job_id``, if one has arrived."""
        for result in self._by_job.get(job_id, []):
            if result.final:
                return result
        return None
