"""Tests for environment-driven agent settings."""

from __future__ import annotations

import pytest

from muster_agent.config import AgentSettings, default_agent_name


def test_default_agent_name_uses_hostname(monkeypatch: pytest.MonkeyPatch) -> None:
    """The helper derives the name from the socket hostname."""
    monkeypatch.setattr("muster_agent.config.socket.gethostname", lambda: "box-7")
    assert default_agent_name() == "box-7"


def test_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unset fields fall back to their declared defaults."""
    monkeypatch.setattr("muster_agent.config.socket.gethostname", lambda: "atlas")
    settings = AgentSettings()
    assert settings.agent_name == "atlas"
    assert settings.heartbeat_interval_s == 10.0
    assert settings.reconnect_min_s == 1.0
    assert settings.reconnect_max_s == 30.0
    assert "claude" in settings.tool_candidates
    assert settings.reachable_hosts == []
    assert settings.accounts == []
    assert settings.labels == {}
    assert settings.claude_bin == "claude"
    assert settings.workspace_root == "."
    assert settings.log_level == "INFO"


def test_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prefixed environment variables override defaults, including nested labels."""
    monkeypatch.setenv("MUSTER_AGENT_CONTROL_PLANE_URL", "ws://hub/agent")
    monkeypatch.setenv("MUSTER_AGENT_AGENT_NAME", "nova")
    monkeypatch.setenv("MUSTER_AGENT_HEARTBEAT_INTERVAL_S", "2.5")
    monkeypatch.setenv("MUSTER_AGENT_LABELS__zone", "homelab")
    settings = AgentSettings()
    assert settings.control_plane_url == "ws://hub/agent"
    assert settings.agent_name == "nova"
    assert settings.heartbeat_interval_s == 2.5
    assert settings.labels == {"zone": "homelab"}
