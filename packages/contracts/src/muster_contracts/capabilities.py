"""Capability descriptors advertised by agents at registration.

For now these models are *collected and transported only* — the control plane
stores a capability blob verbatim and no scheduling logic reads it yet. The shape
is therefore deliberately permissive (``extra="allow"``) so the manifest can grow
new fields without breaking older agents or the registry.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class GpuInfo(BaseModel):
    """Describes one GPU an agent can use directly or reach over SSH."""

    model_config = ConfigDict(extra="allow")

    name: str = Field(description="Human-readable GPU model, e.g. 'NVIDIA RTX 3090'.")
    vram_gb: float | None = Field(
        default=None, ge=0, description="Total video memory in GB, if known."
    )


class Capabilities(BaseModel):
    """The self-reported capability manifest an agent shares when it registers.

    The registry treats this as an opaque blob today; the typed fields below are a
    starting shape, and ``extra="allow"`` keeps the manifest forward-compatible so
    new capability kinds need no contract change.
    """

    model_config = ConfigDict(extra="allow")

    gpus: list[GpuInfo] = Field(
        default_factory=list, description="GPUs available locally on the agent's host."
    )
    tools: list[str] = Field(
        default_factory=list,
        description="Installed tools/binaries, e.g. 'comfyui', 'ffmpeg', 'aws-cli'.",
    )
    reachable_hosts: list[str] = Field(
        default_factory=list,
        description="Hosts the agent can operate on via SSH, e.g. '3090.zero'.",
    )
    accounts: list[str] = Field(
        default_factory=list,
        description="Named credentials/accounts held, e.g. 'aws:acct-1234'.",
    )
    labels: dict[str, str] = Field(
        default_factory=dict,
        description="Free-form key/value tags for anything not yet modeled.",
    )
