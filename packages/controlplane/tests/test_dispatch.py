"""Tests for job dispatch and the result store."""

from __future__ import annotations

from uuid import uuid4

import pytest

from muster_contracts import JobMessage, Origin, ResultMessage, ResultStatus, parse_message
from muster_controlplane.agent_ws import AgentConnection, ConnectionManager
from muster_controlplane.dispatch import NoAvailableAgent, ResultStore, dispatch_job

ORIGIN = Origin(connector="test", channel="c", thread="t")


class _FakeSocket:
    """Captures frames sent to a (pretend) connected agent."""

    def __init__(self) -> None:
        self.sent: list[str] = []

    async def accept(self) -> None:  # pragma: no cover - unused here
        ...

    async def receive_text(self) -> str:  # pragma: no cover - unused here
        return ""

    async def send_text(self, data: str) -> None:
        self.sent.append(data)

    async def close(self) -> None:  # pragma: no cover - unused here
        ...


async def test_dispatch_sends_job_to_live_agent() -> None:
    """A job is serialized and pushed to the first live connection."""
    socket = _FakeSocket()
    connections = ConnectionManager()
    connections.add(AgentConnection("atlas", socket))
    job = await dispatch_job(connections, "render a teapot", ORIGIN)
    sent = parse_message(socket.sent[0])
    assert isinstance(sent, JobMessage)
    assert sent.instruction == "render a teapot"
    assert sent.job_id == job.job_id


async def test_dispatch_without_agents_raises() -> None:
    """Submitting with an empty fleet raises NoAvailableAgent."""
    with pytest.raises(NoAvailableAgent):
        await dispatch_job(ConnectionManager(), "x", ORIGIN)


def test_result_store_collects_and_finds_final() -> None:
    """Results accumulate per job; final() returns the terminal frame."""
    store = ResultStore()
    job_id = uuid4()
    store.add(ResultMessage(job_id=job_id, status=ResultStatus.PARTIAL, content="a", final=False))
    store.add(ResultMessage(job_id=job_id, status=ResultStatus.SUCCESS, content="ab", final=True))
    results = store.results(job_id)
    assert [r.content for r in results] == ["a", "ab"]
    final = store.final(job_id)
    assert final is not None and final.status == ResultStatus.SUCCESS


def test_result_store_no_final_yet() -> None:
    """final() is None for an unknown job or one with no terminal frame."""
    store = ResultStore()
    job_id = uuid4()
    assert store.results(job_id) == []
    assert store.final(job_id) is None
    store.add(ResultMessage(job_id=job_id, status=ResultStatus.PARTIAL, content="a", final=False))
    assert store.final(job_id) is None
