"""Tests for the WebSocket transport adapter and connect factory."""

from __future__ import annotations

import pytest
from websockets.exceptions import ConnectionClosed

from muster_agent.transport import (
    ClosedTransport,
    WebsocketsTransport,
    connect_websocket,
)


class _FakeConnection:
    """A scriptable stand-in for a websockets client connection."""

    def __init__(self, frames: list[str | bytes] | None = None) -> None:
        self._frames = list(frames or [])
        self.sent: list[str] = []
        self.closed = False

    async def send(self, message: str) -> None:
        self.sent.append(message)

    async def recv(self) -> str | bytes:
        if not self._frames:
            raise ConnectionClosed(None, None)
        return self._frames.pop(0)

    async def close(self) -> None:
        self.closed = True


async def test_send_delegates() -> None:
    """send forwards the text frame to the underlying connection."""
    conn = _FakeConnection()
    await WebsocketsTransport(conn).send("hi")
    assert conn.sent == ["hi"]


async def test_recv_passes_text() -> None:
    """A text frame is returned unchanged."""
    transport = WebsocketsTransport(_FakeConnection(["frame"]))
    assert await transport.recv() == "frame"


async def test_recv_normalizes_bytes() -> None:
    """A binary frame is decoded to str."""
    transport = WebsocketsTransport(_FakeConnection([b"bytes-frame"]))
    assert await transport.recv() == "bytes-frame"


async def test_recv_raises_closed_transport() -> None:
    """A connection-closed error surfaces as ClosedTransport."""
    transport = WebsocketsTransport(_FakeConnection([]))
    with pytest.raises(ClosedTransport):
        await transport.recv()


async def test_close_delegates() -> None:
    """close closes the underlying connection."""
    conn = _FakeConnection()
    await WebsocketsTransport(conn).close()
    assert conn.closed is True


async def test_connect_websocket_wraps_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The factory dials the real connect and wraps the result."""
    conn = _FakeConnection(["x"])

    async def fake_connect(url: str) -> _FakeConnection:
        assert url == "ws://hub/agent"
        return conn

    monkeypatch.setattr(
        "websockets.asyncio.client.connect", fake_connect, raising=True
    )
    transport = await connect_websocket("ws://hub/agent")
    assert isinstance(transport, WebsocketsTransport)
    assert await transport.recv() == "x"
