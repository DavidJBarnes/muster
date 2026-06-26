"""WebSocket transport abstraction for the agent's single control-plane socket.

The agent talks to exactly one transport at a time. Everything above this module
depends only on the :class:`Transport` protocol, never on ``websockets`` itself,
so the whole register/heartbeat/job loop can be driven by a fake in tests. The
real ``websockets.connect`` call is deliberately isolated to one factory function
here.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Protocol

from websockets.exceptions import ConnectionClosed

from muster_agent.log import get_logger

logger = get_logger(__name__)


class ClosedTransport(Exception):
    """Raised by :meth:`Transport.recv` once the connection is gone.

    The agent's receive loop treats this as its normal termination signal rather
    than an error to propagate.
    """


class Transport(Protocol):
    """A bidirectional, text-framed connection to the control plane."""

    async def send(self, data: str) -> None:
        """Send one text frame."""
        ...

    async def recv(self) -> str:
        """Receive the next frame as text, or raise :class:`ClosedTransport`."""
        ...

    async def close(self) -> None:
        """Close the connection; idempotent at the call site."""
        ...


# A websockets client connection exposes the async ``send``/``recv``/``close``
# methods this transport wraps; typed structurally to avoid pinning a version.
class _WsConnection(Protocol):
    async def send(self, message: str) -> None: ...
    async def recv(self) -> str | bytes: ...
    async def close(self) -> None: ...


class WebsocketsTransport:
    """Adapts a ``websockets`` client connection to the :class:`Transport` API.

    Normalizes binary frames to ``str`` on receive and translates the library's
    connection-closed exception into :class:`ClosedTransport` so callers depend
    only on this module's contract.
    """

    def __init__(self, connection: _WsConnection) -> None:
        """Wrap an already-open websockets client ``connection``."""
        self._connection = connection

    async def send(self, data: str) -> None:
        """Send ``data`` as a text frame."""
        await self._connection.send(data)

    async def recv(self) -> str:
        """Return the next frame as text, raising :class:`ClosedTransport` when shut."""
        try:
            frame = await self._connection.recv()
        except ConnectionClosed as exc:
            raise ClosedTransport(str(exc)) from exc
        if isinstance(frame, bytes):
            return frame.decode()
        return frame

    async def close(self) -> None:
        """Close the underlying connection."""
        await self._connection.close()


TransportFactory = Callable[[str], Awaitable[Transport]]
"""Async factory that opens a :class:`Transport` for a control-plane URL."""


async def connect_websocket(url: str) -> Transport:
    """Open a real WebSocket client connection to ``url``.

    This is the only place the concrete ``websockets`` library is dialed; tests
    substitute their own factory everywhere this would otherwise be used.
    """
    from websockets.asyncio.client import connect

    connection = await connect(url)
    logger.info("connected", extra={"url": url})
    return WebsocketsTransport(connection)
