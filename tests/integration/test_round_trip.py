"""End-to-end: a real agent serves a job from a live control plane.

This is the genuine article — no fakes on the wire. A real ``muster-controlplane``
runs under uvicorn on an ephemeral port; the real :class:`Agent` opens its real
``websockets`` client to it, registers, and serves a dispatched job. The only
stand-in is the job *runner* (a ``FakeRunner`` standing in for Claude Code), so
the test needs neither the ``claude`` binary nor a GPU, yet exercises the full
register → dispatch → stream-results loop across a real socket.
"""

from __future__ import annotations

import asyncio
import contextlib
import socket
from collections.abc import AsyncIterator

import httpx
import uvicorn

from muster_agent.agent import Agent
from muster_agent.config import AgentSettings
from muster_agent.transport import connect_websocket
from muster_contracts import Capabilities
from muster_controlplane.app import create_app


class FakeRunner:
    """A runner that streams canned chunks in place of Claude Code."""

    def __init__(self, chunks: list[str]) -> None:
        self._chunks = chunks

    async def run(self, instruction: str) -> AsyncIterator[str]:
        """Yield the canned chunks, ignoring the instruction."""
        for chunk in self._chunks:
            yield chunk


def _free_port() -> int:
    """Reserve and release an ephemeral localhost port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


async def _await_true(predicate, *, timeout: float = 5.0, step: float = 0.02):  # type: ignore[no-untyped-def]
    """Poll an async predicate until truthy or the timeout elapses."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        value = await predicate()
        if value:
            return value
        await asyncio.sleep(step)
    raise AssertionError("condition not met within timeout")


async def test_agent_serves_job_from_live_control_plane() -> None:
    """The agent registers, receives a dispatched job, and streams results home."""
    port = _free_port()
    app = create_app()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    server_task = asyncio.create_task(server.serve())

    agent = Agent(
        AgentSettings(
            control_plane_url=f"ws://127.0.0.1:{port}/agent",
            agent_name="atlas",
            heartbeat_interval_s=0.05,
        ),
        Capabilities(tools=["claude"]),
        connect_websocket,
        FakeRunner(["Hello ", "world"]),
    )
    stop = asyncio.Event()
    serve_task = asyncio.create_task(agent.serve(stop))

    try:
        await _await_true(lambda: _ready(server))

        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}") as client:
            # The agent must register before a job can be dispatched to it.
            await _await_true(lambda: _agent_listed(client, "atlas"))

            submitted = await client.post(
                "/jobs",
                json={
                    "instruction": "greet the world",
                    "origin": {"connector": "test", "channel": "c", "thread": "t"},
                },
            )
            assert submitted.status_code == 200
            job_id = submitted.json()["job_id"]

            data = await _await_true(lambda: _job_final(client, job_id))

        contents = [r["content"] for r in data["results"]]
        assert contents == ["Hello ", "world", "Hello world"]
        statuses = [r["status"] for r in data["results"]]
        assert statuses == ["partial", "partial", "success"]
    finally:
        stop.set()
        serve_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await serve_task
        server.should_exit = True
        await server_task


async def _ready(server: uvicorn.Server) -> bool:
    """Whether the uvicorn server has finished starting up."""
    return bool(server.started)


async def _agent_listed(client: httpx.AsyncClient, name: str) -> bool:
    """Whether ``name`` appears in the hub's registered-agent list."""
    response = await client.get("/agents")
    return any(a["name"] == name for a in response.json())


async def _job_final(client: httpx.AsyncClient, job_id: str) -> dict | None:  # type: ignore[type-arg]
    """Return the job payload once it has a terminal result, else ``None``."""
    response = await client.get(f"/jobs/{job_id}")
    payload = response.json()
    return payload if payload["final"] else None
