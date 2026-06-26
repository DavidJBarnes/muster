"""Shared fakes and fixtures for the agent test-suite.

Every external boundary the agent touches has a deterministic stand-in here so
the whole register/heartbeat/job loop runs with no network, no ``claude``, and no
GPU. Fakes capture what was sent so tests assert on observable behaviour rather
than on internal calls.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import uuid4

import pytest

from muster_contracts import JobMessage, Origin
from muster_agent.config import AgentSettings
from muster_agent.transport import ClosedTransport, Transport


class FakeTransport:
    """A scriptable in-memory :class:`Transport`.

    ``incoming`` frames are handed out by ``recv`` in order; once drained ``recv``
    raises :class:`ClosedTransport` exactly as the real transport does at EOF.
    Sent frames are captured in ``sent`` and ``close`` flips ``closed``.
    """

    def __init__(self, incoming: list[str] | None = None) -> None:
        """Seed the receive queue and reset capture state."""
        self._incoming = list(incoming or [])
        self.sent: list[str] = []
        self.closed = False

    async def send(self, data: str) -> None:
        """Capture an outbound frame."""
        self.sent.append(data)

    async def recv(self) -> str:
        """Pop the next scripted frame, or raise :class:`ClosedTransport`."""
        if not self._incoming:
            raise ClosedTransport("drained")
        return self._incoming.pop(0)

    async def close(self) -> None:
        """Record that the transport was closed."""
        self.closed = True


class FakeRunner:
    """A :class:`Runner` that yields canned chunks, optionally then raising."""

    def __init__(
        self, chunks: list[str] | None = None, error: Exception | None = None
    ) -> None:
        """Configure the chunks to stream and an optional terminal error."""
        self._chunks = list(chunks or [])
        self._error = error
        self.instructions: list[str] = []

    async def run(self, instruction: str) -> AsyncIterator[str]:
        """Record the instruction, yield the canned chunks, then maybe raise."""
        self.instructions.append(instruction)
        for chunk in self._chunks:
            yield chunk
        if self._error is not None:
            raise self._error


def make_transport_factory(
    transports: list[Transport],
) -> tuple[object, list[str]]:
    """Build a transport factory that serves ``transports`` in order.

    Returns the async factory plus a list capturing each URL it was called with,
    so tests can assert reconnect behaviour. Raises ``IndexError`` if called more
    often than transports were supplied — a useful signal that a loop ran away.
    """
    urls: list[str] = []
    queue = list(transports)

    async def factory(url: str) -> Transport:
        urls.append(url)
        return queue.pop(0)

    return factory, urls


class FakeStream:
    """A minimal stand-in for an asyncio ``StreamReader``.

    Iterates the supplied byte lines and supports a one-shot ``read`` that drains
    whatever remains — enough for the runner's stdout-iteration and stderr-read.
    """

    def __init__(self, lines: list[bytes]) -> None:
        """Seed the stream with byte lines."""
        self._lines = list(lines)

    def __aiter__(self) -> "FakeStream":
        """Iterate over remaining lines."""
        return self

    async def __anext__(self) -> bytes:
        """Return the next line or stop iteration when drained."""
        if not self._lines:
            raise StopAsyncIteration
        return self._lines.pop(0)

    async def read(self) -> bytes:
        """Return and consume everything left in the stream."""
        data = b"".join(self._lines)
        self._lines = []
        return data


class FakeProcess:
    """A fake asyncio subprocess for driving :class:`AgentRunner`."""

    def __init__(
        self,
        stdout_lines: list[bytes] | None,
        returncode: int = 0,
        stderr_data: bytes = b"",
        has_stderr: bool = True,
    ) -> None:
        """Configure stdout lines, exit code and stderr contents."""
        self.stdout = None if stdout_lines is None else FakeStream(stdout_lines)
        self.stderr = FakeStream([stderr_data] if stderr_data else []) if has_stderr else None
        self._returncode = returncode
        self.returncode: int | None = None

    async def wait(self) -> int:
        """Report the configured exit code."""
        self.returncode = self._returncode
        return self._returncode


def make_spawn(process: FakeProcess) -> tuple[object, list[list[str]]]:
    """Build an injected spawn returning ``process`` and capturing argv lists."""
    calls: list[list[str]] = []

    async def spawn(args: list[str], cwd: str) -> FakeProcess:
        calls.append(args)
        return process

    return spawn, calls


@pytest.fixture
def settings() -> AgentSettings:
    """A fully-specified settings object independent of the host environment."""
    return AgentSettings(
        control_plane_url="ws://test/agent",
        agent_name="test-agent",
        heartbeat_interval_s=0.01,
        reconnect_min_s=0.01,
        reconnect_max_s=0.04,
        tool_candidates=["claude", "ffmpeg"],
        reachable_hosts=["3090.zero"],
        accounts=["aws:acct-1"],
        labels={"zone": "lab"},
        claude_bin="claude",
        workspace_root="/tmp",
    )


@pytest.fixture
def job() -> JobMessage:
    """A representative inbound job message."""
    return JobMessage(
        job_id=uuid4(),
        instruction="render a teapot",
        origin=Origin(connector="slack", channel="C1", thread="T1"),
    )
