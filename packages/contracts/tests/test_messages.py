"""Tests for the wire messages, enums, and the parse helper."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from muster_contracts.capabilities import Capabilities, GpuInfo
from muster_contracts.messages import (
    AgentStatus,
    HeartbeatMessage,
    JobMessage,
    Origin,
    RegisterMessage,
    ResultMessage,
    ResultStatus,
    parse_message,
)


def _origin() -> Origin:
    """Build a representative Origin for job/result tests."""
    return Origin(connector="slack", channel="C123", thread="T456", user="U789")


def test_enum_values() -> None:
    """Enum string values are the on-wire tokens."""
    assert AgentStatus.WORKING.value == "working"
    assert {s.value for s in AgentStatus} == {"idle", "working", "blocked"}
    assert ResultStatus.PARTIAL.value == "partial"


def test_origin_optional_user() -> None:
    """The requesting user is optional."""
    origin = Origin(connector="slack", channel="C1", thread="T1")
    assert origin.user is None


def test_base_fields_autopopulate() -> None:
    """Every message gets a uuid id and a tz-aware UTC timestamp by default."""
    msg = RegisterMessage(agent_name="atlas", capabilities=Capabilities())
    assert isinstance(msg.message_id, UUID)
    assert isinstance(msg.timestamp, datetime)
    assert msg.timestamp.tzinfo is timezone.utc


def test_register_message() -> None:
    """Register carries the agent name and its manifest."""
    caps = Capabilities(gpus=[GpuInfo(name="NVIDIA RTX 3090", vram_gb=24)])
    msg = RegisterMessage(agent_name="atlas", capabilities=caps)
    assert msg.type == "register"
    assert msg.agent_name == "atlas"
    assert msg.capabilities.gpus[0].name == "NVIDIA RTX 3090"


def test_heartbeat_message_defaults() -> None:
    """Heartbeat detail and current job are optional."""
    msg = HeartbeatMessage(agent_name="atlas", status=AgentStatus.IDLE)
    assert msg.type == "heartbeat"
    assert msg.current_job_id is None
    assert msg.detail is None


def test_heartbeat_message_working() -> None:
    """A working heartbeat can reference the in-flight job."""
    job_id = uuid4()
    msg = HeartbeatMessage(
        agent_name="atlas",
        status=AgentStatus.WORKING,
        current_job_id=job_id,
        detail="refactor gateway",
    )
    assert msg.current_job_id == job_id
    assert msg.detail == "refactor gateway"


def test_job_message() -> None:
    """A job auto-assigns a job_id and carries its origin."""
    msg = JobMessage(instruction="fix the fps correction", origin=_origin())
    assert msg.type == "job"
    assert isinstance(msg.job_id, UUID)
    assert msg.origin.connector == "slack"


def test_result_message_final_default() -> None:
    """Results are final unless marked otherwise."""
    job_id = uuid4()
    msg = ResultMessage(job_id=job_id, status=ResultStatus.SUCCESS, content="done")
    assert msg.type == "result"
    assert msg.final is True


def test_result_message_partial_chunk() -> None:
    """A streamed chunk is a non-final PARTIAL result."""
    msg = ResultMessage(
        job_id=uuid4(),
        status=ResultStatus.PARTIAL,
        content="working...",
        final=False,
    )
    assert msg.status is ResultStatus.PARTIAL
    assert msg.final is False


def test_parse_message_from_dict() -> None:
    """parse_message routes a mapping to the right concrete type."""
    parsed = parse_message(
        {"type": "heartbeat", "agent_name": "atlas", "status": "idle"}
    )
    assert isinstance(parsed, HeartbeatMessage)
    assert parsed.agent_name == "atlas"


def test_parse_message_from_json_string() -> None:
    """parse_message accepts a JSON string frame and round-trips a message."""
    original = JobMessage(instruction="deploy wanly", origin=_origin())
    parsed = parse_message(original.model_dump_json())
    assert isinstance(parsed, JobMessage)
    assert parsed.job_id == original.job_id


def test_parse_message_from_bytes() -> None:
    """parse_message accepts a bytes frame (as a WebSocket would deliver)."""
    original = RegisterMessage(agent_name="scout", capabilities=Capabilities())
    parsed = parse_message(original.model_dump_json().encode())
    assert isinstance(parsed, RegisterMessage)
    assert parsed.agent_name == "scout"


def test_parse_message_discriminates_all_types() -> None:
    """Each discriminator value selects its matching model."""
    samples = [
        RegisterMessage(agent_name="a", capabilities=Capabilities()),
        HeartbeatMessage(agent_name="a", status=AgentStatus.BLOCKED),
        JobMessage(instruction="x", origin=_origin()),
        ResultMessage(job_id=uuid4(), status=ResultStatus.ERROR, content="boom"),
    ]
    for sample in samples:
        assert type(parse_message(sample.model_dump(mode="json"))) is type(sample)


def test_parse_message_rejects_unknown_type() -> None:
    """An unrecognized discriminator fails validation."""
    with pytest.raises(ValidationError):
        parse_message({"type": "nope"})
