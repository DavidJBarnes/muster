"""Tests for host capability probing and manifest assembly."""

from __future__ import annotations

import subprocess

import pytest

from muster_agent import capabilities as capmod
from muster_agent.capabilities import (
    probe_capabilities,
    probe_gpus,
    probe_tools,
)
from muster_agent.config import AgentSettings


def test_default_run_invokes_subprocess(monkeypatch: pytest.MonkeyPatch) -> None:
    """The default runner shells out with captured text and check=True."""
    captured: dict[str, object] = {}

    def fake_run(args: list[str], **kwargs: object) -> "subprocess.CompletedProcess[str]":
        captured["args"] = args
        captured.update(kwargs)
        return subprocess.CompletedProcess(args, 0, stdout="out")

    monkeypatch.setattr(capmod.subprocess, "run", fake_run)
    result = capmod._default_run(["nvidia-smi"])
    assert result.stdout == "out"
    assert captured["check"] is True
    assert captured["capture_output"] is True
    assert captured["text"] is True


def _completed(stdout: str) -> "subprocess.CompletedProcess[str]":
    """Build a fake completed process carrying ``stdout``."""
    return subprocess.CompletedProcess(args=["nvidia-smi"], returncode=0, stdout=stdout)


def test_probe_gpus_parses_rows() -> None:
    """Each CSV row becomes a GpuInfo with MiB converted to GB."""
    out = "NVIDIA RTX 3090, 24576\nNVIDIA RTX 2070, 8192\n\n"

    def run(args: list[str]) -> "subprocess.CompletedProcess[str]":
        return _completed(out)

    gpus = probe_gpus(run=run)
    assert [g.name for g in gpus] == ["NVIDIA RTX 3090", "NVIDIA RTX 2070"]
    assert gpus[0].vram_gb == 24.0


def test_probe_gpus_handles_missing_memory() -> None:
    """A row without a memory column yields a GPU with unknown vram."""

    def run(args: list[str]) -> "subprocess.CompletedProcess[str]":
        return _completed("Tesla T4\n")

    gpus = probe_gpus(run=run)
    assert gpus[0].name == "Tesla T4"
    assert gpus[0].vram_gb is None


def test_probe_gpus_missing_binary() -> None:
    """A missing nvidia-smi yields an empty list, never an error."""

    def run(args: list[str]) -> "subprocess.CompletedProcess[str]":
        raise FileNotFoundError("nvidia-smi")

    assert probe_gpus(run=run) == []


def test_probe_gpus_nonzero_exit() -> None:
    """A non-zero exit yields an empty list."""

    def run(args: list[str]) -> "subprocess.CompletedProcess[str]":
        raise subprocess.CalledProcessError(1, args)

    assert probe_gpus(run=run) == []


def test_probe_tools_filters_to_found() -> None:
    """Only candidates whose binary resolves are kept."""
    present = {"ffmpeg", "docker"}

    def which(name: str) -> str | None:
        return f"/usr/bin/{name}" if name in present else None

    assert probe_tools(["ffmpeg", "claude", "docker"], which=which) == [
        "ffmpeg",
        "docker",
    ]


def test_probe_capabilities_assembles_manifest() -> None:
    """Probed GPUs/tools combine with declared hosts/accounts/labels."""
    settings = AgentSettings(
        tool_candidates=["ffmpeg", "claude"],
        reachable_hosts=["3090.zero"],
        accounts=["aws:acct-1"],
        labels={"zone": "lab"},
    )

    def run(args: list[str]) -> "subprocess.CompletedProcess[str]":
        return _completed("NVIDIA RTX 3090, 24576\n")

    def which(name: str) -> str | None:
        return "/usr/bin/ffmpeg" if name == "ffmpeg" else None

    caps = probe_capabilities(settings, run=run, which=which)
    assert caps.gpus[0].name == "NVIDIA RTX 3090"
    assert caps.tools == ["ffmpeg"]
    assert caps.reachable_hosts == ["3090.zero"]
    assert caps.accounts == ["aws:acct-1"]
    assert caps.labels == {"zone": "lab"}
