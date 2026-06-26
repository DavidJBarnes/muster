"""Probe the host for capabilities and assemble a capability manifest.

In this pass capabilities are *collected and reported only* — nothing here reads
or matches on them; that scheduling logic belongs to the control plane later.
Every external boundary (``nvidia-smi`` invocation, ``PATH`` lookup) is injected
so the probes run deterministically with no GPU and no real binaries present.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable

from muster_contracts import Capabilities, GpuInfo

from muster_agent.config import AgentSettings
from muster_agent.log import get_logger

logger = get_logger(__name__)

# Signature of the injected subprocess runner: takes an argv list, returns a
# completed process whose ``stdout`` is captured text.
RunCallable = Callable[[list[str]], "subprocess.CompletedProcess[str]"]
WhichCallable = Callable[[str], str | None]

_NVIDIA_SMI_ARGS = [
    "nvidia-smi",
    "--query-gpu=name,memory.total",
    "--format=csv,noheader,nounits",
]


def _default_run(args: list[str]) -> "subprocess.CompletedProcess[str]":
    """Run ``args`` capturing text stdout and raising on non-zero exit."""
    return subprocess.run(args, capture_output=True, text=True, check=True)


def probe_gpus(run: RunCallable = _default_run) -> list[GpuInfo]:
    """Return locally visible GPUs via ``nvidia-smi``, or ``[]`` if none.

    Parses the CSV rows of name + total memory (MiB) into :class:`GpuInfo`,
    converting memory to GB. Missing tooling or a non-zero exit yields an empty
    list rather than an error — a host without ``nvidia-smi`` simply has no GPUs
    to advertise.
    """
    try:
        completed = run(_NVIDIA_SMI_ARGS)
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        logger.debug("nvidia-smi unavailable", extra={"error": str(exc)})
        return []
    gpus: list[GpuInfo] = []
    for line in completed.stdout.splitlines():
        row = line.strip()
        if not row:
            continue
        name, _, mem = row.partition(",")
        vram_gb = float(mem.strip()) / 1024 if mem.strip() else None
        gpus.append(GpuInfo(name=name.strip(), vram_gb=vram_gb))
    return gpus


def probe_tools(
    candidates: list[str], which: WhichCallable = shutil.which
) -> list[str]:
    """Return the subset of ``candidates`` whose binary resolves on ``PATH``."""
    return [tool for tool in candidates if which(tool) is not None]


def probe_capabilities(
    settings: AgentSettings,
    *,
    run: RunCallable = _default_run,
    which: WhichCallable = shutil.which,
) -> Capabilities:
    """Assemble the agent's capability manifest from probes plus declarations.

    GPUs and tools are discovered on the host; reachable hosts, accounts and
    labels are taken verbatim from settings (declared, not probed in this pass).
    Injecting ``run``/``which`` keeps the assembly testable with no hardware.
    """
    capabilities = Capabilities(
        gpus=probe_gpus(run=run),
        tools=probe_tools(settings.tool_candidates, which=which),
        reachable_hosts=list(settings.reachable_hosts),
        accounts=list(settings.accounts),
        labels=dict(settings.labels),
    )
    logger.info(
        "probed capabilities",
        extra={
            "gpu_count": len(capabilities.gpus),
            "tools": capabilities.tools,
        },
    )
    return capabilities
