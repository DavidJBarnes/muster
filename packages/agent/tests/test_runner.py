"""Tests for the headless coding-agent runner (Claude and OpenCode backends)."""

from __future__ import annotations

import pytest

from muster_agent import runner as runner_mod
from muster_agent.config import AgentSettings, RunnerBackend
from muster_agent.runner import AgentRunner, RunnerError, build_runner

from conftest import FakeProcess, make_spawn


async def test_default_spawn_invokes_create_subprocess(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The default spawn delegates to asyncio with piped streams and cwd."""
    captured: dict[str, object] = {}

    async def fake_exec(*args: object, **kwargs: object) -> str:
        captured["args"] = args
        captured["kwargs"] = kwargs
        return "proc"

    monkeypatch.setattr(runner_mod.asyncio, "create_subprocess_exec", fake_exec)
    result = await runner_mod._default_spawn(["claude", "-p"], "/work")
    assert result == "proc"
    assert captured["args"] == ("claude", "-p")
    assert captured["kwargs"]["cwd"] == "/work"


async def _collect(runner: AgentRunner, instruction: str) -> list[str]:
    """Drain a runner's async stream into a list."""
    return [chunk async for chunk in runner.run(instruction)]


async def test_claude_streams_assistant_text() -> None:
    """The Claude backend yields assistant text, skipping junk and non-text frames."""
    lines = [
        b'{"type":"system","subtype":"init"}\n',
        b'{"type":"assistant","message":{"content":[{"type":"text","text":"Hello "}]}}\n',
        b"\n",
        b"not-json\n",
        b'{"type":"assistant","message":{"content":[{"type":"tool_use","id":"1"}]}}\n',
        b'{"type":"assistant","message":"oops"}\n',
        b'{"type":"assistant","message":{"content":"nope"}}\n',
        b'{"type":"assistant","message":{"content":[{"type":"text","text":"world"}]}}\n',
    ]
    spawn, calls = make_spawn(FakeProcess(lines, returncode=0))
    runner = AgentRunner(RunnerBackend.CLAUDE, "claude", "/work", spawn=spawn)

    assert await _collect(runner, "do it") == ["Hello ", "world"]
    assert calls[0] == [
        "claude",
        "-p",
        "do it",
        "--output-format",
        "stream-json",
        "--verbose",
        "--dangerously-skip-permissions",
    ]


async def test_claude_raises_on_nonzero_exit() -> None:
    """A non-zero exit raises RunnerError carrying stderr."""
    spawn, _ = make_spawn(FakeProcess([], returncode=1, stderr_data=b"boom"))
    runner = AgentRunner(RunnerBackend.CLAUDE, "claude", "/work", spawn=spawn)
    with pytest.raises(RunnerError, match="boom"):
        await _collect(runner, "x")


async def test_nonzero_exit_without_stderr() -> None:
    """A non-zero exit with no stderr stream falls back to a default message."""
    spawn, _ = make_spawn(FakeProcess([], returncode=2, has_stderr=False))
    runner = AgentRunner(RunnerBackend.CLAUDE, "claude", "/work", spawn=spawn)
    with pytest.raises(RunnerError, match="claude exited with 2"):
        await _collect(runner, "x")


async def test_tolerates_missing_stdout() -> None:
    """A process without a stdout stream simply yields nothing."""
    spawn, _ = make_spawn(FakeProcess(None, returncode=0))
    runner = AgentRunner(RunnerBackend.CLAUDE, "claude", "/work", spawn=spawn)
    assert await _collect(runner, "x") == []


async def test_opencode_streams_plain_text_lines() -> None:
    """The OpenCode backend yields each stdout line verbatim and runs ``run``."""
    lines = [b"Hello\n", b"world\n"]
    spawn, calls = make_spawn(FakeProcess(lines, returncode=0))
    runner = AgentRunner(RunnerBackend.OPENCODE, "opencode", "/work", spawn=spawn)

    assert await _collect(runner, "do it") == ["Hello\n", "world\n"]
    assert calls[0] == ["opencode", "run", "do it"]


async def test_opencode_raises_on_nonzero_exit() -> None:
    """The OpenCode backend surfaces a failing exit as a RunnerError."""
    spawn, _ = make_spawn(FakeProcess([], returncode=1, stderr_data=b"nope"))
    runner = AgentRunner(RunnerBackend.OPENCODE, "opencode", "/work", spawn=spawn)
    with pytest.raises(RunnerError, match="nope"):
        await _collect(runner, "x")


def test_build_runner_selects_claude_by_default() -> None:
    """With the default backend, build_runner makes a Claude-backed runner."""
    runner = build_runner(AgentSettings(workspace_root="/w"))
    assert runner._backend is RunnerBackend.CLAUDE
    assert runner._binary == "claude"
    assert runner._workspace_root == "/w"


def test_build_runner_selects_opencode() -> None:
    """When configured for opencode, build_runner uses the opencode binary."""
    runner = build_runner(
        AgentSettings(backend=RunnerBackend.OPENCODE, opencode_bin="oc")
    )
    assert runner._backend is RunnerBackend.OPENCODE
    assert runner._binary == "oc"
