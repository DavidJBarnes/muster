"""Wire messages exchanged over the Muster control-plane WebSocket surfaces.

Four envelope types travel the wire, each tagged by a ``type`` discriminator so a
receiver can parse a raw frame into the correct model with :func:`parse_message`:

* :class:`RegisterMessage` — agent announces itself + capabilities (agent to control plane)
* :class:`HeartbeatMessage` — periodic liveness + status (agent to control plane)
* :class:`JobMessage` — an instruction to execute (control plane to agent)
* :class:`ResultMessage` — output for a job, streamed or final (agent to control plane)

The models are pure and perform no I/O; transport and routing live elsewhere.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, Any, Literal, Union
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, TypeAdapter

from muster_contracts.capabilities import Capabilities


def _utcnow() -> datetime:
    """Return the current timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc)


class AgentStatus(str, Enum):
    """Status an agent reports about itself in a heartbeat.

    The control plane derives DOWN/STALE from missed heartbeats; agents never
    report those themselves.
    """

    IDLE = "idle"
    WORKING = "working"
    BLOCKED = "blocked"


class ResultStatus(str, Enum):
    """Outcome carried by a :class:`ResultMessage`."""

    SUCCESS = "success"
    ERROR = "error"
    PARTIAL = "partial"  # a streamed chunk; more output will follow


class Origin(BaseModel):
    """Where a job entered the system, so its result can be routed back.

    Populated by an ingress connector and carried unchanged through the job's
    whole lifecycle.
    """

    connector: str = Field(description="Ingress connector name, e.g. 'slack'.")
    channel: str = Field(description="Channel/conversation id within the connector.")
    thread: str = Field(description="Thread id, used for affinity and reply targeting.")
    user: str | None = Field(
        default=None, description="Identifier of the requesting user, if known."
    )


class _BaseMessage(BaseModel):
    """Fields shared by every wire message."""

    message_id: UUID = Field(
        default_factory=uuid4, description="Unique id for this message."
    )
    timestamp: datetime = Field(
        default_factory=_utcnow, description="UTC creation time."
    )


class RegisterMessage(_BaseMessage):
    """Sent by an agent when it connects, announcing identity and capabilities."""

    type: Literal["register"] = "register"
    agent_name: str = Field(description="Stable, unique agent name, e.g. 'atlas'.")
    capabilities: Capabilities = Field(description="Self-reported capability manifest.")


class HeartbeatMessage(_BaseMessage):
    """Periodic liveness and status ping from an agent."""

    type: Literal["heartbeat"] = "heartbeat"
    agent_name: str = Field(description="Name of the agent emitting the heartbeat.")
    status: AgentStatus = Field(description="What the agent is currently doing.")
    current_job_id: UUID | None = Field(
        default=None, description="Job in progress, if status is WORKING."
    )
    detail: str | None = Field(
        default=None, description="Optional human-readable status detail."
    )


class JobMessage(_BaseMessage):
    """An instruction dispatched to an agent for execution."""

    type: Literal["job"] = "job"
    job_id: UUID = Field(
        default_factory=uuid4, description="Unique id correlating job and results."
    )
    instruction: str = Field(description="Free-text task for the agent to perform.")
    origin: Origin = Field(
        description="Where the job came from, for routing results back."
    )


class ResultMessage(_BaseMessage):
    """Output produced for a job — a streamed partial or the final result."""

    type: Literal["result"] = "result"
    job_id: UUID = Field(description="Id of the job this result belongs to.")
    status: ResultStatus = Field(
        description="Outcome, or PARTIAL for a streamed chunk."
    )
    content: str = Field(description="Result text or chunk content.")
    final: bool = Field(
        default=True, description="True if this is the last message for the job."
    )


Message = Annotated[
    Union[RegisterMessage, HeartbeatMessage, JobMessage, ResultMessage],
    Field(discriminator="type"),
]
"""Discriminated union of every wire message, keyed on the ``type`` field."""

_MESSAGE_ADAPTER: TypeAdapter[Message] = TypeAdapter(Message)


def parse_message(data: dict[str, Any] | str | bytes | bytearray) -> Message:
    """Parse a raw wire payload into the correct concrete message model.

    Accepts a mapping or a JSON string/bytes frame and returns the message type
    selected by its ``type`` discriminator.
    """
    if isinstance(data, (str, bytes, bytearray)):
        return _MESSAGE_ADAPTER.validate_json(data)
    return _MESSAGE_ADAPTER.validate_python(data)
