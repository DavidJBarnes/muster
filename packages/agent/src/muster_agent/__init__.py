"""Muster agent: a headless Claude Code worker for the control-plane fleet.

Re-exports the package's public surface so callers can import collaborators from
one place regardless of internal module layout.
"""

from muster_agent.agent import Agent
from muster_agent.capabilities import probe_capabilities
from muster_agent.config import AgentSettings
from muster_agent.log import get_logger, setup_logging
from muster_agent.runner import ClaudeCodeRunner, Runner
from muster_agent.transport import Transport, connect_websocket

__all__ = [
    "Agent",
    "AgentSettings",
    "ClaudeCodeRunner",
    "Runner",
    "Transport",
    "connect_websocket",
    "get_logger",
    "probe_capabilities",
    "setup_logging",
]
