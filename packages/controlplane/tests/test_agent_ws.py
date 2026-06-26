"""Tests for the per-connection agent protocol handler."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from fastapi import WebSocketDisconnect

from muster_contracts import (
    AgentStatus,
    Capabilities,
    HeartbeatMessage,
    RegisterMessage,
    ResultMessage,
    ResultStatus,
)
from muster_controlplane.agent_ws import (
    AgentConnection,
    ConnectionManager,
    _utcnow,
    handle_agent,
)
from muster_controlplane.registry import Registry

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


class _FakeSocket:
    """A scriptable server-side socket; disconnects when its script drains."""

    def __init__(self, incoming: list[str]) -> None:
        self.incoming = list(incoming)
        self.sent: list[str] = []
        self.accepted = False
        self.closed = False

    async def accept(self) -> None:
        self.accepted = True

    async def receive_text(self) -> str:
        if not self.incoming:
            raise WebSocketDisconnect(code=1000)
        return self.incoming.pop(0)

    async def send_text(self, data: str) -> None:
        self.sent.append(data)

    async def close(self) -> None:
        self.closed = True


def _reg(name: str = "atlas") -> str:
    """Serialize a register frame for ``name``."""
    return RegisterMessage(
        agent_name=name, capabilities=Capabilities(tools=["claude"])
    ).model_dump_json()


async def test_handle_agent_full_flow() -> None:
    """Registers, ingests a heartbeat and a result, then cleans up on disconnect."""
    heartbeat = HeartbeatMessage(
        agent_name="atlas", status=AgentStatus.WORKING, current_job_id=uuid4()
    )
    result = ResultMessage(
        job_id=uuid4(), status=ResultStatus.SUCCESS, content="done", final=True
    )
    socket = _FakeSocket([_reg(), heartbeat.model_dump_json(), result.model_dump_json()])
    registry = Registry()
    connections = ConnectionManager()
    collected: list[ResultMessage] = []

    # Default ``now`` is used here so _utcnow is exercised.
    await handle_agent(socket, registry, connections, collected.append)

    assert socket.accepted is True
    assert [r.content for r in collected] == ["done"]
    # finally-block cleanup removes the agent and its connection
    assert len(registry) == 0
    assert connections.all() == []


async def test_handle_agent_rejects_non_register_first_frame() -> None:
    """A first frame that is not a register closes the socket and registers nothing."""
    heartbeat = HeartbeatMessage(agent_name="atlas", status=AgentStatus.IDLE)
    socket = _FakeSocket([heartbeat.model_dump_json()])
    registry = Registry()
    connections = ConnectionManager()

    await handle_agent(
        socket, registry, connections, lambda r: None, now=lambda: NOW
    )

    assert socket.closed is True
    assert len(registry) == 0


async def test_handle_agent_ignores_unexpected_message() -> None:
    """A non-heartbeat, non-result inbound frame is ignored, not dispatched."""
    stray = RegisterMessage(agent_name="atlas", capabilities=Capabilities())
    socket = _FakeSocket([_reg(), stray.model_dump_json()])
    registry = Registry()
    connections = ConnectionManager()
    collected: list[ResultMessage] = []

    await handle_agent(
        socket, registry, connections, collected.append, now=lambda: NOW
    )

    assert collected == []


def test_connection_manager_get_and_remove() -> None:
    """The manager resolves and forgets connections by name."""
    manager = ConnectionManager()
    connection = AgentConnection("atlas", _FakeSocket([]))
    manager.add(connection)
    assert manager.get("atlas") is connection
    manager.remove("atlas")
    assert manager.get("atlas") is None


def test_utcnow_is_timezone_aware() -> None:
    """The default clock returns an aware UTC timestamp."""
    assert _utcnow().tzinfo is not None
