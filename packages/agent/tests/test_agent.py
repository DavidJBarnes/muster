"""Tests for the agent lifecycle: register, heartbeat, jobs, session, serve."""

from __future__ import annotations

import asyncio

import pytest

from muster_contracts import (
    AgentStatus,
    Capabilities,
    HeartbeatMessage,
    RegisterMessage,
    ResultMessage,
    ResultStatus,
    parse_message,
)
from muster_contracts.messages import JobMessage
from muster_agent.agent import Agent
from muster_agent.config import AgentSettings
from muster_agent.runner import RunnerError

from conftest import (
    FakeRunner,
    FakeTransport,
    make_transport_factory,
)


def _agent(settings: AgentSettings, runner: object, **kw: object) -> Agent:
    """Build an Agent with a throwaway factory and the given runner."""
    factory, _ = make_transport_factory([])
    return Agent(settings, Capabilities(), factory, runner, **kw)  # type: ignore[arg-type]


async def test_register_sends_register_message(settings: AgentSettings) -> None:
    """Registration sends a single RegisterMessage with name and capabilities."""
    agent = _agent(settings, FakeRunner())
    transport = FakeTransport()
    await agent.register(transport)
    message = parse_message(transport.sent[0])
    assert isinstance(message, RegisterMessage)
    assert message.agent_name == "test-agent"
    assert isinstance(message.capabilities, Capabilities)


async def test_heartbeat_once_reflects_state(settings: AgentSettings, job: JobMessage) -> None:
    """A heartbeat carries the agent's current status and job id."""
    agent = _agent(settings, FakeRunner())
    agent.status = AgentStatus.WORKING
    agent.current_job_id = job.job_id
    transport = FakeTransport()
    await agent.heartbeat_once(transport)
    message = parse_message(transport.sent[0])
    assert isinstance(message, HeartbeatMessage)
    assert message.status == AgentStatus.WORKING
    assert message.current_job_id == job.job_id


async def test_handle_job_streams_and_finalizes(
    settings: AgentSettings, job: JobMessage
) -> None:
    """Each chunk is a PARTIAL; completion sends a final SUCCESS with all text."""
    agent = _agent(settings, FakeRunner(chunks=["a", "b"]))
    transport = FakeTransport()
    await agent.handle_job(transport, job)
    messages = [parse_message(f) for f in transport.sent]
    assert [m.status for m in messages] == [
        ResultStatus.PARTIAL,
        ResultStatus.PARTIAL,
        ResultStatus.SUCCESS,
    ]
    assert all(isinstance(m, ResultMessage) for m in messages)
    final = messages[-1]
    assert isinstance(final, ResultMessage)
    assert final.content == "ab"
    assert final.final is True
    assert agent.status == AgentStatus.IDLE
    assert agent.current_job_id is None


async def test_handle_job_marks_working_during_run(
    settings: AgentSettings, job: JobMessage
) -> None:
    """While the runner streams, the agent reports WORKING on the job."""
    seen: dict[str, object] = {}

    class _Recorder:
        async def run(self, instruction: str):  # type: ignore[no-untyped-def]
            seen["status"] = agent.status
            seen["job"] = agent.current_job_id
            yield "x"

    agent = _agent(settings, _Recorder())
    await agent.handle_job(FakeTransport(), job)
    assert seen["status"] == AgentStatus.WORKING
    assert seen["job"] == job.job_id


async def test_handle_job_reports_error(
    settings: AgentSettings, job: JobMessage
) -> None:
    """A runner failure becomes a single final ERROR result, and status resets."""
    agent = _agent(settings, FakeRunner(error=RunnerError("nope")))
    transport = FakeTransport()
    await agent.handle_job(transport, job)
    message = parse_message(transport.sent[-1])
    assert isinstance(message, ResultMessage)
    assert message.status == ResultStatus.ERROR
    assert message.content == "nope"
    assert message.final is True
    assert agent.status == AgentStatus.IDLE
    assert agent.current_job_id is None


async def test_receive_loop_dispatches_job(
    settings: AgentSettings, job: JobMessage
) -> None:
    """A job frame is parsed and handled before the closed socket ends the loop."""
    agent = _agent(settings, FakeRunner(chunks=["hi"]))
    transport = FakeTransport([job.model_dump_json()])
    stop = asyncio.Event()
    await agent._receive_loop(transport, stop)
    statuses = [parse_message(f).status for f in transport.sent]
    assert statuses == [ResultStatus.PARTIAL, ResultStatus.SUCCESS]


async def test_receive_loop_ignores_non_job(settings: AgentSettings) -> None:
    """A non-job inbound frame is ignored, producing no results."""
    heartbeat = HeartbeatMessage(agent_name="peer", status=AgentStatus.IDLE)
    agent = _agent(settings, FakeRunner())
    transport = FakeTransport([heartbeat.model_dump_json()])
    stop = asyncio.Event()
    await agent._receive_loop(transport, stop)
    assert transport.sent == []


async def test_receive_loop_exits_when_stopped(settings: AgentSettings) -> None:
    """A pre-set stop event prevents the loop from ever reading."""
    agent = _agent(settings, FakeRunner())
    transport = FakeTransport([HeartbeatMessage(agent_name="p", status=AgentStatus.IDLE).model_dump_json()])
    stop = asyncio.Event()
    stop.set()
    await agent._receive_loop(transport, stop)
    assert transport.sent == []


async def test_heartbeat_loop_runs_until_stopped(settings: AgentSettings) -> None:
    """The loop beats once, then the injected sleep sets stop to end it."""
    stop = asyncio.Event()

    async def sleep(_: float) -> None:
        stop.set()

    agent = _agent(settings, FakeRunner(), sleep=sleep)
    transport = FakeTransport()
    await agent._heartbeat_loop(transport, stop)
    assert len(transport.sent) == 1
    assert parse_message(transport.sent[0]).status == AgentStatus.IDLE


async def test_session_registers_then_serves_until_disconnect(
    settings: AgentSettings, job: JobMessage
) -> None:
    """A session registers first, handles a job, and ends when the socket closes."""
    agent = _agent(settings, FakeRunner(chunks=["done"]))
    transport = FakeTransport([job.model_dump_json()])
    await agent.session(transport)
    first = parse_message(transport.sent[0])
    assert isinstance(first, RegisterMessage)
    kinds = {type(parse_message(f)) for f in transport.sent}
    assert ResultMessage in kinds


# The serve() tests stub out session() so the reconnect/backoff machinery is
# exercised in isolation, free of the concurrent heartbeat loop (whose own use of
# the shared injected sleep would otherwise muddy the backoff assertions). The
# real session() concurrency is covered by the test above.


def _serve_agent(
    settings: AgentSettings,
    factory: object,
    sleep: object,
    session: object,
) -> Agent:
    """Build an agent for serve() tests with session() replaced by a stub."""
    agent = Agent(settings, Capabilities(), factory, FakeRunner(), sleep=sleep)  # type: ignore[arg-type]
    agent.session = session  # type: ignore[method-assign, assignment]
    return agent


async def test_serve_breaks_after_session_when_stopped(
    settings: AgentSettings,
) -> None:
    """When stop is set during a session, serve closes and breaks without sleeping."""
    stop = asyncio.Event()
    transport = FakeTransport()
    factory, urls = make_transport_factory([transport])
    slept: list[float] = []

    async def sleep(d: float) -> None:
        slept.append(d)

    async def session(t: object) -> None:
        stop.set()

    agent = _serve_agent(settings, factory, sleep, session)
    await agent.serve(stop)
    assert urls == ["ws://test/agent"]
    assert transport.closed is True
    assert slept == []


async def test_serve_retries_after_connect_failure(
    settings: AgentSettings,
) -> None:
    """A failed connect backs off, then a later connect serves a session."""
    stop = asyncio.Event()
    ok = FakeTransport([])
    calls = {"n": 0}

    async def factory(url: str) -> object:
        calls["n"] += 1
        if calls["n"] == 1:
            raise ConnectionError("refused")
        return ok

    slept: list[float] = []

    async def sleep(d: float) -> None:
        slept.append(d)
        if len(slept) >= 2:
            stop.set()

    async def session(t: object) -> None:
        return None

    agent = _serve_agent(settings, factory, sleep, session)
    await agent.serve(stop)
    assert calls["n"] == 2
    assert slept == [0.01, 0.01]
    assert ok.closed is True


async def test_serve_caps_backoff(settings: AgentSettings) -> None:
    """Repeated connect failures grow backoff up to the configured ceiling."""
    stop = asyncio.Event()

    async def factory(url: str) -> object:
        raise ConnectionError("down")

    slept: list[float] = []

    async def sleep(d: float) -> None:
        slept.append(d)
        if len(slept) >= 4:
            stop.set()

    async def session(t: object) -> None:  # pragma: no cover - never reached
        return None

    agent = _serve_agent(settings, factory, sleep, session)
    await agent.serve(stop)
    assert slept == [0.01, 0.02, 0.04, 0.04]


async def test_serve_survives_session_error(settings: AgentSettings) -> None:
    """An exception raised inside a session is logged and the transport closed."""
    stop = asyncio.Event()
    transport = FakeTransport()
    factory, _ = make_transport_factory([transport])

    async def sleep(d: float) -> None:
        stop.set()

    async def session(t: object) -> None:
        raise RuntimeError("boom")

    agent = _serve_agent(settings, factory, sleep, session)
    await agent.serve(stop)
    assert transport.closed is True
