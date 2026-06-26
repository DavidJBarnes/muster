"""Tests for the Claude Code headless runner."""

from __future__ import annotations

import pytest

from muster_agent import runner as runner_mod
from muster_agent.runner import ClaudeCodeRunner, RunnerError

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


async def _collect(runner: ClaudeCodeRunner, instruction: str) -> list[str]:
    """Drain a runner's async stream into a list."""
    return [chunk async for chunk in runner.run(instruction)]


async def test_run_streams_assistant_text() -> None:
    """Assistant text blocks are yielded; junk and non-text frames are skipped."""
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
    runner = ClaudeCodeRunner("claude", "/work", spawn=spawn)

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


async def test_run_raises_on_nonzero_exit() -> None:
    """A non-zero exit raises RunnerError carrying stderr."""
    spawn, _ = make_spawn(FakeProcess([], returncode=1, stderr_data=b"boom"))
    runner = ClaudeCodeRunner("claude", "/work", spawn=spawn)
    with pytest.raises(RunnerError, match="boom"):
        await _collect(runner, "x")


async def test_run_nonzero_exit_without_stderr() -> None:
    """A non-zero exit with no stderr stream falls back to a default message."""
    spawn, _ = make_spawn(
        FakeProcess([], returncode=2, has_stderr=False)
    )
    runner = ClaudeCodeRunner("claude", "/work", spawn=spawn)
    with pytest.raises(RunnerError, match="claude exited with 2"):
        await _collect(runner, "x")


async def test_run_tolerates_missing_stdout() -> None:
    """A process without a stdout stream simply yields nothing."""
    spawn, _ = make_spawn(FakeProcess(None, returncode=0))
    runner = ClaudeCodeRunner("claude", "/work", spawn=spawn)
    assert await _collect(runner, "x") == []
