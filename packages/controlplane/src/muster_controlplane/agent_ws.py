"""The WebSocket surface agents connect to, and per-connection bookkeeping.

An agent opens one socket, sends a :class:`RegisterMessage`, then streams
heartbeats and job results. :func:`handle_agent` runs that protocol for one
connection; :class:`ConnectionManager` tracks the live sockets so the dispatcher
can push jobs back out to a chosen agent. The socket is abstracted behind
:class:`AgentSocket` so the handler is unit-testable without a real WebSocket.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Protocol

from fastapi import WebSocketDisconnect

from muster_contracts import (
    HeartbeatMessage,
    JobMessage,
    RegisterMessage,
    ResultMessage,
    parse_message,
)

from muster_controlplane.heartbeat import ingest
from muster_controlplane.registry import Registry

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    """Return the current timezone-aware UTC time."""
    return datetime.now(timezone.utc)


class AgentSocket(Protocol):
    """The subset of a WebSocket the agent handler relies on."""

    async def accept(self) -> None: ...
    async def receive_text(self) -> str: ...
    async def send_text(self, data: str) -> None: ...
    async def close(self) -> None: ...


class AgentConnection:
    """A live agent socket the hub can push jobs to."""

    def __init__(self, name: str, socket: AgentSocket) -> None:
        """Bind an agent name to its open socket."""
        self.name = name
        self._socket = socket

    async def send(self, message: JobMessage) -> None:
        """Send a job to this agent as a JSON text frame."""
        await self._socket.send_text(message.model_dump_json())


class ConnectionManager:
    """Tracks live agent connections by name."""

    def __init__(self) -> None:
        """Start with no live connections."""
        self._connections: dict[str, AgentConnection] = {}

    def add(self, connection: AgentConnection) -> None:
        """Register a live connection (replacing any prior one for the name)."""
        self._connections[connection.name] = connection

    def remove(self, name: str) -> None:
        """Drop a connection on disconnect; a no-op if already gone."""
        self._connections.pop(name, None)

    def get(self, name: str) -> AgentConnection | None:
        """Return the live connection for ``name``, or ``None``."""
        return self._connections.get(name)

    def all(self) -> list[AgentConnection]:
        """Return every live connection."""
        return list(self._connections.values())


ResultSink = Callable[[ResultMessage], None]
"""Callback invoked with each job result a connected agent streams back."""


async def handle_agent(
    socket: AgentSocket,
    registry: Registry,
    connections: ConnectionManager,
    on_result: ResultSink,
    now: Callable[[], datetime] = _utcnow,
) -> None:
    """Run the agent protocol for one socket until it disconnects.

    Accepts the socket, requires a :class:`RegisterMessage` as the first frame
    (closing on violation), then ingests heartbeats and forwards results to
    ``on_result`` until the agent disconnects. Registry and connection state are
    always cleaned up on the way out.
    """
    await socket.accept()
    first = await socket.receive_text()
    message = parse_message(first)
    if not isinstance(message, RegisterMessage):
        logger.warning("first frame was %s, not register; closing", message.type)
        await socket.close()
        return

    registry.register(message.agent_name, message.capabilities, now())
    connections.add(AgentConnection(message.agent_name, socket))
    logger.info("agent registered: %s", message.agent_name)
    try:
        while True:
            frame = await socket.receive_text()
            inbound = parse_message(frame)
            if isinstance(inbound, HeartbeatMessage):
                ingest(registry, inbound, now())
            elif isinstance(inbound, ResultMessage):
                on_result(inbound)
            else:
                logger.info("ignoring inbound %s from %s", inbound.type, message.agent_name)
    except WebSocketDisconnect:
        logger.info("agent disconnected: %s", message.agent_name)
    finally:
        connections.remove(message.agent_name)
        registry.remove(message.agent_name)
