"""Tests for the console-script entrypoint shim."""

from __future__ import annotations

from collections.abc import Coroutine
from typing import Any

import pytest

from muster_contracts import Capabilities
from muster_agent import main as main_module
from muster_agent.config import AgentSettings


def test_main_wires_and_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    """main composes real collaborators and hands a coroutine to asyncio.run."""
    started: dict[str, Any] = {}

    monkeypatch.setattr(main_module, "setup_logging", lambda level: None)
    monkeypatch.setattr(
        main_module, "AgentSettings", lambda: AgentSettings(agent_name="m")
    )
    monkeypatch.setattr(
        main_module, "probe_capabilities", lambda settings: Capabilities()
    )

    def fake_run(coro: Coroutine[Any, Any, None]) -> None:
        started["ran"] = True
        coro.close()  # we are not driving the loop; avoid an un-awaited warning

    monkeypatch.setattr(main_module.asyncio, "run", fake_run)

    main_module.main()
    assert started["ran"] is True
