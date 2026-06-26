"""Environment-driven settings for a Muster agent.

All knobs an operator may want to tune at deploy time live here as a single
``pydantic-settings`` model so they can be supplied through ``MUSTER_AGENT_*``
environment variables (or a process environment) without touching code. Nested
collections use the ``__`` delimiter, e.g. ``MUSTER_AGENT_LABELS__zone=homelab``.
"""

from __future__ import annotations

import socket

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def default_agent_name() -> str:
    """Return a hostname-derived default agent name.

    Factored out of the settings default so the derivation can be unit-tested
    independently of any environment or :class:`AgentSettings` construction.
    """
    return socket.gethostname()


class AgentSettings(BaseSettings):
    """Operator-facing configuration for one agent process.

    Values come from ``MUSTER_AGENT_``-prefixed environment variables; every
    field has a deployment-sensible default except ``control_plane_url`` and the
    hostname-derived ``agent_name``, so a minimal deployment only needs to point
    the agent at its control plane.
    """

    model_config = SettingsConfigDict(
        env_prefix="MUSTER_AGENT_",
        env_nested_delimiter="__",
    )

    control_plane_url: str = "ws://localhost:8000/agent"
    """WebSocket URL of the control plane the agent connects to as a client."""

    agent_name: str = Field(default_factory=default_agent_name)
    """Stable, unique name; defaults to this host's name."""

    heartbeat_interval_s: float = 10.0
    """Seconds between liveness heartbeats over the live socket."""

    reconnect_min_s: float = 1.0
    """Initial backoff after a dropped connection."""

    reconnect_max_s: float = 30.0
    """Ceiling for exponential reconnect backoff."""

    tool_candidates: list[str] = [
        "claude",
        "ffmpeg",
        "docker",
        "aws",
        "comfyui",
        "ollama",
    ]
    """Binaries to probe for on ``PATH`` and advertise as capabilities."""

    reachable_hosts: list[str] = []
    """Hosts this agent can operate on via SSH (declared, not probed)."""

    accounts: list[str] = []
    """Named credentials/accounts this agent holds (declared, not probed)."""

    labels: dict[str, str] = {}
    """Free-form key/value tags advertised in the capability manifest."""

    claude_bin: str = "claude"
    """Path or name of the Claude Code binary used by the runner."""

    workspace_root: str = "."
    """Working directory jobs execute in."""

    log_level: str = "INFO"
    """Root log level for the structured logger."""
