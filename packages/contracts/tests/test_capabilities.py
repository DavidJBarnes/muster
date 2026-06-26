"""Tests for the capability manifest models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from muster_contracts.capabilities import Capabilities, GpuInfo


def test_gpu_info_minimal() -> None:
    """A GPU needs only a name; vram defaults to None."""
    gpu = GpuInfo(name="NVIDIA RTX 3090")
    assert gpu.name == "NVIDIA RTX 3090"
    assert gpu.vram_gb is None


def test_gpu_info_with_vram() -> None:
    """vram_gb is captured when supplied."""
    gpu = GpuInfo(name="NVIDIA RTX 2070", vram_gb=8)
    assert gpu.vram_gb == 8


def test_gpu_info_rejects_negative_vram() -> None:
    """Negative video memory is invalid."""
    with pytest.raises(ValidationError):
        GpuInfo(name="bad", vram_gb=-1)


def test_gpu_info_allows_extra_fields() -> None:
    """Unknown fields are preserved for forward compatibility."""
    gpu = GpuInfo(name="NVIDIA RTX 3090", driver="555.42")
    assert gpu.model_dump()["driver"] == "555.42"


def test_capabilities_defaults_are_empty() -> None:
    """An empty manifest yields empty collections, not None."""
    caps = Capabilities()
    assert caps.gpus == []
    assert caps.tools == []
    assert caps.reachable_hosts == []
    assert caps.accounts == []
    assert caps.labels == {}


def test_capabilities_populated() -> None:
    """A populated manifest round-trips its typed fields."""
    caps = Capabilities(
        gpus=[GpuInfo(name="NVIDIA RTX 3090", vram_gb=24)],
        tools=["comfyui", "ffmpeg"],
        reachable_hosts=["3090.zero"],
        accounts=["aws:acct-1234"],
        labels={"zone": "homelab"},
    )
    assert caps.gpus[0].vram_gb == 24
    assert "ffmpeg" in caps.tools
    assert caps.reachable_hosts == ["3090.zero"]
    assert caps.labels["zone"] == "homelab"


def test_capabilities_allows_extra_fields() -> None:
    """The manifest accepts not-yet-modeled capability kinds."""
    caps = Capabilities(network_bandwidth_gbps=10)
    assert caps.model_dump()["network_bandwidth_gbps"] == 10
