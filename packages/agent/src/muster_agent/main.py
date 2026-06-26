"""Console-script entrypoint: wire real collaborators and run the agent.

This shim is intentionally thin — it constructs production collaborators (the
real WebSocket factory and Claude Code runner), installs signal handlers, and
hands off to :meth:`Agent.serve`. All testable logic lives in the modules it
composes, so this function carries the package's only coverage pragma.
"""

from __future__ import annotations

import asyncio
import signal

from muster_agent.agent import Agent
from muster_agent.capabilities import probe_capabilities
from muster_agent.config import AgentSettings
from muster_agent.log import get_logger, setup_logging
from muster_agent.runner import ClaudeCodeRunner
from muster_agent.transport import connect_websocket


def main() -> None:  # pragma: no cover
    """Load settings, probe capabilities, and serve until signalled to stop."""
    settings = AgentSettings()
    setup_logging(settings.log_level)
    logger = get_logger(__name__)

    capabilities = probe_capabilities(settings)
    runner = ClaudeCodeRunner(settings.claude_bin, settings.workspace_root)
    agent = Agent(settings, capabilities, connect_websocket, runner)

    async def run() -> None:
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, stop.set)
        logger.info("agent starting", extra={"agent_name": settings.agent_name})
        await agent.serve(stop)

    asyncio.run(run())
