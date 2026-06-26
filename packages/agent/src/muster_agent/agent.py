"""The agent: register, heartbeat, run jobs, and survive disconnects.

:class:`Agent` owns the lifecycle over a single control-plane socket. It is
constructed entirely from injected collaborators — a transport factory, a runner,
and a sleep function — so the full register/heartbeat/job loop is exercised in
tests with no network, no ``claude`` binary, and no GPU. Jobs are handled one at
a time (sequentially) in this pass.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from uuid import UUID

from muster_contracts import (
    AgentStatus,
    Capabilities,
    HeartbeatMessage,
    JobMessage,
    RegisterMessage,
    ResultMessage,
    ResultStatus,
    parse_message,
)

from muster_agent.config import AgentSettings
from muster_agent.log import get_logger
from muster_agent.runner import Runner
from muster_agent.transport import ClosedTransport, Transport, TransportFactory

logger = get_logger(__name__)

SleepCallable = Callable[[float], Awaitable[None]]
"""Async sleep used for heartbeat cadence and reconnect backoff; injectable."""


class Agent:
    """A long-lived agent that serves jobs from the control plane."""

    def __init__(
        self,
        settings: AgentSettings,
        capabilities: Capabilities,
        transport_factory: TransportFactory,
        runner: Runner,
        sleep: SleepCallable = asyncio.sleep,
    ) -> None:
        """Wire the agent to its settings and injected collaborators."""
        self._settings = settings
        self._capabilities = capabilities
        self._transport_factory = transport_factory
        self._runner = runner
        self._sleep = sleep
        self.status: AgentStatus = AgentStatus.IDLE
        self.current_job_id: UUID | None = None

    @property
    def _name(self) -> str:
        """The agent's reporting name."""
        return self._settings.agent_name

    async def register(self, t: Transport) -> None:
        """Announce identity and capabilities as the first frame on a socket."""
        message = RegisterMessage(
            agent_name=self._name, capabilities=self._capabilities
        )
        await t.send(message.model_dump_json())
        logger.info("registered", extra={"agent_name": self._name})

    async def heartbeat_once(self, t: Transport) -> None:
        """Send one heartbeat reflecting current status and job."""
        message = HeartbeatMessage(
            agent_name=self._name,
            status=self.status,
            current_job_id=self.current_job_id,
            detail=None,
        )
        await t.send(message.model_dump_json())

    async def _heartbeat_loop(self, t: Transport, stop: asyncio.Event) -> None:
        """Emit heartbeats on the configured interval until ``stop`` is set."""
        while not stop.is_set():
            await self.heartbeat_once(t)
            await self._sleep(self._settings.heartbeat_interval_s)

    async def handle_job(self, t: Transport, job: JobMessage) -> None:
        """Run one job, streaming partial results and a final outcome.

        Each runner chunk is forwarded as a PARTIAL result; on completion a final
        SUCCESS result carries the full concatenated text. Any runner failure is
        reported as a final ERROR result. Status and current job are always reset
        afterwards so the agent returns to IDLE regardless of outcome.
        """
        self.status = AgentStatus.WORKING
        self.current_job_id = job.job_id
        logger.info("job started", extra={"job_id": str(job.job_id)})
        chunks: list[str] = []
        try:
            async for chunk in self._runner.run(job.instruction):
                chunks.append(chunk)
                partial = ResultMessage(
                    job_id=job.job_id,
                    status=ResultStatus.PARTIAL,
                    content=chunk,
                    final=False,
                )
                await t.send(partial.model_dump_json())
            final = ResultMessage(
                job_id=job.job_id,
                status=ResultStatus.SUCCESS,
                content="".join(chunks),
                final=True,
            )
            await t.send(final.model_dump_json())
            logger.info("job succeeded", extra={"job_id": str(job.job_id)})
        except Exception as exc:  # noqa: BLE001 - any failure becomes an ERROR result
            error = ResultMessage(
                job_id=job.job_id,
                status=ResultStatus.ERROR,
                content=str(exc),
                final=True,
            )
            await t.send(error.model_dump_json())
            logger.error(
                "job failed",
                extra={"job_id": str(job.job_id), "error": str(exc)},
            )
        finally:
            self.status = AgentStatus.IDLE
            self.current_job_id = None

    async def _receive_loop(self, t: Transport, stop: asyncio.Event) -> None:
        """Dispatch inbound frames until the socket closes or ``stop`` is set.

        Job frames are handled sequentially; any other inbound message type is
        logged and ignored. Terminates on :class:`ClosedTransport`.
        """
        while not stop.is_set():
            try:
                frame = await t.recv()
            except ClosedTransport:
                logger.info("transport closed")
                break
            message = parse_message(frame)
            if isinstance(message, JobMessage):
                await self.handle_job(t, message)
            else:
                logger.info("ignoring inbound message", extra={"type": message.type})

    async def session(self, t: Transport) -> None:
        """Register, then run heartbeat and receive loops until either ends.

        The two loops share a local stop event; when the first finishes (almost
        always the receive loop on disconnect) the survivor is cancelled cleanly.
        """
        await self.register(t)
        stop = asyncio.Event()
        heartbeat = asyncio.create_task(self._heartbeat_loop(t, stop))
        receive = asyncio.create_task(self._receive_loop(t, stop))
        try:
            await asyncio.wait(
                {heartbeat, receive}, return_when=asyncio.FIRST_COMPLETED
            )
        finally:
            stop.set()
            for task in (heartbeat, receive):
                if not task.done():
                    task.cancel()
            await asyncio.gather(heartbeat, receive, return_exceptions=True)

    async def serve(self, stop: asyncio.Event) -> None:
        """Connect, serve a session, and reconnect with backoff until stopped.

        Connection failures are swallowed and logged so the loop survives; the
        backoff grows exponentially between ``reconnect_min_s`` and
        ``reconnect_max_s`` and resets after a session that actually connected.
        Setting ``stop`` breaks the loop.
        """
        backoff = self._settings.reconnect_min_s
        while not stop.is_set():
            try:
                transport = await self._transport_factory(
                    self._settings.control_plane_url
                )
            except Exception as exc:  # noqa: BLE001 - keep serving despite failures
                logger.warning("connect failed", extra={"error": str(exc)})
                await self._sleep(backoff)
                backoff = min(backoff * 2, self._settings.reconnect_max_s)
                continue
            try:
                await self.session(transport)
            except Exception as exc:  # noqa: BLE001 - a broken session is recoverable
                logger.error("session error", extra={"error": str(exc)})
            finally:
                await transport.close()
            backoff = self._settings.reconnect_min_s
            if stop.is_set():
                break
            await self._sleep(backoff)
