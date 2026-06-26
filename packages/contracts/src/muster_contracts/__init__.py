"""Muster wire contracts: capability manifest, messages, and ingress interface.

This package is pure (Pydantic models + ABCs, no I/O) and is the single shared
dependency every other Muster component compiles against.
"""

from muster_contracts.capabilities import Capabilities, GpuInfo
from muster_contracts.ingress import (
    IncomingInstruction,
    Ingress,
    InstructionHandler,
    OutgoingUpdate,
)
from muster_contracts.messages import (
    AgentStatus,
    HeartbeatMessage,
    JobMessage,
    Message,
    Origin,
    RegisterMessage,
    ResultMessage,
    ResultStatus,
    parse_message,
)

__all__ = [
    "AgentStatus",
    "Capabilities",
    "GpuInfo",
    "HeartbeatMessage",
    "IncomingInstruction",
    "Ingress",
    "InstructionHandler",
    "JobMessage",
    "Message",
    "Origin",
    "OutgoingUpdate",
    "RegisterMessage",
    "ResultMessage",
    "ResultStatus",
    "parse_message",
]
