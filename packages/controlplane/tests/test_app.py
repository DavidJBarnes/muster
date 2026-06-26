"""Tests for the hub's HTTP + WebSocket surface via the FastAPI test client."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any
from uuid import uuid4

from fastapi.testclient import TestClient

from muster_contracts import (
    AgentStatus,
    Capabilities,
    HeartbeatMessage,
    JobMessage,
    RegisterMessage,
    ResultMessage,
    ResultStatus,
    parse_message,
)
from muster_controlplane.app import create_app

JOB_BODY = {
    "instruction": "say hi",
    "origin": {"connector": "test", "channel": "c", "thread": "t"},
}


def _poll(predicate: Callable[[], Any], *, tries: int = 100, delay: float = 0.02) -> Any:
    """Poll ``predicate`` until it returns truthy; fail loudly if it never does."""
    for _ in range(tries):
        value = predicate()
        if value:
            return value
        time.sleep(delay)
    raise AssertionError("condition not met within timeout")


def test_submit_without_agents_returns_503() -> None:
    """Dispatching with no connected agents is a 503."""
    client = TestClient(create_app())
    response = client.post("/jobs", json=JOB_BODY)
    assert response.status_code == 503


def test_read_unknown_job_is_empty() -> None:
    """An unknown job id reads back as empty and not final."""
    client = TestClient(create_app())
    data = client.get(f"/jobs/{uuid4()}").json()
    assert data == {"final": False, "results": []}


def test_agents_empty_by_default() -> None:
    """With nothing connected, the agent list is empty."""
    client = TestClient(create_app())
    assert client.get("/agents").json() == []


def test_full_round_trip_over_ws() -> None:
    """Register, see the agent, dispatch a job, stream a result, read it back."""
    client = TestClient(create_app())
    register = RegisterMessage(
        agent_name="atlas", capabilities=Capabilities(tools=["claude"])
    )

    with client.websocket_connect("/agent") as ws:
        ws.send_text(register.model_dump_json())

        agents = _poll(
            lambda: [a for a in client.get("/agents").json() if a["name"] == "atlas"]
        )
        assert agents[0]["status"] == AgentStatus.IDLE.value
        assert agents[0]["current_job_id"] is None
        assert agents[0]["capabilities"]["tools"] == ["claude"]

        # A heartbeat with a current job exercises the populated-job branch.
        job_id = uuid4()
        ws.send_text(
            HeartbeatMessage(
                agent_name="atlas",
                status=AgentStatus.WORKING,
                current_job_id=job_id,
            ).model_dump_json()
        )
        _poll(
            lambda: next(
                a
                for a in client.get("/agents").json()
                if a["name"] == "atlas"
            )["current_job_id"]
            == str(job_id)
        )

        # Dispatch a job and confirm the agent receives it on its socket.
        submitted = client.post("/jobs", json=JOB_BODY)
        dispatched_id = submitted.json()["job_id"]
        job = parse_message(ws.receive_text())
        assert isinstance(job, JobMessage)
        assert str(job.job_id) == dispatched_id

        # Stream a partial then a final result back over the socket.
        ws.send_text(
            ResultMessage(
                job_id=job.job_id,
                status=ResultStatus.PARTIAL,
                content="hi ",
                final=False,
            ).model_dump_json()
        )
        ws.send_text(
            ResultMessage(
                job_id=job.job_id,
                status=ResultStatus.SUCCESS,
                content="hi there",
                final=True,
            ).model_dump_json()
        )

        data = _poll(lambda: (lambda d: d if d["final"] else None)(
            client.get(f"/jobs/{dispatched_id}").json()
        ))
        assert [r["content"] for r in data["results"]] == ["hi ", "hi there"]
