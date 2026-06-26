"""Execute job instructions through Claude Code headless and stream its text.

The agent depends only on the :class:`Runner` protocol, so jobs can be driven by
a fake that yields canned chunks in tests. :class:`ClaudeCodeRunner` is the real
implementation; it spawns the ``claude`` CLI in stream-json mode and yields the
assistant's text as it arrives. The subprocess spawn is injected so the runner is
fully testable without ``claude`` installed.

POC note: jobs run with ``--dangerously-skip-permissions`` by design; permission
gating is a later concern.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any, Protocol

from muster_agent.log import get_logger

logger = get_logger(__name__)


class RunnerError(Exception):
    """Raised when a job's underlying process fails (non-zero exit)."""


class Runner(Protocol):
    """Runs a free-text instruction, streaming assistant text chunks."""

    def run(self, instruction: str) -> AsyncIterator[str]:
        """Return an async iterator of assistant text chunks for ``instruction``."""
        ...


class _Process(Protocol):
    """The subset of an asyncio subprocess the runner relies on."""

    stdout: asyncio.StreamReader | None
    stderr: asyncio.StreamReader | None

    @property
    def returncode(self) -> int | None:
        """Exit status once the process has finished, else ``None``."""
        ...

    async def wait(self) -> int: ...


# Async spawn callable: given argv + working directory, return a live process
# with piped stdout/stderr. Injected so tests supply a fake process.
SpawnCallable = Callable[[list[str], str], Awaitable[_Process]]


async def _default_spawn(args: list[str], cwd: str) -> _Process:
    """Spawn ``args`` in ``cwd`` with stdout/stderr piped, via asyncio."""
    return await asyncio.create_subprocess_exec(
        *args,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )


def _extract_text(payload: dict[str, Any]) -> str | None:
    """Pull concatenated assistant text from one stream-json line, if any.

    Returns ``None`` for non-assistant frames (system/init, tool use, results)
    so the caller can skip them; returns the joined text of all text blocks for
    an assistant message.
    """
    if payload.get("type") != "assistant":
        return None
    message = payload.get("message")
    if not isinstance(message, dict):
        return None
    content = message.get("content")
    if not isinstance(content, list):
        return None
    parts = [
        block["text"]
        for block in content
        if isinstance(block, dict)
        and block.get("type") == "text"
        and isinstance(block.get("text"), str)
    ]
    if not parts:
        return None
    return "".join(parts)


class ClaudeCodeRunner:
    """Streams assistant output from a headless Claude Code invocation."""

    def __init__(
        self,
        claude_bin: str,
        workspace_root: str,
        spawn: SpawnCallable = _default_spawn,
    ) -> None:
        """Configure the binary, working directory and (injected) spawn callable."""
        self._claude_bin = claude_bin
        self._workspace_root = workspace_root
        self._spawn = spawn

    async def run(self, instruction: str) -> AsyncIterator[str]:
        """Spawn Claude Code for ``instruction`` and yield assistant text chunks.

        Reads stdout line by line, parsing each as a stream-json frame and
        yielding any assistant text; blank or unparseable lines are skipped
        defensively. On a non-zero exit the captured stderr is raised as a
        :class:`RunnerError`.
        """
        args = [
            self._claude_bin,
            "-p",
            instruction,
            "--output-format",
            "stream-json",
            "--verbose",
            "--dangerously-skip-permissions",
        ]
        process = await self._spawn(args, self._workspace_root)
        logger.info("runner started", extra={"bin": self._claude_bin})
        if process.stdout is not None:
            async for raw in process.stdout:
                line = raw.decode().strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    logger.debug("skipping unparseable line", extra={"line": line})
                    continue
                text = _extract_text(payload)
                if text is not None:
                    yield text
        returncode = await process.wait()
        if returncode != 0:
            stderr = b""
            if process.stderr is not None:
                stderr = await process.stderr.read()
            message = stderr.decode().strip()
            logger.error("runner failed", extra={"returncode": returncode})
            raise RunnerError(message or f"claude exited with {returncode}")
