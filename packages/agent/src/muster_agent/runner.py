"""Execute job instructions through a headless coding agent and stream its text.

The agent depends only on the :class:`Runner` protocol, so jobs can be driven by
a fake that yields canned chunks in tests. :class:`AgentRunner` is the real
implementation: it spawns whichever backend the box is configured for — Claude
Code or OpenCode — in headless mode and yields the assistant's text as it streams.
The two backends differ only in how they are invoked and how their stdout is
parsed; that variation is captured as data in :data:`_BACKENDS`, keeping a single
runner class. The subprocess spawn is injected so the runner is fully testable
with neither ``claude`` nor ``opencode`` installed.

POC note: the Claude backend runs with ``--dangerously-skip-permissions`` by
design; permission gating is a later concern.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol

from muster_agent.config import AgentSettings, RunnerBackend
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


def _claude_args(binary: str, instruction: str) -> list[str]:
    """Build the headless Claude Code argv for ``instruction``."""
    return [
        binary,
        "-p",
        instruction,
        "--output-format",
        "stream-json",
        "--verbose",
        "--dangerously-skip-permissions",
    ]


def _claude_parse(line: str) -> str | None:
    """Extract assistant text from one Claude stream-json line, skipping noise."""
    stripped = line.strip()
    if not stripped:
        return None
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        logger.debug("skipping unparseable line", extra={"line": stripped})
        return None
    return _extract_text(payload)


def _opencode_args(binary: str, instruction: str) -> list[str]:
    """Build the headless OpenCode argv for ``instruction``."""
    return [binary, "run", instruction]


def _opencode_parse(line: str) -> str | None:
    """Yield each OpenCode stdout line verbatim as assistant text.

    OpenCode's non-interactive ``run`` streams plain text, so the line (newline
    included) is the assistant output; concatenating chunks reconstructs it.
    """
    return line


@dataclass(frozen=True)
class _BackendSpec:
    """How to invoke and parse the output of one runner backend."""

    build_args: Callable[[str, str], list[str]]
    parse_line: Callable[[str], str | None]


_BACKENDS: dict[RunnerBackend, _BackendSpec] = {
    RunnerBackend.CLAUDE: _BackendSpec(_claude_args, _claude_parse),
    RunnerBackend.OPENCODE: _BackendSpec(_opencode_args, _opencode_parse),
}


class AgentRunner:
    """Streams assistant output from a headless coding-agent invocation.

    The configured :class:`~muster_agent.config.RunnerBackend` determines how the
    process is launched and how its stdout is turned into text chunks; the spawn
    plumbing and exit handling are shared across backends.
    """

    def __init__(
        self,
        backend: RunnerBackend,
        binary: str,
        workspace_root: str,
        spawn: SpawnCallable = _default_spawn,
    ) -> None:
        """Configure the backend, its binary, working directory and spawn callable."""
        self._backend = backend
        self._spec = _BACKENDS[backend]
        self._binary = binary
        self._workspace_root = workspace_root
        self._spawn = spawn

    async def run(self, instruction: str) -> AsyncIterator[str]:
        """Spawn the backend for ``instruction`` and yield assistant text chunks.

        Reads stdout line by line, handing each to the backend's parser and
        yielding whatever assistant text it returns (``None`` is skipped). On a
        non-zero exit the captured stderr is raised as a :class:`RunnerError`.
        """
        args = self._spec.build_args(self._binary, instruction)
        process = await self._spawn(args, self._workspace_root)
        logger.info(
            "runner started",
            extra={"backend": self._backend.value, "bin": self._binary},
        )
        if process.stdout is not None:
            async for raw in process.stdout:
                text = self._spec.parse_line(raw.decode())
                if text is not None:
                    yield text
        returncode = await process.wait()
        if returncode != 0:
            stderr = b""
            if process.stderr is not None:
                stderr = await process.stderr.read()
            message = stderr.decode().strip()
            logger.error("runner failed", extra={"returncode": returncode})
            raise RunnerError(message or f"{self._binary} exited with {returncode}")


def build_runner(settings: AgentSettings) -> AgentRunner:
    """Construct the runner for the backend selected in ``settings``."""
    binary = (
        settings.opencode_bin
        if settings.backend is RunnerBackend.OPENCODE
        else settings.claude_bin
    )
    return AgentRunner(settings.backend, binary, settings.workspace_root)
